"""Exercise synthetic faults through the same entry points as live calls."""

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps


def test_fault_draws_are_repeatable_for_the_same_seed() -> None:
    from support_agent.reliability.chaos import ChaosInjector

    settings = Settings().chaos.model_copy(
        update={"enabled": True, "llm_timeout_rate": 0.2, "rerank_down_rate": 0.5}
    )

    def outcomes(injector: ChaosInjector) -> list[str | None]:
        results = []
        for _ in range(30):
            for operation in (
                lambda: injector.llm("classify"),
                lambda: injector.dependency("reranker"),
            ):
                try:
                    results.append(operation())
                except TimeoutError as error:
                    results.append(type(error).__name__)
        return results

    first = outcomes(ChaosInjector(settings))
    assert first == outcomes(ChaosInjector(settings))
    assert set(first) == {None, "InjectedTimeout"}
    assert set(outcomes(ChaosInjector(settings.model_copy(update={"enabled": False})))) == {None}


@pytest.mark.parametrize(
    ("fault", "diagnostic"),
    [
        ("timeout", "InjectedTimeout"),
        ("rate_limit", "InjectedRateLimit"),
        ("garbage", "ValidationError"),
    ],
)
def test_classifier_faults_use_the_fixed_route(fault: str, diagnostic: str) -> None:
    class ForbiddenModel(FakeListChatModel):
        def with_structured_output(self, *args, **kwargs):
            pytest.fail("Injected classifier fault should intercept the SDK call")

    settings = Settings()
    settings.chaos.enabled = True
    setattr(settings.chaos, f"llm_{fault}_rate", 1.0)
    settings.reliability.retry.max_attempts = 1
    with GraphDeps(settings, fast_model=ForbiddenModel(responses=["unused"])) as deps:
        result = build_graph(deps).invoke(
            {"messages": [HumanMessage(content="How do I return this item?")]},
            {"configurable": {"thread_id": "chaos-fake"}},
        )
    assert result["trace"] == ["rewrite", "classify", "fixed"]
    assert result["classification_error_type"] == diagnostic
    assert "human support agent" in result["answer"]
