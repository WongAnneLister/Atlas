"""Exact source offsets from the pinned BGE tokenizer, with a network-free test tokenizer."""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol, cast

from support_agent.config import REPO_ROOT, RetrievalSettings


class Tokenizer(Protocol):
    def spans(self, text: str) -> list[tuple[int, int]]: ...

    def count(self, text: str) -> int: ...


class WhitespaceTokenizer:
    """Test double only. Production counts always use the BGE tokenizer."""

    def spans(self, text: str) -> list[tuple[int, int]]:
        return [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]

    def count(self, text: str) -> int:
        return len(self.spans(text))


class BgeTokenizer:
    def __init__(self, settings: RetrievalSettings) -> None:
        from transformers import AutoTokenizer

        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.backend: Any = AutoTokenizer.from_pretrained(
            settings.embedding_model,
            revision=settings.embedding_revision,
            cache_dir=str(REPO_ROOT / settings.embedding_cache_dir),
            use_fast=True,
        )
        if not self.backend.is_fast:
            raise ValueError("Section-aware chunking requires a fast tokenizer with source offsets")

    def spans(self, text: str) -> list[tuple[int, int]]:
        result = self.backend(
            text, add_special_tokens=False, truncation=False, return_offsets_mapping=True
        )
        return [
            (start, end)
            for start, end in cast(list[tuple[int, int]], result["offset_mapping"])
            if end > start
        ]

    def count(self, text: str) -> int:
        return len(self.spans(text))
