"""Deterministic session-start and mid-turn memory reader for ContextBuilder."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from langchain_core.messages import BaseMessage, SystemMessage

from support_agent.context.budget import ApproxTokenCounter, TokenCounter
from support_agent.memory.long_term.models import CustomerMemory
from support_agent.memory.long_term.store import CustomerMemoryStore
from support_agent.memory.settings import LongTermMemorySettings

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9/_-]{1,}")
_STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "your",
        "you",
        "have",
        "has",
        "was",
        "were",
        "are",
        "can",
        "how",
        "what",
        "when",
        "where",
        "please",
        "help",
        "about",
    }
)
_SESSION_HEADER = (
    "Customer memory hints (background hints only; never evidence, citations, or policy; "
    "always prefer what the customer says now):"
)


def _tokens(text: str) -> set[str]:
    return {
        tok
        for tok in _TOKEN_RE.findall(text.casefold())
        if tok not in _STOP_WORDS and len(tok) >= 2
    }


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, dot / (na * nb))


def relevance_score(
    memory: CustomerMemory,
    query: str,
    *,
    query_embedding: Sequence[float] | None = None,
) -> float:
    q_tokens = _tokens(query)
    m_tokens = _tokens(memory.content)
    lexical = len(q_tokens & m_tokens) / len(q_tokens) if q_tokens and m_tokens else 0.0
    if query_embedding is not None and memory.embedding is not None:
        semantic = _cosine(query_embedding, memory.embedding)
        return 0.5 * lexical + 0.5 * semantic
    return lexical


def combined_rank_score(
    memory: CustomerMemory,
    query: str,
    *,
    now: datetime,
    query_embedding: Sequence[float] | None = None,
) -> float:
    age_days = max(0.0, (now - memory.last_used_at).total_seconds() / 86400.0)
    recency = 1.0 / (1.0 + age_days / 30.0)
    rel = relevance_score(memory, query, query_embedding=query_embedding)
    return 0.65 * rel + 0.35 * recency


def format_memory_line(memory: CustomerMemory) -> str:
    day = memory.created_at.strftime("%Y-%m-%d")
    return f"- On {day} ({memory.kind}): {memory.content}"


def load_session_profile(
    store: CustomerMemoryStore,
    customer_id: str,
    first_message: str,
    settings: LongTermMemorySettings,
    *,
    now: datetime | None = None,
    counter: TokenCounter | None = None,
    query_embedding: Sequence[float] | None = None,
) -> tuple[str | None, list[str]]:
    """Load and deterministically render L1_session memory hints at conversation start."""
    ref_now = now or datetime.now(UTC)
    active = store.list_active(customer_id, now=ref_now)
    if not active:
        return None, []

    ranked = sorted(
        active,
        key=lambda m: (
            -combined_rank_score(m, first_message, now=ref_now, query_embedding=query_embedding),
            -m.last_used_at.timestamp(),
            m.id,
        ),
    )
    selected = ranked[: settings.session_top_k]
    # Canonical order by (created_at, id) so identical memory sets yield identical L1 bytes.
    selected.sort(key=lambda m: (m.created_at.isoformat(), m.id))

    tok_counter = counter or ApproxTokenCounter()
    lines: list[str] = [_SESSION_HEADER]
    used_tokens = tok_counter.count_text(_SESSION_HEADER)
    loaded_ids: list[str] = []

    for mem in selected:
        line = format_memory_line(mem)
        line_tokens = tok_counter.count_text(line)
        if used_tokens + line_tokens > settings.session_budget_tokens:
            continue
        lines.append(line)
        used_tokens += line_tokens
        loaded_ids.append(mem.id)

    if not loaded_ids:
        return None, []
    return "\n".join(lines), loaded_ids


def lookup_turn_memories(
    store: CustomerMemoryStore,
    customer_id: str,
    query: str,
    *,
    already_loaded_ids: Sequence[str],
    settings: LongTermMemorySettings,
    now: datetime | None = None,
    query_embedding: Sequence[float] | None = None,
) -> list[str]:
    """Fetch mid-conversation memories for L4_turn without mutating frozen L1_session."""
    ref_now = now or datetime.now(UTC)
    loaded = set(already_loaded_ids)
    candidates = [m for m in store.list_active(customer_id, now=ref_now) if m.id not in loaded]
    if not candidates:
        return []

    scored = [(relevance_score(m, query, query_embedding=query_embedding), m) for m in candidates]
    hits = [(score, m) for score, m in scored if score >= settings.mid_turn_min_relevance]
    if not hits:
        return []
    hits.sort(key=lambda item: (-item[0], -item[1].last_used_at.timestamp(), item[1].id))
    chosen = [m for _, m in hits[: settings.mid_turn_top_k]]
    return [format_memory_line(m) for m in chosen]


def format_turn_memory_messages(hints: Sequence[str]) -> list[BaseMessage]:
    """Render mid-conversation memory hints as an L4_turn message."""
    if not hints:
        return []
    body = (
        "Additional customer memory hints for this turn "
        "(background hints only; never evidence, citations, or policy):\n" + "\n".join(hints)
    )
    return [SystemMessage(content=body)]
