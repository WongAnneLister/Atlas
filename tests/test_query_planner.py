"""Offline planning and per-part classification decisions."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from support_agent.config import Settings
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent, Path
from support_agent.graph.nodes.classify import Classifier
from support_agent.graph.nodes.plan import Planner, may_have_multiple_parts
from support_agent.graph.state import ConversationState

QUESTION = "When can I return a laptop? Also, who pays shipping?"
RETURN = "When can I return a laptop?"
SHIPPING = "Who pays shipping?"
PLANNED = [
    {"text": RETURN, "key_terms": ["return", "laptop"]},
    {"text": SHIPPING, "key_terms": ["shipping"]},
]


class PlanningModel(FakeListChatModel):
    outputs: list[Any]
    calls: list[tuple[str, str]] = Field(default_factory=list)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        def invoke(messages: list[BaseMessage]) -> dict[str, Any]:
            query = messages[-1].content
            assert isinstance(query, str)
            self.calls.append((schema.__name__, query))
            parsed = self.outputs.pop(0)
            if isinstance(parsed, Exception):
                raise parsed
            return {"parsed": parsed, "raw": AIMessage(content=""), "parsing_error": None}

        return RunnableLambda(invoke)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Can I return my item?", False),
        ("Which headphones have a microphone and noise cancellation?", False),
        ("Can I return sweaters or jackets?", False),
        ("Can I return this? Who pays shipping?", True),
        ("Can I return this. Also, who pays shipping", True),
        ("Can I return this and who pays shipping?", True),
        ("What is covered, and will you pay my shipping?", True),
        ("Also, who pays return shipping?", True),
        ("word " * 60 + "?", True),
    ],
)
def test_planner_heuristic(query: str, expected: bool) -> None:
    assert may_have_multiple_parts(query, Settings().planning) is expected


@pytest.mark.parametrize(
    ("enabled", "query"),
    [(False, QUESTION), (True, "Can I return my item?")],
)
def test_planner_skips_model(enabled: bool, query: str) -> None:
    settings = Settings()
    settings.planning.enabled = enabled
    model = PlanningModel(responses=["unused"], outputs=[])
    with GraphDeps(settings, fast_model=model) as deps:
        update = Planner(deps)(ConversationState(rewritten_query=query, trace=["rewrite"]))
    assert update.get("parts", []) == []
    assert update.get("trace", ["rewrite"]) == ["rewrite"]
    assert model.calls == []


def run_planner(output: Any, *, original: str = QUESTION) -> tuple[dict[str, Any], PlanningModel]:
    model = PlanningModel(responses=["unused"], outputs=[output])
    with GraphDeps(Settings(), fast_model=model) as deps:
        update = Planner(deps)(
            ConversationState(
                messages=[HumanMessage(content=original)],
                rewritten_query=QUESTION,
                trace=["rewrite"],
            )
        )
    return update, model


def test_planner_drops_parts_with_invented_terms() -> None:
    output = {
        "is_multi_part": True,
        "parts": [*PLANNED, {"text": "Is there a penalty?", "key_terms": ["penalty"]}],
    }

    update, model = run_planner(output)

    assert [part.text for part in update["parts"]] == [RETURN, SHIPPING]
    assert update["trace"] == ["rewrite", "plan"]
    assert model.calls == [("PlanPrediction", QUESTION)]


def test_planner_accepts_terms_from_original_and_rewritten_queries() -> None:
    output = {
        "is_multi_part": True,
        "parts": [
            {"text": RETURN, "key_terms": ["RETURN", "laptop", "device"]},
            PLANNED[1],
        ],
    }
    update, _ = run_planner(output, original="Can I return the device? Also, who pays shipping?")
    assert [part.text for part in update["parts"]] == [RETURN, SHIPPING]


@pytest.mark.parametrize(
    "output",
    [
        {"is_multi_part": False, "parts": PLANNED},
        {"is_multi_part": True, "parts": [PLANNED[0], PLANNED[0]]},
        {"is_multi_part": True, "parts": [PLANNED[0], {**PLANNED[1], "key_terms": ["ship"]}]},
        {"is_multi_part": True, "parts": PLANNED * 2},
        {"is_multi_part": True, "parts": [{**part, "key_terms": ["invented"]} for part in PLANNED]},
        {"is_multi_part": True, "parts": [{"text": RETURN}]},
        TimeoutError("model unavailable"),
    ],
)
def test_planner_falls_back_to_whole(output: Any) -> None:
    update, model = run_planner(output)
    assert update.get("parts", []) == []
    assert model.calls == [("PlanPrediction", QUESTION)]


def predict(intent: Intent) -> dict[str, Any]:
    return {"intent": intent, "confidence": 0.9}


@pytest.mark.parametrize(
    ("outputs", "part_intents", "route_source", "path"),
    [
        (
            [predict(Intent.POLICY_QUESTION), predict(Intent.PRODUCT_QUESTION)],
            [Intent.POLICY_QUESTION, Intent.PRODUCT_QUESTION],
            "parts",
            Path.KNOWLEDGE,
        ),
        (
            [predict(Intent.POLICY_QUESTION), predict(Intent.CHITCHAT_OTHER)],
            [Intent.POLICY_QUESTION, Intent.CHITCHAT_OTHER],
            "parts",
            Path.KNOWLEDGE,
        ),
        (
            [
                predict(Intent.POLICY_QUESTION),
                predict(Intent.ORDER_STATUS),
                predict(Intent.ORDER_STATUS),
            ],
            [Intent.POLICY_QUESTION, Intent.ORDER_STATUS],
            "whole",
            Path.TOOLS,
        ),
        (
            [
                predict(Intent.POLICY_QUESTION),
                RuntimeError("invalid"),
                predict(Intent.POLICY_QUESTION),
            ],
            [Intent.POLICY_QUESTION, Intent.CHITCHAT_OTHER],
            "whole",
            Path.KNOWLEDGE,
        ),
        (
            [predict(Intent.CHITCHAT_OTHER)] * 3,
            [Intent.CHITCHAT_OTHER, Intent.CHITCHAT_OTHER],
            "whole",
            Path.FIXED,
        ),
    ],
)
def test_classifier_routes_by_part_intents(
    outputs: list[Any],
    part_intents: list[Intent],
    route_source: str,
    path: Path,
) -> None:
    model = PlanningModel(responses=["unused"], outputs=outputs)
    state = ConversationState.model_validate(
        {"rewritten_query": QUESTION, "parts": PLANNED, "trace": ["rewrite", "plan"]}
    )

    outcome = Classifier(model, Settings())(state)

    assert outcome.get("route_source") == route_source
    assert outcome["path"] == path
    assert [part.intent for part in outcome["parts"]] == part_intents
    if route_source == "parts" and part_intents[-1] is Intent.CHITCHAT_OTHER:
        assert outcome["parts"][-1].failure_reason == "unsupported_part"
    expected_calls = [RETURN, SHIPPING] if route_source == "parts" else [RETURN, SHIPPING, QUESTION]
    assert model.calls == [("IntentPrediction", query) for query in expected_calls]
    assert outcome["trace"] == ["rewrite", "plan", "classify"]


@pytest.mark.parametrize(
    ("first", "key_first", "second", "key_second"),
    [
        (
            "Can I buy discontinued items?",
            "discontinued",
            "Can I ask for a refund after a price drop?",
            "price drop",
        ),
        (
            "Do I send back the free gift when returning an item?",
            "free gift",
            "Which warranty applies when the card and website disagree?",
            "warranty",
        ),
        (
            "How long do replacements take?",
            "replacements",
            "How do I contact your courier partners?",
            "courier partners",
        ),
        (
            "How do I change my account password?",
            "password",
            "How are monthly installments charged?",
            "monthly installments",
        ),
        (
            "Can I use a gift card across sellers?",
            "gift card",
            "What should I do after the return period ends?",
            "return period",
        ),
        (
            "What does the Imported label mean?",
            "Imported",
            "What steps can I take if my parcel shows delivered but is missing?",
            "parcel",
        ),
    ],
)
def test_cross_doc_policy_question_shapes_use_part_routing(
    first: str, key_first: str, second: str, key_second: str
) -> None:
    query = f"{first} Also, {second}"
    response = {
        "is_multi_part": True,
        "parts": [
            {"text": first, "key_terms": [key_first]},
            {"text": second, "key_terms": [key_second]},
        ],
    }
    settings = Settings()
    model = PlanningModel(
        responses=["unused"],
        outputs=[response, predict(Intent.POLICY_QUESTION), predict(Intent.POLICY_QUESTION)],
    )
    initial = ConversationState(
        messages=[HumanMessage(content=query)], rewritten_query=query, trace=["rewrite"]
    )
    with GraphDeps(settings, fast_model=model) as deps:
        planned = Planner(deps)(initial)
        outcome = Classifier(None, settings, models=deps.models)(initial.model_copy(update=planned))

    assert outcome["route_source"] == "parts"
    assert outcome["path"] == Path.KNOWLEDGE
    assert outcome["trace"] == ["rewrite", "plan", "classify"]
    assert model.calls == [
        ("PlanPrediction", query),
        ("IntentPrediction", first),
        ("IntentPrediction", second),
    ]
