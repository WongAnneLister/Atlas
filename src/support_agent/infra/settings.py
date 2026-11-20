"""Redis and readiness settings."""

from typing import Literal

from pydantic import BaseModel, Field


class RedisSettings(BaseModel):
    backend: Literal["null", "redis"]
    connect_timeout_s: float = Field(gt=0, allow_inf_nan=False)
    socket_timeout_s: float = Field(gt=0, allow_inf_nan=False)


class ReadinessSettings(BaseModel):
    postgres_timeout_s: float = Field(gt=0, allow_inf_nan=False)
    migrations_timeout_s: float = Field(gt=0, allow_inf_nan=False)
    redis_timeout_s: float = Field(gt=0, allow_inf_nan=False)
    milvus_timeout_s: float = Field(gt=0, allow_inf_nan=False)
