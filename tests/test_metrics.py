"""Metrics use fixed labels and attach request IDs only as exemplars."""

import re

import pytest

from support_agent.config import Settings
from support_agent.graph.handoff import HandoffReason
from test_api import QUESTION, client, events


def test_atlas_metric_labels_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from support_agent.observability.metrics import AtlasMetrics
    from support_agent.reliability.circuit import CircuitRegistry

    settings = Settings()
    settings.llm.main_model = "configured-model"
    monkeypatch.delenv("LLM_MAIN_MODEL", raising=False)
    metrics = AtlasMetrics(settings)
    private = "customer-order-and-conversation-id"
    metrics.request("/api/chat", "success", 0.5, "0123456789abcdef")
    metrics.request("/unknown/" + private, private, 0.5, "0123456789abcdef")
    metrics.llm_attempt("main", "configured-model", "success", 0.5)
    metrics.llm_attempt("main", private, "error", 0.5)
    metrics.retry("reranker")
    metrics.retry(private)
    metrics.fallback("main")
    metrics.repair("answer", "error")
    metrics.repair(private, "success")
    metrics.handoff(HandoffReason.DEPENDENCY_UNAVAILABLE)
    metrics.graph_update({"path": "B. knowledge"})
    metrics.graph_update({"path": private})
    circuits = CircuitRegistry(settings.reliability.circuit)
    metrics.render(circuits, "")

    allowed = {
        "endpoint": {"chat", "other"},
        "outcome": {"success", "error"},
        "role": {"main"},
        "model": {"configured-model", "unconfigured"},
        "dependency": {"milvus", "reranker", "orders_db"}
        | {f"llm:{model}" for model in metrics.models},
        "call_site": {"answer"},
        "reason": {"dependency_unavailable"},
        "passed": {"true", "false"},
        "path": metrics.paths,
    }
    samples = [sample for metric in metrics.registry.collect() for sample in metric.samples]
    for sample in samples:
        for name, value in sample.labels.items():
            if name == "le":
                continue  # Prometheus histogram bucket boundary
            assert value in allowed[name]
    assert (
        metrics.registry.get_sample_value(
            "atlas_requests_total", {"endpoint": "chat", "outcome": "success"}
        )
        == 1
    )
    assert all(private not in str(sample.labels) for sample in samples)


async def test_api_exposes_trace_correlated_graph_metrics(seeded) -> None:
    from prometheus_client import CollectorRegistry

    registry = CollectorRegistry()
    async with client(seeded, score=0.01, registry=registry) as api:
        reply = await api.post("/api/chat", json=QUESTION)
        trace_id = reply.headers["x-trace-id"]
        assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
        event = next(data for name, data in events(reply) if name == "handoff")
        assert event["trace_id"] == trace_id
        response = await api.get("/metrics")
        assert response.status_code == 200
        assert 'atlas_handoffs_total{reason="low_evidence"} 1.0' in response.text
        assert 'atlas_gate_evaluations_total{passed="false"} 1.0' in response.text
        assert "atlas_path_total{" in response.text
        assert f'"{trace_id}"' not in response.text
        openmetrics = await api.get("/metrics", headers={"Accept": "application/openmetrics-text"})
        assert f'# {{trace_id="{trace_id}"}}' in openmetrics.text


async def test_sse_system_error_counts_as_failed_request(seeded, monkeypatch) -> None:
    from prometheus_client import CollectorRegistry

    from support_agent.graph.nodes.knowledge import KnowledgePath

    def fail(*args):
        raise RuntimeError("private runtime error")

    monkeypatch.setattr(KnowledgePath, "answer", fail)
    registry = CollectorRegistry()
    async with client(seeded, registry=registry) as api:
        reply = await api.post("/api/chat", json=QUESTION)
        assert reply.status_code == 200
        assert any(name == "error" for name, _ in events(reply))
    assert (
        registry.get_sample_value("atlas_requests_total", {"endpoint": "chat", "outcome": "error"})
        == 1
    )
    assert (
        registry.get_sample_value(
            "atlas_requests_total", {"endpoint": "chat", "outcome": "success"}
        )
        is None
    )
