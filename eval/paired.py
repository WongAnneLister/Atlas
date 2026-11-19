"""Pair per-item observations by ID before estimating changes."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from eval.run_record import Run, StatisticName, resolve_statistic, summarize
from eval.stats import Direction, Interval, Verdict, mcnemar_exact, paired_bootstrap_diff, verdict
from support_agent.config import get_settings


class MetricRule(BaseModel):
    direction: Direction
    test: Literal["mcnemar", "bootstrap"]
    statistic: StatisticName = "mean"


@dataclass(frozen=True)
class Comparison:
    name: str
    n: int
    before: float
    after: float
    delta: Interval
    p_value: float | None
    verdict: Verdict


def compare(
    before: Run, after: Run, rules: dict[str, MetricRule], *, strict: bool = False
) -> list[Comparison]:
    left, right = ({row.id: row for row in run.items} for run in (before, after))
    if len(left) != len(before.items) or len(right) != len(after.items):
        raise ValueError("Runs contain duplicate item IDs")
    if strict and left.keys() != right.keys():
        raise ValueError("Both runs must contain the same item IDs")
    ids = sorted(left.keys() & right.keys())
    if not ids:
        raise ValueError("Runs have no shared item IDs")
    for item_id in ids:
        a, b = left[item_id], right[item_id]
        if (a.answerable, a.group) != (b.answerable, b.group):
            raise ValueError(f"Labels differ for {item_id}")

    results = []
    options = get_settings().eval.stats.model_dump()
    for name, rule in rules.items():
        a_ids = {i for i in ids if name in left[i].metrics}
        b_ids = {i for i in ids if name in right[i].metrics}
        if strict and (a_ids != b_ids or not a_ids):
            raise ValueError(f"{name} requires the same observations in both runs")
        shared = sorted(a_ids & b_ids)
        if not shared:
            continue
        a_values = [left[i].metrics[name] for i in shared]
        b_values = [right[i].metrics[name] for i in shared]
        p_value = None
        if rule.test == "mcnemar":
            if not all(type(value) is bool for value in a_values + b_values):
                raise ValueError(f"{name} requires binary observations")
            pairs = list(zip(a_values, b_values, strict=True))
            p_value = mcnemar_exact(
                sum(a and not b for a, b in pairs), sum(b and not a for a, b in pairs)
            )
        stat = resolve_statistic(rule.statistic)
        diff = paired_bootstrap_diff(a_values, b_values, stat, **options)
        results.append(
            Comparison(
                name=name,
                n=len(shared),
                before=summarize(a_values, stat, **options).interval.point,
                after=summarize(b_values, stat, **options).interval.point,
                delta=diff,
                p_value=p_value,
                verdict=verdict(
                    diff, direction=rule.direction, p_value=p_value, alpha=options["alpha"]
                ),
            )
        )
    return results


def comparison_lines(results: list[Comparison]) -> list[str]:
    confidence = 1 - get_settings().eval.stats.alpha
    lines = [
        f"| Metric | Paired n | A | B | Delta | {confidence:.0%} CI | McNemar p | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in results:
        d = row.delta
        p_value = "—" if row.p_value is None else f"{row.p_value:.4g}"
        lines.append(
            f"| {row.name} | {row.n} | {row.before:.6g} | {row.after:.6g} | {d.point:+.6g} | "
            f"[{d.low:+.6g}, {d.high:+.6g}] | {p_value} | {row.verdict} |"
        )
    return lines
