import csv

import pytest
from eval.e2e_records import JudgeRecord
from eval.judge_calibration import (
    _update_sample,
    calibrate,
    read_kappa,
    render_report,
    select_sample,
)


def test_sample_reproducible_and_includes_every_audited_flag():
    rows = [JudgeRecord(item_id=str(i), flagged=i < 2) for i in range(20)]
    audited = {str(i) for i in range(19)}
    sample = select_sample(rows, audited, seed=17, unflagged=5)
    assert sample == select_sample(list(reversed(rows)), audited, seed=17, unflagged=5)
    assert len(sample) == 7
    assert {"0", "1"} <= set(sample)
    assert set(sample) <= audited


def test_fewer_than_thirty_human_labels_has_no_kappa(tmp_path):
    rows = [JudgeRecord(item_id="a", flagged=True, confirmed="yes")]
    result = calibrate(rows)
    report = tmp_path / "calibration.md"
    report.write_text(render_report(result, {"Split": "test"}), encoding="utf-8")
    assert read_kappa(report) == "kappa: n/a (1/30 labels)"
    assert "29 more" in report.read_text(encoding="utf-8")


def test_precision_recall_and_kappa_use_only_human_labels():
    counts = [(True, "yes", 15), (True, "no", 5), (False, "yes", 3), (False, "no", 17)]
    rows = [
        JudgeRecord(item_id=f"{block}-{index}", flagged=flagged, confirmed=human)
        for block, (flagged, human, count) in enumerate(counts)
        for index in range(count)
    ]
    rows.append(JudgeRecord(item_id="unreviewed", flagged=True))
    result = calibrate(rows, n_resamples=50)
    assert result.label_count == 40
    assert result.precision.point == pytest.approx(15 / 20)
    assert result.recall.point == pytest.approx(15 / 18)
    assert result.kappa.point == pytest.approx(0.6)
    for metric in (result.precision, result.recall, result.kappa):
        assert metric.low <= metric.point <= metric.high


def test_single_class_agreement_leaves_kappa_undefined():
    rows = [JudgeRecord(item_id=str(i), flagged=False, confirmed="no") for i in range(30)]
    result = calibrate(rows)
    assert result.precision is None
    assert result.recall is None
    assert result.kappa is None
    assert "undefined" in render_report(result, {})


def test_refresh_keeps_human_label_and_rejects_changed_answer(tmp_path):
    path = tmp_path / "sample.csv"
    rows = {"a": {"item_id": "a", "answer": "First answer"}}
    assert _update_sample(path, ["a"], rows) == {}
    path.write_text(
        path.read_text(encoding="utf-8").replace("First answer,,,,", "First answer,,,,yes"),
        encoding="utf-8",
    )
    assert _update_sample(path, ["a"], rows) == {"a": "yes"}
    with path.open(encoding="utf-8", newline="") as stream:
        assert next(csv.DictReader(stream))["human_label"] == "yes"

    rows["a"]["answer"] = "Changed answer"
    with pytest.raises(ValueError, match="Stale calibration sample"):
        _update_sample(path, ["a"], rows)
