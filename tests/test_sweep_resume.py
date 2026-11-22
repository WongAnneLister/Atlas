"""Interrupted score collection preserves completed questions without hiding missing items."""

import json

import pytest
from eval import sweep

from retrieval_fakes import LegacyFilterSupport
from support_agent.config import Settings


def test_score_collection_resumes_after_dependency_failure(tmp_path, monkeypatch):
    items = [
        sweep.EvalItem(
            id=name,
            group="basic_policy",
            split="dev",
            question=name,
            gold_sections=["policy"],
            answer_points=["policy"],
            answerable=True,
            source="fixture",
        )
        for name in ("first", "second")
    ]
    eval_path = tmp_path / "eval.jsonl"
    eval_path.write_text("\n".join(item.model_dump_json() for item in items))
    monkeypatch.setattr(sweep, "_eval_paths", lambda *args: (eval_path, items, "corpus"))
    monkeypatch.setattr(sweep, "_git_sha", lambda: "fixture")
    monkeypatch.setattr(sweep, "BgeM3Embedder", lambda *args: None)
    monkeypatch.setattr(sweep, "BgeReranker", lambda *args: None)

    class Store:
        def __init__(self, *args):
            pass

        def pin_reads(self):
            pass

        def current_build_id(self):
            return None

        def close(self):
            pass

    class Retriever(LegacyFilterSupport):
        def __init__(self):
            self.failed = False
            self.queries = []

        def retrieve(self, query, top_k):
            self.queries.append(query)
            if query == "second" and not self.failed:
                self.failed = True
                raise ConnectionError("tunnel closed")
            return []

    retriever = Retriever()
    monkeypatch.setattr(sweep, "MilvusStore", Store)
    monkeypatch.setattr(sweep, "build_retriever", lambda *args, **kwargs: retriever)
    output = tmp_path / "scores.jsonl"
    with pytest.raises(ConnectionError):
        sweep.collect_scores(Settings(), "dev", output)

    assert output.is_file(), "Completed questions must survive a later retrieval failure"
    metadata, records = sweep.load_scores(output)
    assert [record.id for record in records] == ["first"]
    assert metadata.split == "dev"

    records = sweep.collect_scores(Settings(), "dev", output)
    assert [record.id for record in records] == ["first", "second"]
    assert retriever.queries == ["first", "second", "second"]
    assert len(output.read_text().splitlines()) == 3

    # Compatible metadata must not permit duplicate rows to affect rates.
    output.write_text(output.read_text() + records[0].model_dump_json() + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        sweep.collect_scores(Settings(), "dev", output)

    # A failed replacement must leave the last valid checkpoint intact.
    valid = metadata.model_dump_json() + "\n" + records[0].model_dump_json() + "\n"
    output.write_text(valid)
    original_replace = type(output).replace

    def fail_replace(self, target):
        raise OSError("interrupted replacement")

    monkeypatch.setattr(type(output), "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted replacement"):
        sweep.collect_scores(Settings(), "dev", output)
    assert output.read_text() == valid
    monkeypatch.setattr(type(output), "replace", original_replace)

    # The command must finish an incomplete cache before choosing a threshold.
    output.write_text("\n".join(output.read_text().splitlines()[:2]) + "\n")
    monkeypatch.setattr(sweep, "REPO_ROOT", tmp_path)
    collected = []

    def complete(settings, split, path):
        collected.append(split)
        header = metadata.model_copy(update={"split": split})
        selected = [record.model_copy(update={"split": split}) for record in records]
        path.write_text(
            header.model_dump_json()
            + "\n"
            + "\n".join(r.model_dump_json() for r in selected)
            + "\n"
        )

    monkeypatch.setattr(sweep, "collect_scores", complete)
    monkeypatch.setattr(sweep, "write_report", lambda *args: None)
    monkeypatch.setattr(sweep, "write_plot", lambda *args: None)
    monkeypatch.setattr("eval.sweep_runs.write_intervals", lambda *args: None)
    monkeypatch.setattr(sweep, "_write_config_threshold", lambda *args: None)
    (tmp_path / "manifest.json").write_text(json.dumps({"corpus_hash": "corpus"}))
    sweep.main(["--dev-cache", str(output), "--test-cache", str(tmp_path / "test.jsonl")])
    assert collected == ["dev", "test"]

    # A complete cache must still agree with frozen labels in no-collect mode.
    lines = output.read_text().splitlines()
    altered = json.loads(lines[1])
    altered["answerable"] = False
    lines[1] = json.dumps(altered)
    output.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="No current dev cache"):
        sweep.main(["--dev-cache", str(output), "--no-collect"])


def test_sweep_collects_what_the_knowledge_path_sees():
    """Regression: the sweep scored the raw top 5 while production applies the store scope."""
    from support_agent.retrieval.types import RetrievedChunk

    def chunk(cid, sid):
        return RetrievedChunk(
            chunk_id=cid,
            doc_id="d",
            section_id=sid,
            title="t",
            heading_path="h",
            text="x",
            n_tokens=1,
            scores={"rerank": 0.5},
        )

    class Retriever(LegacyFilterSupport):
        def __init__(self):
            self.calls = []

        def retrieve(self, query, top_k):
            self.calls.append(top_k)
            return [chunk("fk", "a.flipkart_faqs.b"), chunk("gen", "a.maktek_faqs.c")][:top_k]

    retriever = Retriever()
    settings = Settings()
    kept = sweep.production_chunks(retriever, "For the generic store: refunds?", settings)
    assert [c.chunk_id for c in kept] == ["gen"]
    assert retriever.calls == [settings.retrieval.store_scope.pool_k]
