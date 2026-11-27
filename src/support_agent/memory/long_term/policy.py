"""Governed write policy and LLM extraction for long-term customer memories."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

from support_agent.context.builder import ContextBuilder
from support_agent.guardrails.pii import find_pii, redact_pii
from support_agent.memory.long_term.models import (
    CustomerMemory,
    MemoryCandidate,
    WriteDecision,
)
from support_agent.memory.long_term.store import CustomerMemoryStore
from support_agent.memory.settings import ALL_MEMORY_KINDS, LongTermMemorySettings, MemoryKind
from support_agent.memory.short_term.compaction import SummaryBlock
from support_agent.memory.short_term.facts import PinnedFacts
from support_agent.reliability.llm_calls import ReliableModels

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[2] / "graph" / "prompts" / "extract_memories.md"

_PAYMENT_PATTERN = re.compile(
    r"\b(?:cvv|cvc|iban|swift|bic|routing\s*number|sort\s*code|bank\s*account|"
    r"account\s*number|credit\s*card|debit\s*card|visa|mastercard|amex|"
    r"card\s*ending|expir(?:y|ation)\s*date|pin\s*code)\b",
    re.IGNORECASE,
)
_THIRD_PARTY_PATTERN = re.compile(
    r"\b(?:my\s+(?:wife|husband|partner|spouse|friend|colleague|coworker|boss|"
    r"manager|neighbor|neighbour|sister|brother|mother|father|mom|dad|son|"
    r"daughter|assistant|roommate)|for\s+(?:mr|mrs|ms|dr)\.?\s+[A-Z][a-z]+|"
    r"someone\s+else(?:'s)?|third[- ]party)\b",
    re.IGNORECASE,
)
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
        "customer",
        "user",
        "reported",
        "prefers",
        "owns",
        "about",
    }
)


class ExtractedMemories(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)


def _content_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in _TOKEN_RE.findall(text.casefold())
        if tok not in _STOP_WORDS and len(tok) >= 2
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _normalise_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _redact_structured(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            cleaned[key] = redact_pii(value).strip()
        elif isinstance(value, list):
            cleaned[key] = [redact_pii(v).strip() if isinstance(v, str) else v for v in value]
        elif isinstance(value, dict):
            cleaned[key] = _redact_structured(value)
        else:
            cleaned[key] = value
    return cleaned


def _contains_payment_data(text: str, structured: dict[str, Any]) -> bool:
    combined = f"{text} {structured}"
    if _PAYMENT_PATTERN.search(combined):
        return True
    return any(match.kind == "card" for match in find_pii(combined))


def _contains_third_party_pii(text: str, structured: dict[str, Any]) -> bool:
    combined = f"{text} {structured}"
    return bool(_THIRD_PARTY_PATTERN.search(combined))


def _subject_key(structured: dict[str, Any]) -> str | None:
    for field in ("subject", "topic", "preference_key", "product", "model", "order_id"):
        val = structured.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip().casefold()
    return None


def make_idempotency_key(
    customer_id: str,
    conversation_id: str,
    kind: str,
    redacted_content: str,
) -> str:
    raw = f"{customer_id}|{conversation_id}|{kind}|{_normalise_text(redacted_content)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def evaluate_candidate(
    candidate: MemoryCandidate,
    existing: Sequence[CustomerMemory],
    settings: LongTermMemorySettings,
    *,
    now: datetime | None = None,
) -> WriteDecision:
    """Apply deterministic governance rules to one candidate memory."""
    ref_now = now or datetime.now(UTC)
    if candidate.kind not in settings.allowed_kinds or candidate.kind not in ALL_MEMORY_KINDS:
        return WriteDecision(accepted=False, action="reject", reason="disallowed_kind")

    if candidate.confidence < settings.min_confidence:
        return WriteDecision(accepted=False, action="reject", reason="low_confidence")

    if _contains_payment_data(candidate.content, candidate.structured):
        return WriteDecision(accepted=False, action="reject", reason="payment_data")

    if _contains_third_party_pii(candidate.content, candidate.structured):
        return WriteDecision(accepted=False, action="reject", reason="third_party_personal_data")

    redacted = " ".join(redact_pii(candidate.content).split())
    redacted_structured = _redact_structured(candidate.structured)
    if len(redacted) < settings.min_content_chars:
        return WriteDecision(accepted=False, action="reject", reason="content_too_short")
    if len(redacted) > settings.max_content_chars:
        return WriteDecision(accepted=False, action="reject", reason="content_too_long")

    kind: MemoryKind = candidate.kind
    ttl_days = settings.ttl_days.get(kind, 90)
    expires_at = ref_now + timedelta(days=ttl_days)

    cand_norm = _normalise_text(redacted)
    cand_tokens = _content_tokens(redacted)
    cand_subject = _subject_key(redacted_structured)

    best_match: CustomerMemory | None = None
    best_sim = 0.0
    same_subject_match: CustomerMemory | None = None

    for mem in existing:
        if mem.kind != kind:
            continue
        if _normalise_text(mem.content) == cand_norm:
            return WriteDecision(
                accepted=True,
                action="refresh",
                reason="exact_duplicate",
                redacted_content=redacted,
                redacted_structured=redacted_structured,
                expires_at=expires_at,
                target_memory_id=mem.id,
            )
        sim = _jaccard(cand_tokens, _content_tokens(mem.content))
        if sim > best_sim:
            best_sim = sim
            best_match = mem
        mem_subject = _subject_key(mem.structured)
        if cand_subject and mem_subject and cand_subject == mem_subject:
            same_subject_match = mem

    if best_match is not None and best_sim >= settings.dedupe_similarity_threshold:
        return WriteDecision(
            accepted=True,
            action="refresh",
            reason="near_duplicate",
            redacted_content=redacted,
            redacted_structured=redacted_structured,
            expires_at=expires_at,
            target_memory_id=best_match.id,
        )

    supersede_target = same_subject_match or (
        best_match if best_sim >= settings.supersede_similarity_threshold else None
    )
    if supersede_target is not None:
        return WriteDecision(
            accepted=True,
            action="supersede",
            reason="supersedes_existing",
            redacted_content=redacted,
            redacted_structured=redacted_structured,
            expires_at=expires_at,
            target_memory_id=supersede_target.id,
        )

    return WriteDecision(
        accepted=True,
        action="insert",
        reason="accepted",
        redacted_content=redacted,
        redacted_structured=redacted_structured,
        expires_at=expires_at,
    )


def apply_write_policy(
    store: CustomerMemoryStore,
    customer_id: str,
    candidates: Sequence[MemoryCandidate],
    *,
    conversation_id: str,
    settings: LongTermMemorySettings,
    now: datetime | None = None,
) -> list[tuple[WriteDecision, CustomerMemory | None]]:
    """Evaluate and persist candidate memories for one customer."""
    ref_now = now or datetime.now(UTC)
    existing = list(store.list_active(customer_id, now=ref_now))
    results: list[tuple[WriteDecision, CustomerMemory | None]] = []

    for candidate in candidates:
        decision = evaluate_candidate(candidate, existing, settings, now=ref_now)
        if not decision.accepted or decision.expires_at is None:
            results.append((decision, None))
            continue

        kind: MemoryKind = candidate.kind  # type: ignore[assignment]
        if decision.action == "refresh" and decision.target_memory_id:
            store.refresh_last_used(
                customer_id,
                decision.target_memory_id,
                now=ref_now,
                new_expires_at=decision.expires_at,
            )
            refreshed = store.get(customer_id, decision.target_memory_id)
            results.append((decision, refreshed))
            continue

        if decision.action == "insert" and len(existing) >= settings.max_memories_per_customer:
            results.append(
                (
                    WriteDecision(
                        accepted=False,
                        action="reject",
                        reason="customer_memory_cap_reached",
                    ),
                    None,
                )
            )
            continue

        idem_key = make_idempotency_key(
            customer_id, conversation_id, kind, decision.redacted_content
        )
        stored = store.insert(
            customer_id,
            kind=kind,
            content=decision.redacted_content,
            structured=decision.redacted_structured,
            source_conversation_id=conversation_id,
            source_turn=candidate.source_turn,
            expires_at=decision.expires_at,
            confidence=candidate.confidence,
            idempotency_key=idem_key,
            now=ref_now,
            supersede_id=(decision.target_memory_id if decision.action == "supersede" else None),
        )
        if decision.action == "supersede" and decision.target_memory_id:
            existing = [m for m in existing if m.id != decision.target_memory_id]
        existing.append(stored)
        results.append((decision, stored))

    return results


def extract_memory_candidates(
    *,
    pinned_facts: PinnedFacts,
    compacted_blocks: Sequence[SummaryBlock],
    messages: Sequence[BaseMessage],
    models: ReliableModels,
    builder: ContextBuilder,
    settings: LongTermMemorySettings,
    strict: bool = False,
) -> list[MemoryCandidate]:
    """Use the fast model with structured output to propose memory candidates."""
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    parts: list[str] = []
    rendered_facts = pinned_facts.render_dict()
    if rendered_facts:
        parts.append(f"Pinned facts: {rendered_facts}")
    if compacted_blocks:
        parts.append("Conversation summaries:\n" + "\n".join(b.text for b in compacted_blocks))
    recent = [
        f"{m.type}: {m.content}"
        for m in messages[-8:]
        if isinstance(m.content, str) and m.content.strip()
    ]
    if recent:
        parts.append("Recent messages:\n" + "\n".join(recent))
    if not parts:
        return []
    user_text = "\n\n".join(parts)
    try:
        built = builder.build(
            "extract_memories",
            task_prompt=prompt,
            user_text=user_text,
        )
        parsed, _ = models.structured(
            "extract_memories",
            settings.extractor_role,
            ExtractedMemories,
            built,
        )
        return list(parsed.value.candidates)
    except Exception as error:
        # Evals pass strict=True: a failed call must not look like "nothing worth storing".
        if strict:
            raise
        logger.warning("Long-term memory extraction failed: %s", type(error).__name__)
        return []
