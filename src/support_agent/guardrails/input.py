"""Check only the current user turn before it enters model context."""

import re
import unicodedata
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

InputFlag = Literal[
    "message_length",
    "instruction_override",
    "role_header",
    "prompt_request",
    "roleplay_request",
    "instruction_payload",
    "input_classifier",
    "input_classifier_error",
]
InputAction = Literal["allow", "allow_flagged", "block"]


class InputDecision(BaseModel):
    action: InputAction = "allow"
    flags: list[InputFlag] = Field(default_factory=list)


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flag: InputFlag
    action: Literal["allow_flagged", "block"]
    pattern: str


class InputPatterns:
    def __init__(self, path: Path) -> None:
        rules = TypeAdapter(list[_Rule]).validate_python(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        self.rules = [(rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in rules]

    def check(self, text: str, max_chars: int) -> InputDecision:
        if len(text) > max_chars:
            return InputDecision(action="block", flags=["message_length"])
        normalized = unicodedata.normalize("NFKC", text)
        matched = [rule for rule, pattern in self.rules if pattern.search(normalized)]
        flags = list(dict.fromkeys(rule.flag for rule in matched))
        if any(rule.action == "block" for rule in matched):
            return InputDecision(action="block", flags=flags)
        return InputDecision(action="allow_flagged" if flags else "allow", flags=flags)
