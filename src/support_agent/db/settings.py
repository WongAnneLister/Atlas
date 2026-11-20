"""Relational storage settings."""

from typing import Literal

from pydantic import BaseModel, Field


class DatabaseSettings(BaseModel):
    backend: Literal["sqlite", "postgres"]
    pool_size: int = Field(gt=0)
    max_overflow: int = Field(ge=0)
    pool_timeout_s: float = Field(gt=0, allow_inf_nan=False)
    connect_timeout_s: int = Field(gt=0)
    pool_pre_ping: bool
