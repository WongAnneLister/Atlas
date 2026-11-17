"""Token usage per model and its price. Works without Langfuse."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel, Field

from support_agent.config import CostSettings

logger = logging.getLogger(__name__)
UNKNOWN_MODEL = "unknown"
_warned: set[str] = set()


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    calls: int = Field(default=0, ge=0)
    # Calls that reported no token counts; their cost cannot be computed.
    calls_without_usage: int = Field(default=0, ge=0)


def _token_counts(usage: Any) -> tuple[int, int] | None:
    if not isinstance(usage, Mapping):
        return None
    input_value = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_value = usage.get("output_tokens", usage.get("completion_tokens"))
    if isinstance(input_value, int) and isinstance(output_value, int):
        return input_value, output_value
    return None


def _model_name(response: Any, message: Any) -> str:
    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, Mapping) and isinstance(llm_output.get("model_name"), str):
        return str(llm_output["model_name"])
    metadata = getattr(message, "response_metadata", None)
    if isinstance(metadata, Mapping) and isinstance(metadata.get("model_name"), str):
        return str(metadata["model_name"])
    return UNKNOWN_MODEL


class UsageLedger(BaseCallbackHandler):
    """Count LLM calls and tokens per reported model name for one conversation."""

    def __init__(self) -> None:
        self.by_model: dict[str, ModelUsage] = {}
        self.first_token_at: float | None = None
        self.started = time.perf_counter()

    def on_llm_new_token(self, token: Any, **kwargs: Any) -> None:
        if token and self.first_token_at is None:
            self.first_token_at = time.perf_counter() - self.started

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        message = None
        counts = None
        for group in getattr(response, "generations", []):
            for generation in group:
                message = getattr(generation, "message", None)
                counts = _token_counts(getattr(message, "usage_metadata", None))
                if counts:
                    break
            if counts:
                break
        if counts is None:
            llm_output = getattr(response, "llm_output", None)
            if isinstance(llm_output, Mapping):
                counts = _token_counts(llm_output.get("token_usage"))
        usage = self.by_model.setdefault(_model_name(response, message), ModelUsage())
        usage.calls += 1
        if counts is None:
            usage.calls_without_usage += 1
            return
        usage.input_tokens += counts[0]
        usage.output_tokens += counts[1]

    @property
    def calls(self) -> int:
        return sum(usage.calls for usage in self.by_model.values())

    def tokens(self) -> tuple[int | None, int | None]:
        if not any(usage.calls > usage.calls_without_usage for usage in self.by_model.values()):
            return None, None
        return (
            sum(usage.input_tokens for usage in self.by_model.values()),
            sum(usage.output_tokens for usage in self.by_model.values()),
        )


def cost_usd(usage_by_model: Mapping[str, ModelUsage], settings: CostSettings) -> float | None:
    """Price every model's tokens. Any call without a known price or usage gives None."""
    total = 0.0
    for model, usage in usage_by_model.items():
        if usage.calls == 0:
            continue
        price = settings.prices.get(model)
        if price is None or price.input_per_million_usd is None:
            if model not in _warned:
                _warned.add(model)
                logger.warning("No price for model %r; cost is unknown", model)
            return None
        if usage.calls_without_usage:
            return None
        output_rate = price.output_per_million_usd
        if output_rate is None:
            return None
        total += usage.input_tokens / 1_000_000 * price.input_per_million_usd
        total += usage.output_tokens / 1_000_000 * output_rate
    return total
