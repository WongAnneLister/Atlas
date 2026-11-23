"""Online drift detection (PSI, KS test, rate deltas) and report rendering."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from support_agent.observability.online_settings import DriftThresholdSettings
from support_agent.observability.online_store import FeedbackRecord, TurnEventRecord

_EPS = 1e-6


class DriftSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: float
    threshold: float
    breached: bool
    reference_summary: str
    current_summary: str


class DriftReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    reference_count: int = Field(ge=0)
    current_count: int = Field(ge=0)
    signals: list[DriftSignal]
    handoff_by_reason_ref: dict[str, float] = Field(default_factory=dict)
    handoff_by_reason_cur: dict[str, float] = Field(default_factory=dict)

    @property
    def breaches(self) -> list[DriftSignal]:
        return [s for s in self.signals if s.breached]


def compute_categorical_psi(reference: Mapping[str, int], current: Mapping[str, int]) -> float:
    """Population Stability Index between two discrete frequency distributions."""
    ref_total = sum(reference.values())
    cur_total = sum(current.values())
    if ref_total == 0 or cur_total == 0:
        return 0.0
    keys = set(reference) | set(current)
    psi = 0.0
    for key in keys:
        p = max(_EPS, reference.get(key, 0) / ref_total)
        q = max(_EPS, current.get(key, 0) / cur_total)
        psi += (q - p) * math.log(q / p)
    return max(0.0, psi)


def compute_continuous_psi(
    reference: Sequence[float],
    current: Sequence[float],
    *,
    bins: int = 10,
) -> float:
    """Population Stability Index over equal-width bins spanning the reference range."""
    if not reference or not current:
        return 0.0
    lo = min(min(reference), min(current))
    hi = max(max(reference), max(current))
    if math.isclose(lo, hi):
        return 0.0
    width = (hi - lo) / bins
    ref_counts: Counter[str] = Counter()
    cur_counts: Counter[str] = Counter()
    for val in reference:
        idx = min(bins - 1, max(0, int((val - lo) / width)))
        ref_counts[f"b{idx}"] += 1
    for val in current:
        idx = min(bins - 1, max(0, int((val - lo) / width)))
        cur_counts[f"b{idx}"] += 1
    return compute_categorical_psi(ref_counts, cur_counts)


def compute_ks_statistic(reference: Sequence[float], current: Sequence[float]) -> float:
    """Exact two-sample Kolmogorov-Smirnov D statistic (max empirical CDF distance)."""
    if not reference or not current:
        return 0.0
    r_sorted = sorted(reference)
    c_sorted = sorted(current)
    n_r, n_c = len(r_sorted), len(c_sorted)
    i = j = 0
    max_d = 0.0
    while i < n_r and j < n_c:
        x = min(r_sorted[i], c_sorted[j])
        while i < n_r and r_sorted[i] <= x:
            i += 1
        while j < n_c and c_sorted[j] <= x:
            j += 1
        max_d = max(max_d, abs(i / n_r - j / n_c))
    return max_d


def _rate(num: int, den: int) -> float:
    return num / den if den > 0 else 0.0


def _avg_cost_per_conv(events: Sequence[TurnEventRecord]) -> float:
    if not events:
        return 0.0
    by_conv: dict[str, float] = {}
    for ev in events:
        by_conv[ev.conversation_id] = by_conv.get(ev.conversation_id, 0.0) + ev.cost_usd
    return sum(by_conv.values()) / len(by_conv) if by_conv else 0.0


def _handoff_rates_by_reason(events: Sequence[TurnEventRecord]) -> dict[str, float]:
    if not events:
        return {}
    counts = Counter(ev.handoff_reason for ev in events if ev.handoff_reason)
    return {reason: count / len(events) for reason, count in counts.items()}


def evaluate_drift(
    reference_events: Sequence[TurnEventRecord],
    current_events: Sequence[TurnEventRecord],
    reference_feedback: Sequence[FeedbackRecord],
    current_feedback: Sequence[FeedbackRecord],
    thresholds: DriftThresholdSettings,
    *,
    now: datetime | None = None,
) -> DriftReport:
    """Compare current window against reference window across all drift signals."""
    ref_intents = Counter(ev.intent or "unknown" for ev in reference_events)
    cur_intents = Counter(ev.intent or "unknown" for ev in current_events)
    intent_psi = compute_categorical_psi(ref_intents, cur_intents)

    ref_scores = [ev.gate_score for ev in reference_events if ev.gate_score is not None]
    cur_scores = [ev.gate_score for ev in current_events if ev.gate_score is not None]
    gate_ks = compute_ks_statistic(ref_scores, cur_scores)
    gate_psi = compute_continuous_psi(ref_scores, cur_scores)

    ref_ho = _rate(sum(1 for e in reference_events if e.handoff_reason), len(reference_events))
    cur_ho = _rate(sum(1 for e in current_events if e.handoff_reason), len(current_events))
    ho_delta = abs(cur_ho - ref_ho)

    ref_skip = _rate(sum(1 for e in reference_events if e.rewrite_skipped), len(reference_events))
    cur_skip = _rate(sum(1 for e in current_events if e.rewrite_skipped), len(current_events))
    skip_delta = abs(cur_skip - ref_skip)

    ref_tok = (
        sum(e.tokens_total for e in reference_events) / len(reference_events)
        if reference_events
        else 0.0
    )
    cur_tok = (
        sum(e.tokens_total for e in current_events) / len(current_events) if current_events else 0.0
    )
    tok_ratio = abs(cur_tok - ref_tok) / ref_tok if ref_tok > 0 else 0.0

    ref_cost = _avg_cost_per_conv(reference_events)
    cur_cost = _avg_cost_per_conv(current_events)
    cost_ratio = abs(cur_cost - ref_cost) / ref_cost if ref_cost > 0 else 0.0

    ref_down = _rate(
        sum(1 for f in reference_feedback if f.rating == "down"), len(reference_feedback)
    )
    cur_down = _rate(sum(1 for f in current_feedback if f.rating == "down"), len(current_feedback))
    down_delta = abs(cur_down - ref_down)

    signals = [
        DriftSignal(
            name="intent_psi",
            value=intent_psi,
            threshold=thresholds.intent_psi,
            breached=intent_psi >= thresholds.intent_psi,
            reference_summary=f"{len(ref_intents)} intents",
            current_summary=f"{len(cur_intents)} intents",
        ),
        DriftSignal(
            name="gate_score_ks",
            value=gate_ks,
            threshold=thresholds.gate_ks,
            breached=gate_ks >= thresholds.gate_ks,
            reference_summary=(
                f"mean {sum(ref_scores) / len(ref_scores):.3f}" if ref_scores else "n/a"
            ),
            current_summary=(
                f"mean {sum(cur_scores) / len(cur_scores):.3f}" if cur_scores else "n/a"
            ),
        ),
        DriftSignal(
            name="gate_score_psi",
            value=gate_psi,
            threshold=thresholds.gate_psi,
            breached=gate_psi >= thresholds.gate_psi,
            reference_summary=f"n={len(ref_scores)}",
            current_summary=f"n={len(cur_scores)}",
        ),
        DriftSignal(
            name="handoff_rate_delta",
            value=ho_delta,
            threshold=thresholds.handoff_rate_delta,
            breached=ho_delta >= thresholds.handoff_rate_delta,
            reference_summary=f"{100 * ref_ho:.1f}%",
            current_summary=f"{100 * cur_ho:.1f}%",
        ),
        DriftSignal(
            name="rewrite_skip_delta",
            value=skip_delta,
            threshold=thresholds.rewrite_skip_delta,
            breached=skip_delta >= thresholds.rewrite_skip_delta,
            reference_summary=f"{100 * ref_skip:.1f}%",
            current_summary=f"{100 * cur_skip:.1f}%",
        ),
        DriftSignal(
            name="tokens_per_turn_ratio",
            value=tok_ratio,
            threshold=thresholds.tokens_per_turn_ratio,
            breached=tok_ratio >= thresholds.tokens_per_turn_ratio,
            reference_summary=f"{ref_tok:.0f} tok",
            current_summary=f"{cur_tok:.0f} tok",
        ),
        DriftSignal(
            name="cost_per_conv_ratio",
            value=cost_ratio,
            threshold=thresholds.cost_per_conv_ratio,
            breached=cost_ratio >= thresholds.cost_per_conv_ratio,
            reference_summary=f"${ref_cost:.4f}",
            current_summary=f"${cur_cost:.4f}",
        ),
        DriftSignal(
            name="thumbs_down_delta",
            value=down_delta,
            threshold=thresholds.thumbs_down_delta,
            breached=down_delta >= thresholds.thumbs_down_delta,
            reference_summary=f"{100 * ref_down:.1f}% (n={len(reference_feedback)})",
            current_summary=f"{100 * cur_down:.1f}% (n={len(current_feedback)})",
        ),
    ]
    return DriftReport(
        generated_at=now or datetime.now(UTC),
        reference_count=len(reference_events),
        current_count=len(current_events),
        signals=signals,
        handoff_by_reason_ref=_handoff_rates_by_reason(reference_events),
        handoff_by_reason_cur=_handoff_rates_by_reason(current_events),
    )


def render_drift_markdown(
    report: DriftReport,
    *,
    git_sha: str = "unknown",
    simulated: bool = False,
    notes: Sequence[str] = (),
) -> str:
    tag = " (SIMULATED WEEK REPLAY)" if simulated else ""
    lines = [
        f"# Online Drift Monitoring Report{tag}",
        "",
        "## Provenance",
        f"- Generated: `{report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}`",
        f"- Git SHA: `{git_sha}`",
        f"- Traffic source: `{'simulated_replay' if simulated else 'live_store'}`",
        f"- Reference window turns: `{report.reference_count}`",
        f"- Current window turns: `{report.current_count}`",
        f"- Breaches detected: `{len(report.breaches)}/{len(report.signals)}`",
        "",
        "## Drift Signals",
        "",
        "| Signal | Value | Threshold | Status | Reference | Current |",
        "|---|---:|---:|---|---|---|",
    ]
    for sig in report.signals:
        status = "**BREACH**" if sig.breached else "ok"
        lines.append(
            f"| `{sig.name}` | {sig.value:.4f} | {sig.threshold:.4f} | {status} "
            f"| {sig.reference_summary} | {sig.current_summary} |"
        )

    all_reasons = sorted(set(report.handoff_by_reason_ref) | set(report.handoff_by_reason_cur))
    if all_reasons:
        lines.extend(
            [
                "",
                "## Handoff Rate by Reason",
                "",
                "| Reason | Reference | Current | Delta |",
                "|---|---:|---:|---:|",
            ]
        )
        for reason in all_reasons:
            r_val = report.handoff_by_reason_ref.get(reason, 0.0)
            c_val = report.handoff_by_reason_cur.get(reason, 0.0)
            lines.append(
                f"| `{reason}` | {100 * r_val:.1f}% | {100 * c_val:.1f}% "
                f"| {100 * (c_val - r_val):+.1f} pp |"
            )

    if notes:
        lines.extend(["", "## Notes"])
        lines.extend(f"- {note}" for note in notes)
    lines.append("")
    return "\n".join(lines)


def export_drift_gauges(report: DriftReport, observer: Any) -> None:
    """Publish drift signal values to Prometheus gauges if supported by observer."""
    fn = getattr(observer, "drift_metric", None)
    if callable(fn):
        for sig in report.signals:
            fn(sig.name, sig.value)
