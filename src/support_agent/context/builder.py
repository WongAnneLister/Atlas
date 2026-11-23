"""Single prefix-stable, budgeted ContextBuilder used by every LLM call."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from support_agent.context.budget import (
    ApproxTokenCounter,
    ContextBreakdown,
    ContextOverflow,
    DroppedItem,
    TokenCounter,
)
from support_agent.context.cache_adapter import Breakpoint, apply_cache_breakpoints
from support_agent.context.sections import (
    LAYER_ORDER,
    StabilityLayer,
    canonical_json,
    compress_tool_result,
    render_shared_l0,
    sanitise_history_messages,
)
from support_agent.context.settings import ContextSettings
from support_agent.retrieval.types import RetrievedChunk

logger = logging.getLogger(__name__)


class BuiltContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    node: str
    messages: list[BaseMessage]
    breakpoints: list[Breakpoint] = Field(default_factory=list)
    breakdown: ContextBreakdown
    prefix_hash: str
    l0_hash: str
    prefix_message_count: int = Field(default=0, ge=0)
    prefix_bytes: bytes = Field(default=b"", exclude=True)

    def __len__(self) -> int:
        return len(self.messages)

    def __getitem__(self, index: Any) -> Any:
        return self.messages[index]

    def __iter__(self) -> Iterator[BaseMessage]:  # type: ignore[override]
        return iter(self.messages)


class ContextCallRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    node: str
    prefix_hash: str
    l0_hash: str
    total_tokens: int = Field(ge=0)
    budget_tokens: int = Field(gt=0)
    by_layer: dict[StabilityLayer, int]
    by_section: dict[str, int]
    dropped_count: int = Field(default=0, ge=0)
    history_capped: bool = False
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cache_hit_ratio: float = Field(default=0.0, ge=0.0, le=1.0)


_context_records: ContextVar[list[ContextCallRecord] | None] = ContextVar(
    "context_call_records", default=None
)


@contextmanager
def collect_context_records() -> Iterator[list[ContextCallRecord]]:
    records: list[ContextCallRecord] = []
    token = _context_records.set(records)
    try:
        yield records
    finally:
        _context_records.reset(token)


def record_context_call(record: ContextCallRecord, *, observer: object | None = None) -> None:
    records = _context_records.get()
    if records is not None:
        records.append(record)
    callback = getattr(observer, "context_call", None)
    if callable(callback):
        callback(record)


def _serialise_messages(messages: Sequence[BaseMessage]) -> bytes:
    payload = [{"role": msg.type, "content": msg.content} for msg in messages]
    return canonical_json(payload).encode("utf-8")


def _render_evidence_chunk(index: int, chunk: RetrievedChunk) -> str:
    return f"[{index}] {chunk.heading_path}\n{chunk.text}"


class ContextBuilder:
    """Assemble budgeted, prefix-stable messages for every model call."""

    def __init__(
        self,
        settings: ContextSettings,
        *,
        llm_provider: str | None = None,
        counter: TokenCounter | None = None,
    ) -> None:
        self.settings = settings
        self.llm_provider = llm_provider
        self.counter: TokenCounter = counter or ApproxTokenCounter(
            chars_per_token=settings.chars_per_token,
            message_overhead=settings.message_overhead_tokens,
        )

    def build(
        self,
        node: str,
        *,
        task_prompt: str,
        user_text: str = "",
        history: Sequence[BaseMessage] = (),
        customer_profile: str | None = None,
        compacted_blocks: Sequence[str] = (),
        evidence: Sequence[RetrievedChunk] = (),
        good_evidence_count: int = 0,
        order_context: dict[str, Any] | None = None,
        order_context_never_trim: bool = False,
        tool_results: Sequence[tuple[str, Any]] = (),
        tool_names: Sequence[str] = (),
        pinned_facts: dict[str, Any] | None = None,
        current_date: date | str | None = None,
        extra_l4_messages: Sequence[BaseMessage] = (),
    ) -> BuiltContext:
        profile = self.settings.profile_for(node)
        budget = profile.total_tokens
        ttls = self.settings.cache_adapter.layer_ttls
        by_layer: dict[StabilityLayer, int] = dict.fromkeys(LAYER_ORDER, 0)
        by_section: dict[str, int] = {}
        dropped: list[DroppedItem] = []

        messages: list[BaseMessage] = []
        breakpoints: list[Breakpoint] = []

        # --- L0_global (never trimmed; shared verbatim across main-conversation nodes) ---
        l0_text = render_shared_l0(tool_names) if profile.share_prefix else task_prompt
        l0_msg = SystemMessage(content=l0_text)
        l0_tokens = self.counter.count_message(l0_msg)
        messages.append(l0_msg)
        by_layer["L0_global"] += l0_tokens
        by_section["system_instructions"] = l0_tokens
        l0_bytes = _serialise_messages([l0_msg])
        l0_hash = hashlib.sha256(l0_bytes).hexdigest()
        breakpoints.append(
            Breakpoint(
                layer="L0_global",
                message_index=len(messages) - 1,
                prefix_tokens=l0_tokens,
                ttl_s=ttls.get("L0_global", 3600),
            )
        )

        # --- L1_session (once per conversation; populated in Commit 30) ---
        if customer_profile and customer_profile.strip():
            l1_msg = SystemMessage(content=f"Customer profile:\n{customer_profile.strip()}")
            l1_tokens = self.counter.count_message(l1_msg)
            messages.append(l1_msg)
            by_layer["L1_session"] += l1_tokens
            by_section["customer_profile"] = l1_tokens
            breakpoints.append(
                Breakpoint(
                    layer="L1_session",
                    message_index=len(messages) - 1,
                    prefix_tokens=sum(by_layer.values()),
                    ttl_s=ttls.get("L1_session", 300),
                )
            )

        # --- L2_compacted (frozen summary blocks; populated in Commit 29) ---
        if compacted_blocks:
            l2_tokens = 0
            for idx, block in enumerate(compacted_blocks):
                if not block.strip():
                    continue
                b_msg = SystemMessage(
                    content=f"Conversation summary block {idx + 1}:\n{block.strip()}"
                )
                t = self.counter.count_message(b_msg)
                messages.append(b_msg)
                l2_tokens += t
            if l2_tokens:
                by_layer["L2_compacted"] += l2_tokens
                by_section["conversation_summary"] = l2_tokens
                breakpoints.append(
                    Breakpoint(
                        layer="L2_compacted",
                        message_index=len(messages) - 1,
                        prefix_tokens=sum(by_layer.values()),
                        ttl_s=ttls.get("L2_compacted", 300),
                    )
                )

        # --- L3_history (append-only; temporary hard cap until Commit 29 compaction) ---
        history_capped = False
        cleaned_history = sanitise_history_messages(history)
        if profile.history_max_tokens > 0 and cleaned_history:
            turn_cap = (
                profile.recent_turns
                if profile.recent_turns is not None
                else self.settings.hard_history_turn_cap
            )
            max_msgs = turn_cap * 2
            if len(cleaned_history) > max_msgs:
                dropped_msgs = cleaned_history[:-max_msgs]
                cleaned_history = cleaned_history[-max_msgs:]
                history_capped = True
                logger.info(
                    "ContextBuilder[%s] hit temporary history cap (%d turns); "
                    "cache-breaking fallback until Commit 29 compaction",
                    node,
                    turn_cap,
                )
                dropped.append(
                    DroppedItem(
                        section="recent_turns",
                        reason="hard_history_turn_cap",
                        tokens_dropped=sum(self.counter.count_message(m) for m in dropped_msgs),
                    )
                )
            l3_tokens = 0
            for msg in cleaned_history:
                t = self.counter.count_message(msg)
                messages.append(msg)
                l3_tokens += t
            if l3_tokens:
                by_layer["L3_history"] += l3_tokens
                by_section["recent_turns"] = l3_tokens
                breakpoints.append(
                    Breakpoint(
                        layer="L3_history",
                        message_index=len(messages) - 1,
                        prefix_tokens=sum(by_layer.values()),
                        ttl_s=ttls.get("L3_history", 300),
                    )
                )

        prefix_message_count = len(messages)
        prefix_bytes = _serialise_messages(messages)
        prefix_hash = hashlib.sha256(prefix_bytes).hexdigest()
        prefix_tokens = sum(by_layer.values())

        # --- L4_turn (never-trim items first, then trimmable sections inside remaining budget) ---
        l4_fixed: list[tuple[str, BaseMessage, int]] = []
        if profile.share_prefix and task_prompt.strip():
            m = SystemMessage(content=f"Task instructions ({node}):\n{task_prompt.strip()}")
            l4_fixed.append(("task_instructions", m, self.counter.count_message(m)))
        if current_date is not None:
            day_str = (
                current_date.isoformat() if isinstance(current_date, date) else str(current_date)
            )
            m = SystemMessage(content=f"Current date: {day_str}")
            l4_fixed.append(("current_date", m, self.counter.count_message(m)))
        if order_context is not None and order_context_never_trim:
            m = SystemMessage(content=f"Order context:\n{canonical_json(order_context)}")
            l4_fixed.append(("order_context", m, self.counter.count_message(m)))
        if user_text:
            u_msg = HumanMessage(content=user_text)
            l4_fixed.append(("user_message", u_msg, self.counter.count_message(u_msg)))

        required_tokens = prefix_tokens + sum(t for _, _, t in l4_fixed)
        if required_tokens > budget:
            raise ContextOverflow(node, required_tokens, budget)

        remaining = budget - required_tokens
        l4_optional: list[tuple[str, BaseMessage, int]] = []

        # 1. Pinned facts (high priority in L4)
        if pinned_facts:
            m = SystemMessage(content=f"Pinned facts:\n{canonical_json(pinned_facts)}")
            t = self.counter.count_message(m)
            if t <= remaining:
                l4_optional.append(("pinned_facts", m, t))
                remaining -= t
            else:
                dropped.append(
                    DroppedItem(section="pinned_facts", reason="budget", tokens_dropped=t)
                )

        # 2. Order context (when trimmable)
        if order_context is not None and not order_context_never_trim:
            m = SystemMessage(content=f"Order context:\n{canonical_json(order_context)}")
            t = self.counter.count_message(m)
            if t <= remaining:
                l4_optional.append(("order_context", m, t))
                remaining -= t
            else:
                dropped.append(
                    DroppedItem(section="order_context", reason="budget", tokens_dropped=t)
                )

        # 3. Compressed tool results
        if tool_results:
            kept_tools: list[str] = []
            for tool_name, payload in tool_results:
                compressed = f"{tool_name}: {compress_tool_result(tool_name, payload)}"
                candidate = SystemMessage(
                    content="Tool results:\n" + "\n".join([*kept_tools, compressed])
                )
                t = self.counter.count_message(candidate)
                if t <= remaining:
                    kept_tools.append(compressed)
                else:
                    dropped.append(
                        DroppedItem(
                            section="tool_results",
                            reason="budget",
                            tokens_dropped=self.counter.count_text(compressed),
                        )
                    )
            if kept_tools:
                m = SystemMessage(content="Tool results:\n" + "\n".join(kept_tools))
                t = self.counter.count_message(m)
                l4_optional.append(("tool_results", m, t))
                remaining -= t

        # 4. Retrieved evidence (trimmed lowest-rerank-first, never below good_evidence_count)
        if evidence:
            indexed = list(enumerate(evidence, start=1))
            kept_ev = list(indexed)
            min_keep = min(max(0, good_evidence_count), len(indexed))
            while kept_ev:
                rendered = "Sources:\n" + "\n\n".join(
                    _render_evidence_chunk(idx, chunk) for idx, chunk in kept_ev
                )
                m = SystemMessage(content=rendered)
                t = self.counter.count_message(m)
                if t <= remaining:
                    l4_optional.append(("retrieved_evidence", m, t))
                    remaining -= t
                    break
                if len(kept_ev) <= min_keep:
                    # Never drop below the gate's good_count chunks -> signal overflow.
                    raise ContextOverflow(node, budget - remaining + t, budget)
                _, removed_chunk = kept_ev.pop()
                dropped.append(
                    DroppedItem(
                        section="retrieved_evidence",
                        reason="lowest_rerank_trimmed",
                        tokens_dropped=self.counter.count_text(removed_chunk.text),
                    )
                )

        # 5. Extra L4 messages (e.g. tool-loop turns inside ToolsPath)
        extra_kept: list[BaseMessage] = []
        for msg in extra_l4_messages:
            t = self.counter.count_message(msg)
            if t <= remaining:
                extra_kept.append(msg)
                remaining -= t
            else:
                dropped.append(
                    DroppedItem(section="extra_l4_messages", reason="budget", tokens_dropped=t)
                )
        if extra_kept:
            t_extra = sum(self.counter.count_message(m) for m in extra_kept)
            by_layer["L4_turn"] += t_extra
            by_section["extra_l4_messages"] = t_extra

        # Assemble L4 strictly in order: system L4 items -> user_message -> extra_l4_messages
        l4_user: list[tuple[str, BaseMessage, int]] = []
        l4_sys: list[tuple[str, BaseMessage, int]] = []
        for name, msg, tok in [*l4_fixed, *l4_optional]:
            if name == "user_message":
                l4_user.append((name, msg, tok))
            else:
                l4_sys.append((name, msg, tok))

        for name, msg, tok in [*l4_sys, *l4_user]:
            messages.append(msg)
            by_layer["L4_turn"] += tok
            by_section[name] = by_section.get(name, 0) + tok
        messages.extend(extra_kept)

        total_tokens = sum(by_layer.values())
        adapted_messages, active_breakpoints = apply_cache_breakpoints(
            messages,
            breakpoints,
            self.settings.cache_adapter,
            llm_provider=self.llm_provider,
        )
        breakdown = ContextBreakdown(
            node=node,
            total_tokens=total_tokens,
            budget_tokens=budget,
            by_layer=by_layer,
            by_section=by_section,
            dropped=dropped,
            prefix_hash=prefix_hash,
            l0_hash=l0_hash,
            history_capped=history_capped,
        )
        return BuiltContext(
            node=node,
            messages=adapted_messages,
            breakpoints=active_breakpoints,
            breakdown=breakdown,
            prefix_hash=prefix_hash,
            l0_hash=l0_hash,
            prefix_message_count=prefix_message_count,
            prefix_bytes=prefix_bytes,
        )


def extract_usage_details(message: Any) -> tuple[int, int, int, int]:
    """Extract (input, output, cache_read, cache_write) token counts from an AIMessage."""
    if not isinstance(message, AIMessage):
        return 0, 0, 0, 0
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict):
        resp_meta = getattr(message, "response_metadata", None)
        usage = resp_meta.get("token_usage") if isinstance(resp_meta, dict) else None
    if not isinstance(usage, dict):
        return 0, 0, 0, 0
    in_tok = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    out_tok = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    details = usage.get("input_token_details") or usage.get("prompt_tokens_details") or {}
    cache_read = 0
    cache_write = 0
    if isinstance(details, dict):
        cache_read = int(details.get("cache_read", details.get("cached_tokens", 0)) or 0)
        cache_write = int(details.get("cache_creation", 0) or 0)
    return in_tok, out_tok, cache_read, cache_write
