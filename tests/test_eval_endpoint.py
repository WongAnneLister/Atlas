import pytest
from eval import e2e_eval

from support_agent.config import get_settings


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://name:secret@Relay.Example:6443/private?token=secret#private", "relay.example"),
        ("http://[::1]:8443/path", "::1"),
        ("http://[::1]invalid/path", None),
        ("https://bad\nhost.example/", None),
        ("https://bad%25host.example/path", None),
        ("https://relay.example:bad/path", None),
        ("file://relay.example/", None),
        ("https://bad host.example/", None),
        ("not a URL", None),
    ],
)
def test_e2e_provenance_stores_only_http_hostname(monkeypatch, base_url, expected):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_BASE", base_url)
    settings = get_settings().model_copy(deep=True)

    metadata = e2e_eval._metadata(settings, "test", "fixture", "corpus")

    assert metadata.endpoint_host == expected
    assert "secret" not in metadata.model_dump_json()
    assert metadata.endpoint_host is None or "/" not in metadata.endpoint_host


def test_e2e_provenance_resolves_explicit_model_endpoint_first(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_BASE", "https://unused.example/v1")
    settings = get_settings().model_copy(deep=True)
    settings.llm.model_kwargs = {"api_base": "http://configured.example/v1"}

    metadata = e2e_eval._metadata(settings, "test", "fixture", "corpus")

    assert metadata.endpoint_host == "configured.example"


@pytest.mark.parametrize(
    ("provider", "host"), [("deepseek", "api.deepseek.com"), ("openai", "api.openai.com")]
)
def test_e2e_provenance_resolves_default_provider_endpoint(monkeypatch, provider, host):
    for name in ("DEEPSEEK_API_BASE", "OPENAI_API_BASE", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", provider)
    settings = get_settings().model_copy(deep=True)
    settings.llm.model_kwargs = {}

    assert e2e_eval._metadata(settings, "test", "fixture", "corpus").endpoint_host == host
