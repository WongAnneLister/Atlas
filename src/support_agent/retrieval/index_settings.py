"""Configuration for evidence collection and index operations."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class IndexReleaseSettings(BaseModel):
    sets: list[Literal["dev", "smoke"]] = Field(min_length=1)
    hit_k: int = Field(gt=0)

    @field_validator("sets")
    @classmethod
    def unique_sets(cls, values: list[Literal["dev", "smoke"]]) -> list[Literal["dev", "smoke"]]:
        if len(set(values)) != len(values):
            raise ValueError("Release sets must be unique")
        return values


class IndexSettings(BaseModel):
    release: IndexReleaseSettings
