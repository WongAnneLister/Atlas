from __future__ import annotations

import pytest
from langchain_core.language_models import FakeListChatModel

from support_agent import llm
from support_agent.llm import LLMConfigError, get_chat_model, override_chat_model


@pytest.fixture(autouse=True)
def _no_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_PROVIDER", "LLM_FAST_MODEL", "LLM_MAIN_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_override_returns_fake() -> None:
    fake = FakeListChatModel(responses=["hi"])
    with override_chat_model("fast", fake):
        assert get_chat_model("fast") is fake
        assert get_chat_model("fast").invoke("hello").content == "hi"
    assert "fast" not in llm._overrides


def test_missing_env_raises_clear_error() -> None:
    with pytest.raises(LLMConfigError, match="LLM_MAIN_MODEL"):
        get_chat_model("main")


def test_model_without_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_FAST_MODEL", "some-model")
    with pytest.raises(LLMConfigError, match="LLM_PROVIDER"):
        get_chat_model("fast")


def test_factory_passes_configured_provider_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from support_agent.config import get_settings

    settings = get_settings().model_copy(deep=True)
    settings.llm.provider = "deepseek"
    settings.llm.fast_model = "configured-model"
    settings.llm.model_kwargs = {"extra_body": {"thinking": {"type": "disabled"}}}
    calls = []
    fake = FakeListChatModel(responses=["unused"])

    def capture(model, **kwargs):
        calls.append((model, kwargs))
        return fake

    monkeypatch.setattr(llm, "init_chat_model", capture)
    assert get_chat_model("fast", settings) is fake
    assert calls[0][0] == "configured-model"
    assert calls[0][1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls[0][1]["max_retries"] == 0
