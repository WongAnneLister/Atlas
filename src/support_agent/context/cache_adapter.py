"""Provider-agnostic mapping of abstract prefix cache breakpoints."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from support_agent.context.sections import StabilityLayer
from support_agent.context.settings import CacheAdapterSettings, CacheProvider


class Breakpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    layer: StabilityLayer
    message_index: int = Field(ge=0)
    prefix_tokens: int = Field(ge=0)
    ttl_s: int = Field(gt=0)


def resolve_cache_provider(configured: CacheProvider, llm_provider: str | None) -> CacheProvider:
    if configured != "auto":
        return configured
    if llm_provider in {"anthropic", "openai", "deepseek"}:
        return llm_provider  # type: ignore[return-value]
    return "none"


def select_breakpoints(
    breakpoints: list[Breakpoint], settings: CacheAdapterSettings
) -> list[Breakpoint]:
    """Keep breakpoints at or above min_cacheable_tokens, capped at max_breakpoints."""
    if settings.max_breakpoints <= 0:
        return []
    eligible = [bp for bp in breakpoints if bp.prefix_tokens >= settings.min_cacheable_tokens]
    # Preserve layer order (longer TTLs come first); if more than max, keep earliest + latest.
    if len(eligible) <= settings.max_breakpoints:
        return eligible
    if settings.max_breakpoints == 1:
        return [eligible[-1]]
    return [*eligible[: settings.max_breakpoints - 1], eligible[-1]]


def _with_anthropic_cache_control(message: BaseMessage, ttl_s: int) -> BaseMessage:
    content = message.content
    text = content if isinstance(content, str) else str(content)
    cache_control: dict[str, object] = {"type": "ephemeral"}
    if ttl_s >= 3600:
        cache_control["ttl"] = "1h"
    block: list[str | dict[Any, Any]] = [
        {"type": "text", "text": text, "cache_control": cache_control}
    ]
    if isinstance(message, SystemMessage):
        return SystemMessage(content=block)
    if isinstance(message, HumanMessage):
        return HumanMessage(content=block)
    if isinstance(message, AIMessage):
        return AIMessage(content=block)
    return message


def apply_cache_breakpoints(
    messages: list[BaseMessage],
    breakpoints: list[Breakpoint],
    settings: CacheAdapterSettings,
    *,
    llm_provider: str | None = None,
) -> tuple[list[BaseMessage], list[Breakpoint]]:
    """Map abstract breakpoints to provider wire format; no-op when automatic or unsupported."""
    provider = resolve_cache_provider(settings.provider, llm_provider)
    active = select_breakpoints(breakpoints, settings)
    if provider != "anthropic" or not active:
        return list(messages), active

    by_index = {bp.message_index: bp for bp in active}
    adapted: list[BaseMessage] = []
    for idx, msg in enumerate(messages):
        bp = by_index.get(idx)
        adapted.append(_with_anthropic_cache_control(msg, bp.ttl_s) if bp is not None else msg)
    return adapted, active
