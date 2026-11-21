import pytest
from langchain_core.messages import HumanMessage

from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.retrieval.rerank import RerankingRetriever
from test_graph import fake
from test_graph_knowledge import CoverageFake, FixedRetriever, evidence, invoke, part
from test_refund_flow import DecisionFake
from test_tool_paths import ToolFake, call


def timed_out(*args, **kwargs):
    raise TimeoutError("private backend detail")


@pytest.mark.parametrize("dependency", ["milvus", "reranker"])
def test_knowledge_never_answers_after_search_or_rerank_failure(seeded, dependency) -> None:
    from support_agent.reliability.stores import GuardedReranker

    settings, service = seeded
    settings.gate.threshold = 0.7
    settings.reliability.retry.max_attempts = 1
    main = CoverageFake(responses=["unused"], payload={"parts": [part()]})
    with GraphDeps(
        settings, fast_model=fake(Intent.POLICY_QUESTION), main_model=main, order_service=service
    ) as deps:
        base = FixedRetriever(evidence(0.99))

        class FailedSearch:
            def retrieve(self, query, top_k):
                return deps.dependency_guards.call("milvus", timed_out)

        class FailedReranker:
            rerank = timed_out

        deps.retriever = (
            FailedSearch()
            if dependency == "milvus"
            else RerankingRetriever(
                base, GuardedReranker(FailedReranker, deps.dependency_guards), 1, 1
            )
        )
        result = invoke(build_graph(deps), "How can I return an item?")
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["handoff"].reason.value == "dependency_unavailable"
    assert result["retrieval_error_type"] == "TimeoutError"
    assert result["retrieval"] == []
    assert "answer" not in result["answered_by_model"]


@pytest.mark.parametrize("intent", [Intent.ORDER_STATUS, Intent.REFUND_REQUEST])
def test_orders_outage_hands_off_on_both_routes(seeded, monkeypatch, intent) -> None:
    settings, service = seeded
    settings.reliability.retry.max_attempts = 1
    model = (
        ToolFake(responses=[call(order_id="ORD-000001")])
        if intent is Intent.ORDER_STATUS
        else DecisionFake(responses=["unused"])
    )
    monkeypatch.setattr(service, "get_order", timed_out)
    with GraphDeps(
        settings, fast_model=fake(intent), main_model=model, order_service=service
    ) as deps:
        graph = build_graph(deps)
        result = graph.invoke(
            {
                "messages": [HumanMessage(content="I need help with ORD-000001")],
                "customer_id": "CUST-0001",
            },
            {"configurable": {"thread_id": "orders-outage"}},
        )
    assert result["handoff"].reason.value == "dependency_unavailable"
    if intent is Intent.ORDER_STATUS:
        route = [step for step in result["trace"] if not step.startswith("tool_")]
        assert route == ["input_guard", "rewrite", "classify", "tools", "output_guard"]
        assert len(model.seen) == 1
    else:
        assert result["trace"] == [
            "input_guard",
            "rewrite",
            "classify",
            "after_sales",
            "refund_identify",
            "handoff",
            "output_guard",
        ]
        assert model.decision_calls == 0
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM refund_requests").scalar() == 0


def test_guard_does_not_retry_an_unkeyed_write(seeded) -> None:
    settings, _ = seeded
    with GraphDeps(settings) as deps:
        attempts = 0

        def operation(_: float) -> None:
            nonlocal attempts
            attempts += 1
            timed_out()

        with pytest.raises(TimeoutError):
            deps.dependency_guards.call("orders_db", operation, idempotent=False)
        assert attempts == 1


def test_milvus_sdk_wrapped_outage_keeps_dependency_classification(seeded) -> None:
    import grpc
    from pymilvus.exceptions import ErrorCode, MilvusException

    from support_agent.reliability.guards import DependencyUnavailable

    class Unavailable(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.UNAVAILABLE

    settings, _ = seeded
    settings.reliability.retry.max_attempts = 1
    with GraphDeps(settings) as deps:

        def fail(seconds: float) -> None:
            raise MilvusException(code=grpc.StatusCode.UNAVAILABLE) from Unavailable()

        with pytest.raises(DependencyUnavailable):
            deps.dependency_guards.call("milvus", fail)

        def rate_limit(seconds: float) -> None:
            raise MilvusException(code=ErrorCode.RATE_LIMIT)

        with pytest.raises(DependencyUnavailable):
            deps.dependency_guards.call("milvus", rate_limit)


def test_guard_counts_one_failed_call_once_toward_the_circuit(seeded) -> None:
    from support_agent.reliability.circuit import CircuitState

    settings, _ = seeded
    settings.reliability.retry.base_delay_s = 0
    settings.reliability.retry.max_delay_s = 0
    settings.reliability.circuit.failure_threshold = settings.reliability.retry.max_attempts
    with GraphDeps(settings) as deps:
        with pytest.raises(TimeoutError):
            deps.dependency_guards.call("reranker", lambda _: timed_out())
        assert deps.circuits.state("reranker") is CircuitState.CLOSED
