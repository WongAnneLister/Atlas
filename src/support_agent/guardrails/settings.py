"""Typed configuration for deterministic guardrails and the optional classifier."""

from typing import Literal

from pydantic import BaseModel, Field


class InputClassifierSettings(BaseModel):
    enabled: bool
    model_role: Literal["fast", "main"]


class InputGuardSettings(BaseModel):
    patterns_file: str
    classifier: InputClassifierSettings


class OutputGuardSettings(BaseModel):
    prompt_leak: bool
    foreign_pii: bool
    commitments: bool
    prompt_word_window: int = Field(gt=0)


class GuardrailSettings(BaseModel):
    input: InputGuardSettings
    output: OutputGuardSettings
