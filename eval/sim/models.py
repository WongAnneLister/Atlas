"""Multi-turn scenario, transcript, and trajectory evaluation schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ScenarioCategory = Literal[
    "policy_qa",
    "order_status",
    "refund_eligible",
    "refund_ineligible",
    "refund_needs_human",
    "order_picker_interrupt",
    "topic_switch",
    "self_correction",
    "long_conversation",
    "frustrated_complaint",
    "mixed_knowledge_order",
    "multiturn_redteam",
]


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tone: Literal["polite", "neutral", "impatient", "frustrated", "adversarial"]
    verbosity: Literal["terse", "normal", "verbose"]
    patience: int = Field(ge=1, le=35)


class FactCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_hint: int = Field(ge=1)
    fact_key: str = Field(min_length=1)
    expected_substrings: list[str] = Field(min_length=1)


class SuccessChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_substrings: list[str] = Field(default_factory=list)
    forbidden_substrings: list[str] = Field(default_factory=list)
    expect_refund_created: bool = False
    expect_handoff_reason: str | None = None
    expect_interrupt: bool = False
    require_citations: bool = False


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    split: Literal["dev", "test"]
    category: ScenarioCategory
    customer_id: str = Field(min_length=1)
    persona: Persona
    goal: str = Field(min_length=1)
    facts: dict[str, Any] = Field(default_factory=dict)
    hidden_info: dict[str, str] = Field(default_factory=dict)
    script_hints: list[str] = Field(default_factory=list)
    checkpoints: list[FactCheckpoint] = Field(default_factory=list)
    expected_outcome: str = Field(min_length=1)
    expected_tool_calls: list[str] = Field(default_factory=list)
    max_turns: int = Field(ge=1, le=35)
    success_checks: SuccessChecks = Field(default_factory=SuccessChecks)
    nightly: bool = False
    reviewed: bool = False


class ToolCallRecord(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    customer_id_accessed: str | None = None


class SimTurn(BaseModel):
    turn_index: int = Field(ge=1)
    user_message: str
    agent_message: str = ""
    interrupt_prompt: str | None = None
    resume_choice: str | None = None
    route: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    handoff_reason: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    refund_request_id: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    compaction_events: int = Field(default=0, ge=0)
    summariser_calls: int = Field(default=0, ge=0)
    context_calls: list[dict[str, Any]] = Field(default_factory=list)
    latency_s: float = Field(default=0.0, ge=0.0)
    error_type: str | None = None


class ConversationTranscript(BaseModel):
    scenario_id: str
    category: ScenarioCategory
    customer_id: str
    repeat_index: int = Field(default=0, ge=0)
    turns: list[SimTurn] = Field(default_factory=list)
    stop_reason: Literal["done", "max_turns", "handoff", "error"] = "done"
    simulator_model: str = "unset"
    agent_models: dict[str, str] = Field(default_factory=dict)


class ScenarioEvaluation(BaseModel):
    scenario_id: str
    category: ScenarioCategory
    repeat_index: int = Field(default=0, ge=0)
    task_success: bool
    tool_call_precision: float | None = None
    tool_call_recall: float | None = None
    wrong_customer_access: bool = False
    turns_to_success: int | None = None
    redundant_questions: int = Field(default=0, ge=0)
    fact_retention: float | None = None
    loop_detected: bool = False
    handoff_appropriate: bool = True
    tokens_by_turn: list[int] = Field(default_factory=list)
    total_input_tokens: int = Field(default=0, ge=0)
    total_output_tokens: int = Field(default=0, ge=0)
    had_error: bool = False
