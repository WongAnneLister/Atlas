"""Typed graph and intent benchmark configuration."""

from typing import Literal

from pydantic import BaseModel, Field


class IntentSettings(BaseModel):
    min_confidence: float = Field(ge=0, le=1)
    rewrite_history_turns: int = Field(gt=0)


class GraphSettings(BaseModel):
    checkpoint_backend: Literal["memory", "sqlite", "postgres"]
    checkpoint_path: str


class PlanningSettings(BaseModel):
    enabled: bool
    max_parts: int = Field(ge=2)
    min_question_marks: int = Field(ge=2)
    long_query_words: int = Field(gt=0)


class KnowledgeSettings(BaseModel):
    partial_answers: bool
    # Drop lowest-ranked sources until the answer prompt fits its token budget, instead of
    # sending an over-budget prompt (see graph/nodes/answer_budget.py). Off only to measure it.
    fit_answer_budget: bool = True


class IntentEvalSettings(BaseModel):
    seed: int
    per_intent: int = Field(gt=0)
    extra_per_kind: int = Field(gt=0)
    bitext_holdout_fraction: float = Field(gt=0, lt=1)
    extra_drafts: str
    # Author-reviewed labels, applied by id after selection (13c).
    relabels: str = "eval/drafts/intent_relabels.yaml"
    cache_dir: str
    max_concurrency: int = Field(gt=0)
    target_accuracy: float = Field(ge=0, le=1)
