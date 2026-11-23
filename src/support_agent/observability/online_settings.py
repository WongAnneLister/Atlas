"""Configuration for online feedback, sampled review, and drift monitoring."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DriftThresholdSettings(BaseModel):
    intent_psi: float = Field(default=0.20, gt=0.0)
    gate_ks: float = Field(default=0.15, gt=0.0, le=1.0)
    gate_psi: float = Field(default=0.20, gt=0.0)
    handoff_rate_delta: float = Field(default=0.10, gt=0.0, le=1.0)
    rewrite_skip_delta: float = Field(default=0.15, gt=0.0, le=1.0)
    tokens_per_turn_ratio: float = Field(default=0.25, gt=0.0)
    cost_per_conv_ratio: float = Field(default=0.25, gt=0.0)
    thumbs_down_delta: float = Field(default=0.10, gt=0.0, le=1.0)


class OnlineEvalSettings(BaseModel):
    enabled: bool = False
    sqlite_path: str = "data/processed/online_eval.sqlite"
    sample_size: int = Field(default=20, ge=1)
    near_threshold_band: float = Field(default=0.10, gt=0.0, le=1.0)
    near_threshold_weight: float = Field(default=0.50, ge=0.0, le=1.0)
    drift_thresholds: DriftThresholdSettings = Field(default_factory=DriftThresholdSettings)
