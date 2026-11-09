from __future__ import annotations

import math
from itertools import pairwise

import pytest

from support_agent.config import get_settings
from support_agent.data.build_docs import document
from support_agent.retrieval.chunking import chunk_document, embedding_text, split_text
from support_agent.retrieval.embed import BgeM3Embedder, FakeEmbedder
from support_agent.retrieval.tokenization import WhitespaceTokenizer


def test_chunks_keep_sections_stable_ids_and_overlap() -> None:
    config = get_settings().chunk.model_copy(update={"max_tokens": 6, "overlap_tokens": 2})
    text = document(
        "returns",
        ["fixture"],
        "2026-11-09",
        [
            "## Window\n<!-- section: returns.window -->\n\n"
            "zero one two three four five six seven eight nine ten",
            "## Fee\n<!-- section: returns.fee -->\n\nFees are waived.",
        ],
    )
    chunks = chunk_document(text, config, WhitespaceTokenizer())
    assert chunks == chunk_document(text, config, WhitespaceTokenizer())
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    window = [c for c in chunks if c.section_id == "returns.window"]
    assert len(window) == 3
    assert all(chunk.n_tokens <= config.max_tokens for chunk in chunks)
    for previous, current in pairwise(window):
        assert (
            previous.text.split()[-config.overlap_tokens :]
            == current.text.split()[: config.overlap_tokens]
        )
    assert chunks[-1].text == "Fees are waived."
    assert all("Fees" not in c.text for c in window)
    assert embedding_text(chunks[0], config).startswith("Returns > Window\n\n")
    config.prepend_heading = False
    assert embedding_text(chunks[0], config) == chunks[0].text


def test_paragraph_then_sentence_splitting_keeps_all_source_words() -> None:
    text = "alpha beta gamma.\n\nDelta epsilon zeta. Eta theta iota kappa lambda mu."
    pieces = split_text(text, WhitespaceTokenizer(), maximum=6, overlap=1)
    assert pieces[0] == "alpha beta gamma."
    assert {word for piece in pieces for word in piece.split()} == set(text.split())
    assert all(len(piece.split()) <= 6 for piece in pieces)


def test_products_stay_whole_despite_policy_budget() -> None:
    config = get_settings().chunk.model_copy(update={"max_tokens": 2, "overlap_tokens": 1})
    body = "one two three four five six seven"
    text = document(
        "catalog",
        ["fixture"],
        "2026-11-09",
        [
            "## Model A\n<!-- section: product.A -->\n\n" + body,
        ],
    )
    chunks = chunk_document(text, config, WhitespaceTokenizer())
    assert len(chunks) == 1 and chunks[0].text == body and chunks[0].n_tokens == 7


def test_fake_embedder_is_deterministic_normalised_and_distinguishes_inputs() -> None:
    embedder = FakeEmbedder(get_settings().retrieval.embedding_dim)
    first = embedder.embed(["a", "b"])
    assert first == FakeEmbedder(get_settings().retrieval.embedding_dim).embed(["a", "b"])
    assert first[0] != first[1]
    assert all(math.isclose(sum(value * value for value in vector), 1.0) for vector in first)
    assert embedder.embed([]) == []


class Backend:
    def __init__(self, bad: bool = False) -> None:
        self.seen: list[str] = []
        self.bad = bad

    def encode(self, texts: list[str], **kwargs: object) -> dict[str, list[list[float]]]:
        self.seen.extend(texts)
        return (
            {"dense_vecs": [[1.0, 0.0] if "alpha" in text else [0.0, 1.0] for text in texts]}
            if not self.bad
            else {"dense_vecs": [[1.0]]}
        )


def test_bge_batches_long_inputs_without_losing_tail_and_pools_windows() -> None:
    config = get_settings().retrieval.model_copy(
        update={
            "embedding_dim": 2,
            "embedding_window_tokens": 5,
            "embedding_batch_size": 1,
        }
    )
    backend = Backend()
    embedder = BgeM3Embedder(config, WhitespaceTokenizer(), backend)
    vector = embedder.embed(["alpha beta gamma delta tail"])[0]
    assert backend.seen == ["alpha beta gamma", "delta tail"]
    assert embedder.window_count == 2
    assert vector == pytest.approx([3 / math.sqrt(13), 2 / math.sqrt(13)])
    assert embedder.embed([]) == []


def test_bad_encoder_shape_fails_instead_of_becoming_a_vector() -> None:
    config = get_settings().retrieval.model_copy(update={"embedding_dim": 2})
    with pytest.raises(ValueError, match="wrong vector dimension"):
        BgeM3Embedder(config, WhitespaceTokenizer(), Backend(bad=True)).embed(["test"])
