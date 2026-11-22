"""Find independently answerable requests before intent routing."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from unicodedata import normalize

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, StringConstraints

from support_agent.graph.parts import QueryPart
from support_agent.graph.settings import PlanningSettings
from support_agent.graph.state import ConversationState
from support_agent.reliability.structured import StructuredOutputError

if TYPE_CHECKING:
    from support_agent.graph.deps import GraphDeps

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "plan.md"
SENTENCE_CONNECTOR = re.compile(r"(?:^|[.!?])\s*(?:also|and)\b", re.IGNORECASE)
CLAUSE_CONNECTOR = re.compile(
    r"\b(?:and|or|but|yet)\s+"
    r"(?:how|what|when|where|who|why|which|do|does|did|can|could|would|should|"
    r"will|is|are|was|were|has|have|may|might|must|i|we|you|they|he|she|it)\b",
    re.IGNORECASE,
)
NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PlannedPart(BaseModel):
    text: NonemptyText
    key_terms: list[NonemptyText] = Field(min_length=1)


class PlanPrediction(BaseModel):
    is_multi_part: bool
    parts: list[PlannedPart]


def may_have_multiple_parts(query: str, settings: PlanningSettings) -> bool:
    return (
        query.count("?") >= settings.min_question_marks
        or len(query.split()) > settings.long_query_words
        or SENTENCE_CONNECTOR.search(query) is not None
        or CLAUSE_CONNECTOR.search(query) is not None
    )


def _normalized(text: str) -> str:
    return " ".join(normalize("NFKC", text).casefold().split())


def _grounded_parts(parts: list[PlannedPart], queries: tuple[str, str]) -> list[QueryPart]:
    normalized_queries = tuple(_normalized(query) for query in queries)
    grounded: dict[str, QueryPart] = {}
    for index, part in enumerate(parts):
        if any(
            not any(
                re.search(rf"(?<!\w){re.escape(_normalized(term))}(?!\w)", query)
                for query in normalized_queries
            )
            for term in part.key_terms
        ):
            logger.info("Dropped planned part %d with ungrounded key terms", index)
            continue
        text_key = _normalized(part.text).rstrip(" ?!.")
        grounded.setdefault(text_key, QueryPart(text=part.text, key_terms=part.key_terms))
    return list(grounded.values())


class Planner:
    def __init__(self, deps: GraphDeps) -> None:
        self.settings = deps.settings.planning
        self.models = deps.models
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8").format(
            max_parts=self.settings.max_parts
        )

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        query = state.rewritten_query
        if not self.settings.enabled or not may_have_multiple_parts(query, self.settings):
            return {"parts": []}

        update: dict[str, Any] = {"parts": [], "trace": [*state.trace, "plan"]}
        messages = [SystemMessage(content=self.prompt), HumanMessage(content=query)]
        try:
            parsed, _ = self.models.structured(
                "plan", "fast", PlanPrediction, messages, recover=False
            )
        except Exception as error:
            error_type = (
                error.error_type
                if isinstance(error, StructuredOutputError)
                else type(error).__name__
            )
            logger.warning("Query planning failed: %s", error_type)
            return update

        plan = parsed.value
        if not plan.is_multi_part:
            return update
        if len(plan.parts) > self.settings.max_parts:
            logger.warning("Query plan exceeded the configured part limit")
            return update

        content = state.messages[-1].content if state.messages else None
        original = content if isinstance(content, str) else ""
        parts = _grounded_parts(plan.parts, (original, query))
        if len(parts) > 1:
            update["parts"] = parts
        return update
