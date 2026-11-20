"""Templated order replies: real order questions answered, and no-answer safety.

Part 1 runs the full graph in template mode on `eval/drafts/order_questions.yaml` and
checks each reply for the facts labelled in `expect`. The free-text replies recorded
by `make eval-order-grounding` (no check) are scored with the same labels.
Part 2 compares full-graph runs on the frozen holdouts: free text with the
order-grounding check (13m) before, template mode after.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from eval.chunking_e2e_report import RUNS, section
from eval.e2e_eval import _git_sha, _model_names
from eval.gate_round3 import rate_cell
from eval.grounding_eval import ANSWERS, QUESTIONS, _append, _read, _yaml
from eval.thread_ids import EvalThreads
from eval.tools_fallback_report import Comparison, route_ok_ids
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps

REPLIES = Path("eval/runs/order-replies-template.jsonl")
REPORT = Path("eval/reports/order_replies.md")


def _runs(*names: str) -> tuple[Path, ...]:
    return tuple(RUNS / f"{name}.jsonl" for name in names)


COMPARISONS = [
    Comparison("Near-miss holdout v1", _runs("fix-v1-r1"), _runs("tpl-v1-r1")),
    Comparison("Cross-store holdout v2", _runs("fix-v2-r1"), _runs("tpl-v2-r1")),
    Comparison("Paraphrase holdout", _runs("fix-para-r1"), _runs("tpl-para-r1")),
    Comparison("Dev split", _runs("fix-dev-r1"), _runs("tpl-dev-r1")),
    Comparison("Answerable store controls", _runs("fix-controls-r1"), _runs("tpl-controls-r1")),
]


class Question(BaseModel):
    id: str
    text: str
    expect: list[str] = Field(min_length=1)


class ReplyRecord(BaseModel):
    id: str
    rep: int = Field(ge=1)
    trace: list[str]
    answer: str
    handoff_reason: str | None = None


def _norm(text: str) -> str:
    return " ".join(text.casefold().replace("_", " ").replace("*", "").split())


def facts_present(answer: str, expect: list[str]) -> bool:
    """Each label must appear; `|` separates accepted forms."""
    text = _norm(answer)
    return all(any(_norm(form) in text for form in label.split("|")) for label in expect)


def order_answered(trace: list[str], answer: str, handoff: bool) -> bool:
    """Answered on the order path: no handoff and no fallback to knowledge."""
    return bool(answer) and not handoff and "tools" in trace and "tools_fallback" not in trace


def questions() -> list[Question]:
    return [Question.model_validate(row) for row in _yaml(QUESTIONS)]


def run_replies(settings: Settings, reps: int) -> None:
    done = {(r["id"], r["rep"]) for r in _read(REPLIES)}
    meta = {
        "git_sha": _git_sha(),
        "config_hash": digest(json_text(settings.model_dump(mode="json"))),
        "questions_hash": digest((REPO_ROOT / QUESTIONS).read_text(encoding="utf-8")),
        "models": _model_names(settings),
        "order_replies": settings.agent.order_replies,
        "date": datetime.now(UTC).isoformat(),
    }
    customer = settings.evaluation.customer_id
    threads = EvalThreads("replies")
    with GraphDeps(settings) as deps:
        graph = build_graph(deps)
        for rep in range(1, reps + 1):
            for question in questions():
                if (question.id, rep) in done:
                    continue
                config: dict[str, Any] = {
                    "configurable": {"thread_id": threads(question.id, str(rep))}
                }
                result = graph.invoke(
                    {"messages": [HumanMessage(content=question.text)], "customer_id": customer},
                    config,
                )
                while result.get("__interrupt__"):
                    result = graph.invoke(Command(resume="none"), config)
                handoff = result.get("handoff")
                reason = getattr(getattr(handoff, "reason", None), "value", None)
                record = ReplyRecord(
                    id=question.id,
                    rep=rep,
                    trace=list(result.get("trace") or []),
                    answer=str(result.get("answer") or ""),
                    handoff_reason=reason,
                )
                _append(REPLIES, meta, record)


def score_lines(label: str, rows: list[tuple[str, list[str], str, bool]]) -> str:
    by_id = {q.id: q for q in questions()}
    answered = [r for r in rows if order_answered(r[1], r[2], r[3])]
    correct = [r for r in answered if facts_present(r[2], by_id[r[0]].expect)]
    return (
        f"| {label} | {len(rows)} | {rate_cell(len(answered), len(rows))} | "
        f"{rate_cell(len(correct), len(rows))} |"
    )


def order_lines() -> list[str]:
    template = [ReplyRecord.model_validate(r) for r in _read(REPLIES)]
    free = _read(ANSWERS)
    lines = [
        "## Real order questions",
        "",
        "Answered: the order path replied (no handoff, no fallback). Correct: answered and",
        "every labelled fact is in the reply. Free text was recorded with no check at all;",
        "with the 13m check most of those replies were blocked",
        "(`eval/reports/order_grounding.md`).",
        "",
        "| Setting | Runs | Answered | Answered with all labelled facts |",
        "|---|---:|---:|---:|",
    ]
    if free:
        rows = [(r["item"]["id"], r["trace"], r["answer"], "handoff" in r["trace"]) for r in free]
        lines.append(score_lines("free text, no check", rows))
    if template:
        rows = [(r.id, r.trace, r.answer, r.handoff_reason is not None) for r in template]
        lines.append(score_lines("template", rows))
        by_id = {q.id: q for q in questions()}
        misses = [
            r
            for r in template
            if not (
                order_answered(r.trace, r.answer, r.handoff_reason is not None)
                and facts_present(r.answer, by_id[r.id].expect)
            )
        ]
        lines += ["", "Template runs that missed (route end, handoff reason):", ""]
        lines += [
            f"- `{r.id}` run {r.rep}: {' > '.join(r.trace[-3:])} ({r.handoff_reason})"
            for r in misses
        ] or ["- none"]
    return [*lines, ""]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.report_only:
        load_dotenv(REPO_ROOT / ".env")
        settings = get_settings().model_copy(deep=True)
        settings.agent.order_replies = "template"
        run_replies(settings, args.reps)
    lines = [
        "# Templated order replies",
        "",
        "Generated by `make eval-order-replies`. In template mode the order model only",
        "chooses lookups and calls `reply` with `answer_from_order_data`. Code renders",
        "the reply from this turn's tool data (`src/support_agent/graph/prompts/",
        "order_replies.yaml`). If the order data does not answer the question, nothing",
        "from the order model is released and the gated knowledge path answers.",
        "",
        *order_lines(),
        "## No-answer safety and false rejects (full graph)",
        "",
        "Before: free text with the order-grounding check (13m runs). After: template",
        "mode. Both use the one-FAQ-per-chunk index, threshold 0.24. One run each.",
        "",
    ]
    route_ok = route_ok_ids()
    for comparison in COMPARISONS:
        lines += section(comparison, route_ok)
    lines += [
        "## Limits",
        "",
        "The relay endpoint for `deepseek-flash` is not deterministic; one run per holdout",
        "setting includes run-to-run noise. Order questions and labels are agent-authored",
        "and unreviewed. Template replies are longer and less conversational than free text.",
        "When the order model wrongly says the order data answers a policy question, the",
        "reply is an order list or order details: nothing invented, but not an answer.",
        "This run counts it as accepted (2 answerable items: one dev, one control).",
        "The one v1 false accept took the knowledge path, not the order path: the gate's",
        "specific-term veto passes when any one term (here `usb`) hits, so the lookalike",
        "model TAH5206 reached the coverage check, which let it through this time.",
    ]
    write_text(REPO_ROOT / REPORT, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
