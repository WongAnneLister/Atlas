import json

import pytest
from eval.intent_inputs import artifact_hashes, load_benchmark
from eval.intent_records import IntentItem

from support_agent.config import get_settings
from support_agent.data.doc_models import digest
from support_agent.graph.intents import Intent


@pytest.mark.parametrize(
    "changed_file, error_key",
    [
        ("eval/drafts/intent_extra.yaml", "draft_hash"),
        ("eval/common.py", "builder_hash"),
        ("eval/schema.py", "builder_hash"),
    ],
)
def test_loader_rejects_changed_sources_before_model_calls(
    tmp_path, changed_file, error_key
) -> None:
    settings = get_settings().model_copy(deep=True)
    source = next(s for s in settings.data.sources if s.name == "bitext")
    paths = [
        f"data/raw/bitext/{source.files[0]}",
        "eval/sets/eval_v1.jsonl",
        settings.intent_eval.extra_drafts,
        "src/support_agent/graph/prompts/classify.md",
        "eval/intent_data.py",
        "eval/intent_inputs.py",
        "eval/intent_records.py",
        "eval/common.py",
        "eval/schema.py",
        "src/support_agent/data/doc_models.py",
        "src/support_agent/data/intent_map.py",
        "src/support_agent/graph/intents.py",
    ]
    for rel in paths:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture content")
    text = (
        IntentItem(
            id="fixture",
            text="Hello fixture",
            intent=Intent.CHITCHAT_OTHER,
            source="authored:fixture",
            source_label="fixture",
        ).model_dump_json()
        + "\n"
    )
    folder = tmp_path / settings.evaluation.sets_dir
    (folder / "intent_holdout.jsonl").write_text(text)
    manifest = {
        **artifact_hashes(settings, tmp_path),
        "dataset_hash": digest(text),
        "sampling": settings.intent_eval.model_dump(mode="json"),
    }
    (folder / "intent_manifest.json").write_text(json.dumps(manifest))
    assert load_benchmark(settings, tmp_path)[0][0].id == "fixture"
    (tmp_path / changed_file).write_text("changed source")
    with pytest.raises(ValueError, match=error_key):
        load_benchmark(settings, tmp_path)
