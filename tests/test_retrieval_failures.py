from pathlib import Path

import pytest
from eval import failures
from eval.retrieval_experiment import Experiment
from eval.retrieval_records import RetrievalRun

from support_agent.config import get_settings
from support_agent.retrieval.rerank import FakeReranker
from test_retrieval import QueryEmbedder, SearchStore
from test_retrieval_experiment import metadata, question


def test_failure_viewer_prints_only_requested_split_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = get_settings().model_copy(deep=True)
    settings.retrieval_eval.cache_dir = str(tmp_path)
    item = question().model_copy(update={"gold_sections": ["missing.gold"]})
    record = Experiment(
        settings, SearchStore(), QueryEmbedder(), FakeReranker(), tmp_path / "cache", "id"
    ).retrieve("hybrid", item)
    run = RetrievalRun(metadata=metadata(), records=[record], requested_split="dev")
    (tmp_path / "latest_run.json").write_text(run.model_dump_json())
    monkeypatch.setattr(failures, "get_settings", lambda: settings)
    assert failures.main(["--mode", "hybrid"]) == 0
    output = capsys.readouterr().out
    assert item.question in output
    assert "missing.gold" in output
    assert record.chunks[0].heading_path in output
    with pytest.raises(SystemExit, match="2"):
        failures.main(["--mode", "hybrid", "--split", "test"])
