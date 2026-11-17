"""Cost by intent from per-model usage recorded in an e2e run."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median

from pydantic import BaseModel

from eval.e2e_records import E2ERecord

BASELINE_INTENT = "policy_question"
# Call counts within this ratio of the baseline count as "the same number of calls".
SAME_CALLS_RATIO = 1.2


class IntentCost(BaseModel):
    intent: str
    items: int
    mean_calls: float
    mean_tokens: float
    mean_input_tokens: float
    median_tokens: float
    mean_cost: float | None
    median_cost: float | None
    token_share: float
    cost_share: float | None
    route: str


def _tokens(record: E2ERecord) -> int:
    usage = record.usage_by_model or {}
    return sum(item.input_tokens + item.output_tokens for item in usage.values())


def _input_tokens(record: E2ERecord) -> int:
    return sum(item.input_tokens for item in (record.usage_by_model or {}).values())


def cost_by_intent(records: list[E2ERecord]) -> list[IntentCost]:
    """Aggregate measured records (with per-model usage), most tokens first."""
    measured = [record for record in records if record.usage_by_model is not None]
    groups: dict[str, list[E2ERecord]] = defaultdict(list)
    for record in measured:
        groups[record.intent or "unknown"].append(record)
    total_tokens = sum(_tokens(record) for record in measured)
    priced = all(record.estimated_cost_usd is not None for record in measured)
    total_cost = sum(record.estimated_cost_usd or 0.0 for record in measured)
    rows = []
    for intent, group in groups.items():
        tokens = [_tokens(record) for record in group]
        costs = [record.estimated_cost_usd or 0.0 for record in group]
        routes = Counter(" -> ".join(record.trace) for record in group)
        rows.append(
            IntentCost(
                intent=intent,
                items=len(group),
                mean_calls=mean(record.llm_calls or 0 for record in group),
                mean_tokens=mean(tokens),
                mean_input_tokens=mean(_input_tokens(record) for record in group),
                median_tokens=median(tokens),
                mean_cost=mean(costs) if priced else None,
                median_cost=median(costs) if priced else None,
                token_share=sum(tokens) / total_tokens if total_tokens else 0.0,
                cost_share=sum(costs) / total_cost if priced and total_cost else None,
                route=routes.most_common(1)[0][0],
            )
        )
    return sorted(rows, key=lambda row: (-row.mean_tokens, row.intent))


def _money(value: float | None) -> str:
    return f"${value:.6f}" if value is not None else "price not set"


def _share(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "price not set"


def explanation(rows: list[IntentCost]) -> str:
    """One data-derived sentence on the most expensive path and why."""
    if not rows:
        return "No record in this run has per-model usage, so there is no cost table."
    top = max(rows, key=lambda row: (row.mean_cost or 0.0, row.mean_tokens))
    verb = "costs the most" if top.mean_cost is not None else "uses the most tokens"
    sentence = (
        f"`{top.intent}` {verb} per conversation: {top.mean_tokens:.0f} tokens over "
        f"{top.mean_calls:.1f} LLM calls on average ({top.items} items). "
        f"Its most common route is `{top.route}`."
    )
    base = next((row for row in rows if row.intent == BASELINE_INTENT), None)
    if base is not None and base is not top and base.mean_tokens:
        sentence += (
            f" That is {top.mean_tokens / base.mean_tokens:.1f}x the tokens of "
            f"`{base.intent}` ({base.mean_tokens:.0f} tokens, {base.mean_calls:.1f} calls)."
        )
        input_share = top.mean_input_tokens / top.mean_tokens if top.mean_tokens else 0.0
        if top.mean_calls <= base.mean_calls * SAME_CALLS_RATIO:
            sentence += (
                f" The call counts are close, so the gap is prompt size: "
                f"{input_share:.0%} of its tokens are input."
            )
        else:
            sentence += (
                f" It makes {top.mean_calls / base.mean_calls:.1f}x as many LLM calls; "
                f"{input_share:.0%} of its tokens are input."
            )
    return sentence


def cost_lines(records: list[E2ERecord]) -> list[str]:
    rows = cost_by_intent(records)
    measured = [record for record in records if record.usage_by_model is not None]
    calls: Counter[str] = Counter()
    for record in measured:
        for model, usage in (record.usage_by_model or {}).items():
            calls[model] += usage.calls
    models = ", ".join(f"`{model}` ({count} calls)" for model, count in sorted(calls.items()))
    priced = bool(measured) and all(r.estimated_cost_usd is not None for r in measured)
    lines = [
        "## Cost by intent",
        "",
        "Per conversation (one eval item, including any order-picker resume).",
        f"Measured items: {len(measured)} of {len(records)}. Older records without per-model "
        "usage are left out.",
        f"Models reported by the provider: {models or 'none'}.",
        "Prices: "
        + (
            "from `costs.prices` in the config."
            if priced
            else "not set for every model. Fill `costs.prices`, then rerun with "
            "`--report-only` to price this run without new model calls."
        ),
        "",
        "| Intent | Items | LLM calls (mean) | Tokens (mean) | Tokens (median) "
        "| Cost (mean) | Cost (median) | Share of tokens | Share of cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {row.intent} | {row.items} | {row.mean_calls:.2f} | {row.mean_tokens:.0f} | "
        f"{row.median_tokens:.0f} | {_money(row.mean_cost)} | {_money(row.median_cost)} | "
        f"{row.token_share:.1%} | {_share(row.cost_share)} |"
        for row in rows
    )
    lines.extend(["", explanation(rows), ""])
    return lines
