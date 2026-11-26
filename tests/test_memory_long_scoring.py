from eval.memory_long_eval import recall_scores


def test_a_memory_in_the_prompt_is_not_counted_as_used_unless_the_reply_uses_it() -> None:
    used, loaded, redundant = recall_scores(
        "Which model do you own?", "Owns a Philips W40.", [], ["w40"]
    )
    assert (used, loaded) == (False, True)
    assert redundant

    used, loaded, _ = recall_scores(
        "Your W40 has a two-year warranty.", "", ["Owns a W40"], ["W40"]
    )
    assert (used, loaded) == (True, True)


def test_save_run_keeps_full_text_for_rescoring(tmp_path) -> None:
    import json

    from eval.memory_long_eval import ScenarioResult, save_run

    from support_agent.config import Settings

    row = ScenarioResult(
        scenario_id="s1",
        group="recall",
        arm="memory_on",
        latency_ms=1.0,
        fact_used=True,
        memory_loaded=True,
        redundant_question=False,
        stale_error=None,
        leaked=None,
        deletion_honoured=None,
        stored_memories=[],
        storage_bytes=0,
        answer_preview="Your W40",
        answer="Your W40 has a two-year warranty.",
        loaded_memory="Owns a W40.",
    )
    run = save_run([row], Settings(), tmp_path)
    saved = json.loads((run / "items.jsonl").read_text().splitlines()[0])
    assert saved["answer"] == "Your W40 has a two-year warranty."
    assert saved["loaded_memory"] == "Owns a W40."
    assert {"git_sha", "dirty", "config_hash", "models"} <= json.loads(
        (run / "run.json").read_text()
    ).keys()
