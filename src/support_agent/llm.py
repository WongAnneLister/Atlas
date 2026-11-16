"""The only place chat models are created (AGENTS.md §2).

Model names come from env (`LLM_FAST_MODEL`, `LLM_MAIN_MODEL`, `LLM_PROVIDER`) or config.
Tests inject fakes with `override_chat_model` so no real LLM is ever called offline.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, cast

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from support_agent.config import LLMSettings, Settings, get_settings

Role = Literal["fast", "main"]

ENV_PROVIDER = "LLM_PROVIDER"
ENV_MODEL: dict[Role, str] = {"fast": "LLM_FAST_MODEL", "main": "LLM_MAIN_MODEL"}

_overrides: dict[Role, BaseChatModel] = {}


class LLMConfigError(RuntimeError):
    """Raised when no model name or provider is configured for a role."""


def resolve_model(role: Role, cfg: LLMSettings) -> tuple[str | None, str | None]:
    configured_name = cfg.fast_model if role == "fast" else cfg.main_model
    model = os.environ.get(ENV_MODEL[role]) or configured_name
    provider = os.environ.get(ENV_PROVIDER) or cfg.provider
    return model, provider


def get_chat_model(role: Role, settings: Settings | None = None) -> BaseChatModel:
    """Return the chat model for `role`, or the injected fake if one is set."""
    if role in _overrides:
        return _overrides[role]
    cfg = (settings or get_settings()).llm
    model, provider = resolve_model(role, cfg)
    if not model or not provider:
        raise LLMConfigError(
            f"No model configured for role '{role}'. "
            f"Set {ENV_PROVIDER} and {ENV_MODEL[role]} (see .env.example)."
        )
    return cast(
        BaseChatModel,
        init_chat_model(
            model,
            model_provider=provider,
            temperature=cfg.temperature,
            timeout=cfg.timeout_s,
            **cfg.model_kwargs,
        ),
    )


def set_chat_model_override(role: Role, model: BaseChatModel | None) -> None:
    """Test hook: make `get_chat_model(role)` return `model` (None clears it)."""
    if model is None:
        _overrides.pop(role, None)
    else:
        _overrides[role] = model


@contextmanager
def override_chat_model(role: Role, model: BaseChatModel) -> Iterator[BaseChatModel]:
    """Test hook as a context manager; restores the previous state on exit."""
    previous = _overrides.get(role)
    set_chat_model_override(role, model)
    try:
        yield model
    finally:
        set_chat_model_override(role, previous)
