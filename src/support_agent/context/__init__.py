"""Cache-aware, budgeted context assembly for every LLM call."""

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
    ContextSection,
    StabilityLayer,
    canonical_json,
    compress_tool_result,
    render_shared_l0,
)
from support_agent.context.settings import CacheAdapterSettings, ContextSettings, NodeBudgetProfile

__all__ = [
    "LAYER_ORDER",
    "ApproxTokenCounter",
    "Breakpoint",
    "CacheAdapterSettings",
    "ContextBreakdown",
    "ContextOverflow",
    "ContextSection",
    "ContextSettings",
    "DroppedItem",
    "NodeBudgetProfile",
    "StabilityLayer",
    "TokenCounter",
    "apply_cache_breakpoints",
    "canonical_json",
    "compress_tool_result",
    "render_shared_l0",
]
