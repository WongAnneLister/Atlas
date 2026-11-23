"""Cache-friendly chunked compaction into immutable L2 summary blocks."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field

from support_agent.context.budget import ApproxTokenCounter, TokenCounter
from support_agent.memory.settings import ShortTermMemorySettings

if TYPE_CHECKING:
    from support_agent.context.builder import ContextBuilder
    from support_agent.reliability.llm_calls import ReliableModels

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[2] / "graph" / "prompts" / "summarise_chunk.md"

_TOKEN_ID_OR_NUM = re.compile(
    r"\b(?:ORD-\d+|BHD\d+/\d+|HD\d+X?|TAH\d+|\d+E\d+N\d+A|\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


class SummaryBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    block_id: str = Field(min_length=1)
    turns: tuple[int, int]
    text: str = Field(min_length=1)
    created_at_turn: int = Field(ge=1)
    extractive_fallback: bool = False


class CompactionResult(BaseModel):
    blocks: list[SummaryBlock] = Field(default_factory=list)
    active_history_start: int = Field(default=0, ge=0)
    compacted_chunks: int = Field(default=0, ge=0)
    second_level_merges: int = Field(default=0, ge=0)
    summariser_calls: int = Field(default=0, ge=0)
    extractive_fallbacks: int = Field(default=0, ge=0)


def group_into_turns(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
    """Group messages into atomic turns without ever splitting user/AI or tool call/result pairs."""
    groups: list[list[BaseMessage]] = []
    current: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, HumanMessage) and current:
            # Never split a pending tool_calls AIMessage from its following ToolMessage.
            last = current[-1]
            if not (isinstance(last, AIMessage) and getattr(last, "tool_calls", None)):
                groups.append(current)
                current = [msg]
                continue
        current.append(msg)
    if current:
        groups.append(current)
    return groups


def _render_chunk(messages: Sequence[BaseMessage]) -> str:
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        role = "Customer" if isinstance(msg, HumanMessage) else "Agent"
        if content.strip():
            lines.append(f"{role}: {content.strip()}")
    return "\n".join(lines)


def validate_summary_numbers(summary: str, chunk_text: str) -> list[str]:
    """Return any ID or number in `summary` that does not appear in `chunk_text`."""
    chunk_tokens = {m.group(0).upper() for m in _TOKEN_ID_OR_NUM.finditer(chunk_text)}
    invented: list[str] = []
    for match in _TOKEN_ID_OR_NUM.finditer(summary):
        token = match.group(0).upper()
        if token not in chunk_tokens and token not in invented:
            invented.append(token)
    return invented


def extractive_summary(messages: Sequence[BaseMessage], *, max_chars: int = 500) -> str:
    """Deterministic fallback keeping key verbatim lines (IDs, numbers, first/last user turns)."""
    lines: list[str] = []
    seen: set[str] = set()
    human_msgs = [
        m.content.strip()
        for m in messages
        if isinstance(m, HumanMessage) and isinstance(m.content, str) and m.content.strip()
    ]
    for candidate in human_msgs[:1] + human_msgs[-1:]:
        if candidate not in seen:
            seen.add(candidate)
            lines.append(f"- Customer: {candidate}")
    for msg in messages:
        if isinstance(msg, ToolMessage) or not isinstance(msg.content, str):
            continue
        text = msg.content.strip()
        if text and text not in seen and _TOKEN_ID_OR_NUM.search(text):
            seen.add(text)
            role = "Customer" if isinstance(msg, HumanMessage) else "Agent"
            lines.append(f"- {role}: {text[:180]}")
    joined = "\n".join(lines) if lines else "- Earlier conversation turns compacted."
    return joined[:max_chars]


def _summarise_chunk(
    chunk_messages: Sequence[BaseMessage],
    existing_blocks: Sequence[SummaryBlock],
    *,
    models: ReliableModels | None,
    builder: ContextBuilder | None,
    settings: ShortTermMemorySettings,
    prompt_text: str,
) -> tuple[str, int, bool]:
    """Summarise one chunk reusing parent's L0..L2 prefix; validate -> retry -> extractive."""
    chunk_text = _render_chunk(chunk_messages)
    if not chunk_text.strip():
        return extractive_summary(chunk_messages), 0, True
    if models is None or builder is None:
        return extractive_summary(chunk_messages), 0, True

    calls = 0
    note = ""
    for attempt in range(2):
        task_prompt = prompt_text if not note else f"{prompt_text}\n\nCorrection: {note}"
        try:
            built = builder.build(
                "summarise",
                task_prompt=task_prompt,
                user_text=f"Conversation chunk to summarise:\n{chunk_text}",
                compacted_blocks=[b.text for b in existing_blocks],
                history=(),
            )
            calls += 1
            response, _ = models.invoke("summarise", settings.summariser_role, built)
            candidate = response.content.strip() if isinstance(response.content, str) else ""
        except Exception as error:
            logger.warning(
                "Chunk summariser failed on attempt %d: %s", attempt + 1, type(error).__name__
            )
            break
        if not candidate:
            note = "Return a non-empty bullet summary."
            continue
        invented = validate_summary_numbers(candidate, chunk_text)
        if not invented:
            return candidate, calls, False
        logger.info("Summary contained ungrounded numbers %s; retrying once", invented)
        note = f"Remove these numbers/IDs not present in the chunk: {', '.join(invented)}."

    logger.info("Falling back to extractive summary for chunk")
    return extractive_summary(chunk_messages), calls, True


def _block_id(turns: tuple[int, int], text: str) -> str:
    digest = hashlib.sha256(f"{turns[0]}:{turns[1]}:{text}".encode()).hexdigest()[:12]
    return f"blk-{turns[0]}-{turns[1]}-{digest}"


def _tokens_of_messages(messages: Sequence[BaseMessage], counter: TokenCounter) -> int:
    return sum(counter.count_message(m) for m in messages)


def _tokens_of_blocks(blocks: Sequence[SummaryBlock], counter: TokenCounter) -> int:
    return sum(counter.count_text(b.text) + 6 for b in blocks)


def compact_history(
    all_history: Sequence[BaseMessage],
    *,
    active_history_start: int,
    existing_blocks: Sequence[SummaryBlock],
    current_turn: int,
    settings: ShortTermMemorySettings,
    models: ReliableModels | None = None,
    builder: ContextBuilder | None = None,
    counter: TokenCounter | None = None,
) -> CompactionResult:
    """Compact oldest whole chunks into immutable L2 blocks with hysteresis and L2 merging."""
    blocks = list(existing_blocks)
    start = min(max(0, active_history_start), len(all_history))
    if not settings.enabled or not settings.compaction_enabled:
        return CompactionResult(blocks=blocks, active_history_start=start)

    tok_counter: TokenCounter = counter or (
        builder.counter if builder is not None else ApproxTokenCounter()
    )
    active_msgs = list(all_history[start:])
    if _tokens_of_messages(active_msgs, tok_counter) <= settings.history_budget:
        return CompactionResult(blocks=blocks, active_history_start=start)

    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    target_tokens = int(settings.history_budget * settings.low_watermark)
    compacted_chunks = 0
    summariser_calls = 0
    extractive_fallbacks = 0
    second_level_merges = 0

    if settings.strategy == "rolling":
        # Rolling baseline (Commit 35 comparison only): rewrites one summary block every trigger.
        groups = group_into_turns(active_msgs)
        keep_groups = max(1, len(groups) - max(1, settings.chunk_turns))
        to_fold_groups = groups[:-keep_groups] if len(groups) > 1 else []
        if to_fold_groups:
            folded_msgs = [m for grp in to_fold_groups for m in grp]
            prior_text = "\n".join(b.text for b in blocks)
            combined = (
                [HumanMessage(content=f"Previous summary:\n{prior_text}"), *folded_msgs]
                if prior_text
                else folded_msgs
            )
            text, calls, used_fallback = _summarise_chunk(
                combined,
                (),
                models=models,
                builder=builder,
                settings=settings,
                prompt_text=prompt_text,
            )
            summariser_calls += calls
            extractive_fallbacks += int(used_fallback)
            start += len(folded_msgs)
            blocks = [
                SummaryBlock(
                    block_id=_block_id((1, current_turn), text),
                    turns=(1, current_turn),
                    text=text,
                    created_at_turn=current_turn,
                    extractive_fallback=used_fallback,
                )
            ]
            compacted_chunks = 1
        return CompactionResult(
            blocks=blocks,
            active_history_start=start,
            compacted_chunks=compacted_chunks,
            summariser_calls=summariser_calls,
            extractive_fallbacks=extractive_fallbacks,
        )

    # Default strategy: cache-friendly chunked compaction into immutable frozen blocks.
    while _tokens_of_messages(active_msgs, tok_counter) > target_tokens:
        groups = group_into_turns(active_msgs)
        if len(groups) < 2:
            break
        take = min(settings.chunk_turns, len(groups) - 1)
        chunk_groups = groups[:take]
        chunk_msgs = [m for grp in chunk_groups for m in grp]
        turn_start = (blocks[-1].turns[1] + 1) if blocks else 1
        turn_end = turn_start + take - 1

        text, calls, used_fallback = _summarise_chunk(
            chunk_msgs,
            blocks,
            models=models,
            builder=builder,
            settings=settings,
            prompt_text=prompt_text,
        )
        summariser_calls += calls
        extractive_fallbacks += int(used_fallback)
        blocks.append(
            SummaryBlock(
                block_id=_block_id((turn_start, turn_end), text),
                turns=(turn_start, turn_end),
                text=text,
                created_at_turn=current_turn,
                extractive_fallback=used_fallback,
            )
        )
        start += len(chunk_msgs)
        active_msgs = list(all_history[start:])
        compacted_chunks += 1

    # Second-level compaction: if L2_compacted exceeds summary_budget, merge oldest two blocks.
    while len(blocks) >= 2 and _tokens_of_blocks(blocks, tok_counter) > settings.summary_budget:
        oldest_two = blocks[:2]
        merged_input = [
            HumanMessage(content=f"Block {b.turns[0]}-{b.turns[1]}:\n{b.text}") for b in oldest_two
        ]
        merged_text, calls, used_fallback = _summarise_chunk(
            merged_input,
            (),
            models=models,
            builder=builder,
            settings=settings,
            prompt_text=prompt_text,
        )
        summariser_calls += calls
        extractive_fallbacks += int(used_fallback)
        span = (oldest_two[0].turns[0], oldest_two[1].turns[1])
        merged_block = SummaryBlock(
            block_id=_block_id(span, merged_text),
            turns=span,
            text=merged_text,
            created_at_turn=current_turn,
            extractive_fallback=used_fallback,
        )
        blocks = [merged_block, *blocks[2:]]
        second_level_merges += 1

    return CompactionResult(
        blocks=blocks,
        active_history_start=start,
        compacted_chunks=compacted_chunks,
        second_level_merges=second_level_merges,
        summariser_calls=summariser_calls,
        extractive_fallbacks=extractive_fallbacks,
    )
