"""Check that an order-tool answer states only facts found in this turn's tool results.

The order model may mix order facts with general claims (store rules, policies) it was
never given. Code splits the answer into numbered sentences, so the checker cannot skip
one. Every factual sentence needs quotes, one per data field it uses, and code must
find each quote in the tool data. See eval/reports/order_grounding.md.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from support_agent.reliability.llm_calls import ReliableModels
from support_agent.reliability.structured import StructuredOutputError

logger = logging.getLogger(__name__)

_NOT_DATA = re.compile(r"[^\w./-]+", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LIST_MARK = re.compile(r"^(?:[-*•]+|\d+[.)])\s+")
_ELLIPSIS = re.compile(r"\.\.\.|…")


class SentenceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=1)
    kind: Literal["fact", "other"]
    quotes: list[str]


class OrderGrounding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentences: list[SentenceCheck]


class GroundingResult(BaseModel):
    status: Literal["grounded", "ungrounded", "error"]
    missing: list[str] = Field(default_factory=list)
    attempts: int = Field(ge=1)


def _flat(text: str) -> str:
    """Keep words, numbers, dates and ids; JSON quotes, braces and colons do not matter."""
    return " ".join(_NOT_DATA.sub(" ", text).casefold().split())


def tool_data_text(order_context: dict[str, Any] | None) -> str:
    return json.dumps(order_context or {}, sort_keys=True, ensure_ascii=False, default=str)


def answer_sentences(answer: str) -> list[str]:
    """Lines, then sentences; list markers removed. Over-splitting only adds checks."""
    sentences = []
    for line in answer.splitlines():
        text = _LIST_MARK.sub("", line.strip()).strip()
        sentences += [part.strip() for part in _SENTENCE_END.split(text) if part.strip()]
    return sentences


def numbered(sentences: list[str]) -> str:
    return "\n".join(f"{index}. {text}" for index, text in enumerate(sentences, 1))


def ungrounded_sentences(
    decision: OrderGrounding, sentences: list[str], data_text: str
) -> list[str]:
    """Sentences the checker skipped, or facts with a missing or unmatched quote."""
    data = f" {_flat(data_text)} "
    by_index = {item.index: item for item in decision.sentences}
    missing = []
    for index, text in enumerate(sentences, 1):
        item = by_index.get(index)
        if item is None:
            missing.append(text)
            continue
        if item.kind == "other":
            continue
        pieces = [p for quote in item.quotes for p in _ELLIPSIS.split(quote) if _flat(p)]
        if not pieces or any(f" {_flat(piece)} " not in data for piece in pieces):
            missing.append(text)
    return missing


def _decision(response: Any) -> OrderGrounding | None:
    """None when the model gave no valid structured call (plain text or bad arguments)."""
    if not isinstance(response, dict) or response.get("parsing_error"):
        return None
    parsed = response.get("parsed")
    if parsed is None:
        return None
    try:
        return OrderGrounding.model_validate(parsed)
    except ValueError:
        return None


def _messages(data: str, sentences: list[str], prompt: str) -> list[BaseMessage]:
    return [
        SystemMessage(content=prompt),
        HumanMessage(content=f"Order data:\n{data}\n\nAnswer sentences:\n{numbered(sentences)}"),
    ]


def _check(
    decision: OrderGrounding, sentences: list[str], data: str, attempts: int
) -> GroundingResult:
    missing = ungrounded_sentences(decision, sentences, data)
    status: Literal["grounded", "ungrounded"] = "ungrounded" if missing else "grounded"
    return GroundingResult(status=status, missing=missing, attempts=attempts)


def check_order_answer_reliably(
    models: ReliableModels,
    prompt: str,
    order_context: dict[str, Any] | None,
    answer: str,
) -> GroundingResult:
    """Run the graph's structured grounding check with its single repair."""
    data = tool_data_text(order_context)
    sentences = answer_sentences(answer)
    if not sentences:
        return GroundingResult(status="grounded", attempts=1)
    try:
        response, event = models.structured(
            "grounding", "main", OrderGrounding, _messages(data, sentences, prompt)
        )
    except StructuredOutputError as error:
        logger.warning("Order grounding reply was invalid: %s", error.error_type)
        return GroundingResult(status="error", attempts=1 + int(error.repaired))
    except Exception as error:
        logger.warning("Order grounding check failed: %s", type(error).__name__)
        return GroundingResult(status="error", attempts=1)
    return _check(response.value, sentences, data, 1 + int(event.repaired))


def check_order_answer(
    model: BaseChatModel,
    prompt: str,
    order_context: dict[str, Any] | None,
    answer: str,
    attempts: int,
) -> GroundingResult:
    """Ask for per-sentence quotes; retry only a reply without a valid structured call.

    A raised error (network, provider) is not retried here and fails closed.
    """
    data = tool_data_text(order_context)
    sentences = answer_sentences(answer)
    if not sentences:
        return GroundingResult(status="grounded", attempts=1)
    structured = model.with_structured_output(OrderGrounding, include_raw=True)
    messages = _messages(data, sentences, prompt)
    for attempt in range(1, attempts + 1):
        try:
            response = structured.invoke(messages)
        except Exception as error:
            logger.warning("Order grounding check failed: %s", type(error).__name__)
            return GroundingResult(status="error", attempts=attempt)
        decision = _decision(response)
        if decision is None:
            logger.warning("Order grounding reply had no valid structured call")
            continue
        return _check(decision, sentences, data, attempt)
    return GroundingResult(status="error", attempts=attempts)
