"""Optional cached question-only drafting. Gold labels always remain code-owned."""

from __future__ import annotations

import json
import os
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.llm import get_chat_model


class Draft(BaseModel):
    question: str = Field(min_length=1)


class Drafter:
    def __init__(self, settings: Settings, path: Path) -> None:
        self.settings = settings
        self.path = path
        self.prompt = (REPO_ROOT / "src/support_agent/graph/prompts/eval_draft.md").read_text(
            encoding="utf-8"
        )
        self.cache: dict[str, str] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )

    def question(self, question: str, context: object) -> str:
        if self.settings.evaluation.draft_mode == "template":
            return question
        payload = json_text({"question": question, "context": context})
        model_name = os.environ.get("LLM_FAST_MODEL") or self.settings.llm.fast_model
        key = digest(self.prompt + str(model_name) + payload)
        if key not in self.cache:
            reply = get_chat_model("fast", self.settings).invoke(
                [
                    SystemMessage(content=self.prompt),
                    HumanMessage(content=payload),
                ]
            )
            draft = Draft.model_validate_json(str(reply.content))
            self.cache[key] = draft.question
            # Persist each paid call; a later interrupted build can reuse it.
            write_text(self.path, json_text(self.cache))
        return self.cache[key]
