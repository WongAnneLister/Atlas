"""Project legacy core eval rows onto the observations used by the run comparer."""

from pathlib import Path

from eval.intent_records import IntentRun
from eval.legacy_core import intent_items, retrieval_items
from eval.retrieval_csv_runs import retrieval_csv_items
from eval.retrieval_records import RetrievalRun
from eval.run_record import Run, RunItem
from eval.sweep import load_scores
from eval.sweep_runs import score_run_items


def rows_for_legacy_core(path: Path, reference: Run) -> list[RunItem]:
    match reference.manifest.kind:
        case "intent":
            saved = IntentRun.model_validate_json(path.read_text(encoding="utf-8"))
            return intent_items(saved.records)
        case "retrieval":
            if path.suffix.lower() == ".csv":
                return retrieval_csv_items([path])
            saved = RetrievalRun.model_validate_json(path.read_text(encoding="utf-8"))
            return retrieval_items(
                saved.records, saved.metadata.settings["retrieval_eval"]["metric_ks"]
            )
        case "sweep":
            _, rows = load_scores(path)
            # Score caches omit the selection. Replay at the reference run's threshold.
            return score_run_items(rows, reference.manifest.source["threshold"])
        case _:
            raise ValueError(f"Unsupported legacy eval kind {reference.manifest.kind!r}")
