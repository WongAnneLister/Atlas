"""Structured intent classification shared by the graph and intent evaluation."""

from __future__ import annotations

import logging
from pathlib import Path as FilePath
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from support_agent.config import Settings
from support_agent.graph.intents import INTENT_TO_PATH, Intent, Path
from support_agent.graph.state import ConversationState
from support_agent.reliability.llm_calls import ReliableModels
from support_agent.reliability.structured import StructuredOutputError, parse_response

logger = logging.getLogger(__name__)
PROMPT_PATH = FilePath(__file__).resolve().parents[1] / "prompts" / "classify.md"


class IntentPrediction(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class ClassificationOutcome(IntentPrediction):
    parse_failed: bool = False
    model_name: str | None = None
    error_type: str | None = None


class Classifier:
    def __init__(
        self,
        model: BaseChatModel | None,
        settings: Settings,
        *,
        models: ReliableModels | None = None,
    ) -> None:
        self.model = model
        self.models = models
        self.settings = settings
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def classify(self, query: str) -> ClassificationOutcome:
        model_name: str | None = None
        try:
            messages = [SystemMessage(content=self.prompt), HumanMessage(content=query)]
            if self.models is not None:
                parsed, _ = self.models.structured("classify", "fast", IntentPrediction, messages)
            else:
                if self.model is None:
                    raise RuntimeError("A classifier model is required")
                response = self.model.with_structured_output(
                    IntentPrediction, include_raw=True
                ).invoke(messages)
                parsed = parse_response(IntentPrediction, response)
            return ClassificationOutcome(**parsed.value.model_dump(), model_name=parsed.model_name)
        except Exception as error:
            if isinstance(error, StructuredOutputError):
                error_type, model_name = error.error_type, error.model_name
            else:
                error_type = type(error).__name__
            logger.warning("Intent classification failed: %s", error_type)
            return ClassificationOutcome(
                intent=Intent.CHITCHAT_OTHER,
                confidence=0,
                parse_failed=True,
                model_name=model_name,
                error_type=error_type,
            )

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        outcome = self.classify(state.rewritten_query)
        path = INTENT_TO_PATH[outcome.intent]
        return {
            "intent": outcome.intent,
            "intent_confidence": outcome.confidence,
            "path": path,
            "intent_low_confidence": path in {Path.KNOWLEDGE, Path.AFTER_SALES}
            and outcome.confidence < self.settings.intent.min_confidence,
            "classification_failed": outcome.parse_failed,
            "classification_error_type": outcome.error_type,
            "classifier_model": outcome.model_name,
            "trace": [*state.trace, "classify"],
        }
