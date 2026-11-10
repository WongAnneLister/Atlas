"""Explicit, one-time real-model drafting; the resulting source file is then frozen."""

from __future__ import annotations

import argparse
import logging

import yaml
from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from eval.intent_records import ExtraDrafts
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import write_text
from support_agent.llm import get_chat_model


class ReturnUtterances(BaseModel):
    utterances: list[str] = Field(min_length=1)


def draft_returns(model: BaseChatModel, count: int) -> tuple[list[str], str | None]:
    prompt = (REPO_ROOT / "src/support_agent/graph/prompts/intent_draft.md").read_text()
    response = model.with_structured_output(ReturnUtterances, include_raw=True).invoke(
        [SystemMessage(content=prompt.format(count=count))]
    )
    if not isinstance(response, dict) or response.get("parsing_error"):
        raise ValueError("Return drafting produced invalid structured output")
    parsed = ReturnUtterances.model_validate(response.get("parsed"))
    if len(parsed.utterances) != count or any(not text.strip() for text in parsed.utterances):
        raise ValueError("Return draft count differs from the requested count")
    raw = response.get("raw")
    metadata = getattr(raw, "response_metadata", {})
    name = metadata.get("model_name") or metadata.get("model")
    return parsed.utterances, name if isinstance(name, str) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    load_dotenv(REPO_ROOT / ".env")
    settings = get_settings()
    path = REPO_ROOT / settings.intent_eval.extra_drafts
    drafts = ExtraDrafts.model_validate(yaml.safe_load(path.read_text()))
    if drafts.returns:
        raise ValueError("Return drafts already exist; refusing to replace frozen examples")
    model = get_chat_model("fast", settings)
    texts, response_model = draft_returns(model, settings.intent_eval.extra_per_kind)
    drafts.returns, drafts.returns_model = texts, response_model
    drafts.returns_source = "model:" + (
        response_model or settings.llm.fast_model or "configured-fast"
    )
    write_text(path, yaml.safe_dump(drafts.model_dump(), sort_keys=False, allow_unicode=True))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger(__name__).info("Saved %d model-drafted return examples", len(texts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
