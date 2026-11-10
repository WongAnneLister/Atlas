from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from support_agent.config import CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH, get_settings


def test_defaults_load() -> None:
    settings = get_settings()
    assert settings.retrieval.rrf_k == 60
    assert settings.retrieval.rerank_top_k == 5
    assert settings.agent.max_steps == 5
    configured = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert settings.gate.threshold == configured["gate"]["threshold"]
    assert settings.tracing.enabled is False


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPORT_AGENT__RETRIEVAL__RRF_K", "30")
    monkeypatch.setenv("SUPPORT_AGENT__TRACING__ENABLED", "true")
    settings = get_settings()
    assert settings.retrieval.rrf_k == 30
    assert settings.tracing.enabled is True
    assert settings.retrieval.dense_top_k == 50  # untouched keys keep YAML values


def test_gate_weights_sum_to_one() -> None:
    weights = get_settings().gate.weights.model_dump()
    assert sum(weights.values()) == pytest.approx(1.0)


def test_bad_gate_weights_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["gate"]["weights"]["top_score"] = 0.9
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv(CONFIG_PATH_ENV, str(bad))
    with pytest.raises(ValidationError, match=r"sum to 1\.0"):
        get_settings()


@pytest.mark.parametrize(
    ("key", "value"),
    [("dense_top_k", 0), ("bm25_top_k", -1), ("search_top_k", 0), ("rrf_k", -1)],
)
def test_invalid_retrieval_limits_rejected(
    key: str, value: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"SUPPORT_AGENT__RETRIEVAL__{key.upper()}", str(value))
    with pytest.raises(ValidationError, match=key):
        get_settings()


def test_retrieval_eval_requires_prd_cutoffs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPORT_AGENT__RETRIEVAL_EVAL__METRIC_KS", "[1,3]")
    with pytest.raises(ValidationError, match="metric_ks"):
        get_settings()
