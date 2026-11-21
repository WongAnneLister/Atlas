from eval.run_record import Run, RunItem, RunManifest, RunMetrics


def run(hit: bool = True, noanswer: bool = False, *, outage: bool = False) -> Run:
    answerable = [
        RunItem(
            id=f"answer-{i}",
            answerable=True,
            group="basic_policy",
            metrics={"hit_at_5": hit, "gate_pass": hit, "rr_at_5": float(hit)},
            payload={"error_type": "TimeoutError" if outage else None},
        )
        for i in range(16)
    ]
    return Run(
        manifest=RunManifest(
            kind="index_release",
            split="dev-smoke",
            git_sha="test",
            config_hash="config",
            models={},
            datasets={},
            seed=None,
            dirty=False,
            started_at=None,
            ended_at=None,
            cost_usd=None,
            cost_note=None,
            command=[],
            source={"item_set_hash": "items"},
        ),
        items=[
            *answerable,
            RunItem(
                id="unsafe",
                group="no_answer",
                answerable=False,
                metrics={"noanswer_gate_pass": noanswer},
            ),
        ],
        metrics=RunMetrics(metrics={}),
    )


def test_identical_index_runs_can_release() -> None:
    from eval.index_release import evaluate_release

    assert evaluate_release(run(), run()).outcome == "release"


def test_absolute_gate_cannot_be_overridden() -> None:
    from eval.index_release import evaluate_release

    result = evaluate_release(run(noanswer=True), run(hit=False), override_reason="policy removed")
    assert result.outcome == "refuse"
    assert "unsafe" in result.markdown()


def test_paired_regression_lists_changed_ids_and_can_be_overridden() -> None:
    from eval.index_release import evaluate_release

    result = evaluate_release(run(hit=False), run())
    assert result.outcome == "refuse"
    assert "hit_at_5" in result.markdown() and "answer-15" in result.markdown()
    result = evaluate_release(run(hit=False), run(), override_reason="retired policy")
    assert result.outcome == "release" and "retired policy" in result.markdown()


def test_outage_is_invalid_instead_of_a_regression() -> None:
    from eval.index_release import evaluate_release

    assert evaluate_release(run(outage=True), run()).outcome == "invalid"


def test_fake_retrieval_records_matching_run_for_reuse(tmp_path, monkeypatch) -> None:
    from eval.index_release import ReleaseSet, collect_run, find_live_run
    from eval.schema import EvalItem

    from support_agent.config import Settings
    from support_agent.retrieval.embed import FakeEmbedder
    from support_agent.retrieval.factory import build_retriever
    from support_agent.retrieval.milvus_store import SearchHit
    from support_agent.retrieval.rerank import FakeReranker
    from test_retrieval import item

    settings = Settings()
    chunk = item("example")
    hit = SearchHit(**chunk.model_dump(exclude={"scores", "ranks"}), score=0.9)
    settings.gate.threshold = 0.99

    class Store:
        def search_dense(self, vector, limit):
            return [hit]

        def search_bm25(self, text, limit):
            return [hit]

    selected = ReleaseSet(
        [
            EvalItem(
                id="answer",
                group="basic_policy",
                split="dev",
                question="Model example?",
                gold_sections=[chunk.section_id],
                answer_points=["Manual"],
                answerable=True,
                source="fixture",
            ),
            EvalItem(
                id="missing",
                group="no_answer",
                split="dev",
                question="Is this supported?",
                gold_sections=[],
                answer_points=[],
                answerable=False,
                source="fixture",
            ),
        ],
        {},
        "dev",
    )
    retriever = build_retriever(
        "hybrid_rerank",
        settings=settings,
        store=Store(),
        embedder=FakeEmbedder(4),
        reranker=FakeReranker(),
    )
    monkeypatch.setattr("eval.index_release.is_dirty", lambda: False)
    path = collect_run(
        settings,
        "fixture",
        build_id="a",
        release_set=selected,
        retriever=retriever,
        run_root=tmp_path,
    )
    assert find_live_run(settings, build_id="a", release_set=selected, run_root=tmp_path) == path
    assert find_live_run(settings, build_id="b", release_set=selected, run_root=tmp_path) is None
    settings.gate.threshold = 0.98
    assert find_live_run(settings, build_id="a", release_set=selected, run_root=tmp_path) is None
    settings.gate.threshold = 0.99
    assert (
        find_live_run(
            settings, build_id="a", release_set=ReleaseSet([], {}, "dev"), run_root=tmp_path
        )
        is None
    )
