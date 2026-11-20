"""Order-grounding check: real order answers must pass, invented claims must be blocked.

Step 1 runs the full graph with the check off, so each order question gets one tool
answer and its tool data. Step 2 runs the check, repeatedly, on two kinds of cases:
those real answers, and authored attacks (a real answer plus one unsupported claim).
Every checker variant and retry setting sees identical inputs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from eval.e2e_eval import _git_sha, _model_names
from eval.gate_round3 import rate_cell
from eval.thread_ids import EvalThreads
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS
from support_agent.graph.nodes.tools_path import execute_tool
from support_agent.graph.order_grounding import check_order_answer
from support_agent.graph.tools import build_order_tools
from support_agent.orders.service import OrderService

QUESTIONS = Path("eval/drafts/order_questions.yaml")
ATTACKS = Path("eval/drafts/order_grounding_attacks.yaml")
ANSWERS = Path("eval/runs/grounding-answers.jsonl")
RUNS = Path("eval/runs")
REPORT = Path("eval/reports/order_grounding.md")
# Checker versions in the order they were built; each has its own run file.
VARIANTS = {
    "single-quote": "one verbatim quote per claim (commit 544bd74)",
    "sentence-quotes": (
        "code numbers every sentence and each must be answered; a fact sentence needs"
        " one quote per data field, and every quote must match"
    ),
}

Kind = Literal["order", "attack"]


class OrderQuestion(BaseModel):
    id: str
    text: str


class AnswerRecord(BaseModel):
    item: OrderQuestion
    trace: list[str]
    answer: str
    order_context: dict[str, Any] | None = None

    @property
    def tools_answer(self) -> bool:
        """The tools path released free text (no handoff, no fallback)."""
        return (
            "tools" in self.trace
            and "tools_fallback" not in self.trace
            and "handoff" not in self.trace
            and bool(self.answer)
            and bool(self.order_context)
        )


class Attack(BaseModel):
    id: str
    base: str | None = None
    add: str | None = None
    answer: str | None = None
    tools: list[str] = Field(default_factory=list)


class Case(BaseModel):
    kind: Kind
    id: str
    answer: str
    order_context: dict[str, Any]


class CheckRecord(BaseModel):
    variant: str
    kind: Kind
    id: str
    max_attempts: int = Field(ge=1)
    rep: int = Field(ge=1)
    status: Literal["grounded", "ungrounded", "error"]
    attempts: int = Field(ge=1)
    missing: list[str] = Field(default_factory=list)


def checks_path(variant: str) -> Path:
    return RUNS / f"grounding-checks-{variant}.jsonl"


def _yaml(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))
    return rows


def _read(path: Path) -> list[dict[str, Any]]:
    full = REPO_ROOT / path
    if not full.exists():
        return []
    return [json.loads(line) for line in full.read_text(encoding="utf-8").splitlines()[1:]]


def _append(path: Path, metadata: dict[str, Any], row: BaseModel) -> None:
    full = REPO_ROOT / path
    full.parent.mkdir(parents=True, exist_ok=True)
    if not full.exists():
        full.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    with full.open("a", encoding="utf-8") as handle:
        handle.write(row.model_dump_json() + "\n")


def metadata(settings: Settings) -> dict[str, Any]:
    return {
        "git_sha": _git_sha(),
        "config_hash": digest(json_text(settings.model_dump(mode="json"))),
        "questions_hash": digest((REPO_ROOT / QUESTIONS).read_text(encoding="utf-8")),
        "attacks_hash": digest((REPO_ROOT / ATTACKS).read_text(encoding="utf-8")),
        "prompt_hash": digest((PROMPTS / "order_grounding.md").read_text(encoding="utf-8")),
        "models": _model_names(settings),
        "customer_id": settings.evaluation.customer_id,
        "date": datetime.now(UTC).isoformat(),
    }


def collect_answers(settings: Settings, meta: dict[str, Any]) -> None:
    done = {row["item"]["id"] for row in _read(ANSWERS)}
    questions = [OrderQuestion.model_validate(row) for row in _yaml(QUESTIONS)]
    pending = [q for q in questions if q.id not in done]
    if not pending:
        return
    answer_settings = settings.model_copy(deep=True)
    answer_settings.agent.order_grounding = False
    customer = settings.evaluation.customer_id
    threads = EvalThreads("grounding")
    with GraphDeps(answer_settings) as deps:
        graph = build_graph(deps)
        for question in pending:
            config: dict[str, Any] = {"configurable": {"thread_id": threads(question.id)}}
            result = graph.invoke(
                {"messages": [HumanMessage(content=question.text)], "customer_id": customer},
                config,
            )
            while result.get("__interrupt__"):
                result = graph.invoke(Command(resume="none"), config)
            record = AnswerRecord(
                item=question,
                trace=list(result.get("trace") or []),
                answer=str(result.get("answer") or ""),
                order_context=result.get("order_context"),
            )
            _append(ANSWERS, meta, record)


def build_cases(answers: list[AnswerRecord], service: OrderService, customer: str) -> list[Case]:
    by_id = {a.item.id: a for a in answers if a.tools_answer}
    cases = [
        Case(kind="order", id=a.item.id, answer=a.answer, order_context=a.order_context or {})
        for a in by_id.values()
    ]
    tools = {tool.name: tool for tool in build_order_tools(service, customer)}
    for attack in (Attack.model_validate(row) for row in _yaml(ATTACKS)):
        if attack.base is not None:
            base = by_id[attack.base]
            text = f"{base.answer}\n\n{attack.add}"
            context = base.order_context or {}
        else:
            text = attack.answer or ""
            context = {name: execute_tool(tools, name, {}).data for name in attack.tools}
        cases.append(Case(kind="attack", id=attack.id, answer=text, order_context=context))
    return cases


def run_checks(
    settings: Settings, meta: dict[str, Any], variant: str, attempts: list[int], reps: int
) -> None:
    path = checks_path(variant)
    done = {(r["kind"], r["id"], r["max_attempts"], r["rep"]) for r in _read(path)}
    answers = [AnswerRecord.model_validate(row) for row in _read(ANSWERS)]
    prompt = (PROMPTS / "order_grounding.md").read_text(encoding="utf-8")
    service = OrderService(settings=settings.orders)
    cases = build_cases(answers, service, settings.evaluation.customer_id)
    with GraphDeps(settings, order_service=service) as deps:
        model = deps.model("main")
        for case in cases:
            for max_attempts in attempts:
                for rep in range(1, reps + 1):
                    if (case.kind, case.id, max_attempts, rep) in done:
                        continue
                    result = check_order_answer(
                        model, prompt, case.order_context, case.answer, max_attempts
                    )
                    row = CheckRecord(
                        variant=variant,
                        kind=case.kind,
                        id=case.id,
                        max_attempts=max_attempts,
                        rep=rep,
                        **result.model_dump(),
                    )
                    _append(path, meta, row)


def _meta_lines(path: Path) -> list[str]:
    full = REPO_ROOT / path
    if not full.exists():
        return []
    meta = json.loads(full.read_text(encoding="utf-8").splitlines()[0])
    keys = ("git_sha", "config_hash", "prompt_hash", "questions_hash", "attacks_hash", "models")
    return [f"- `{path.name}` {key}: `{meta.get(key)}`" for key in keys if key in meta]


def table_lines(checks: list[CheckRecord]) -> list[str]:
    lines = [
        "| Checker | Max attempts | Real answers passed | Attacks caught | "
        "Attacks blocked only by error | Check errors (all cases) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    keys = sorted(
        {(c.variant, c.max_attempts) for c in checks},
        key=lambda k: (list(VARIANTS).index(k[0]), k[1]),
    )
    for variant, max_attempts in keys:
        rows = [c for c in checks if c.variant == variant and c.max_attempts == max_attempts]
        order = [c for c in rows if c.kind == "order"]
        attack = [c for c in rows if c.kind == "attack"]
        cells = [
            rate_cell(sum(c.status == "grounded" for c in order), len(order)) if order else "n/a",
            rate_cell(sum(c.status == "ungrounded" for c in attack), len(attack))
            if attack
            else "n/a",
            rate_cell(sum(c.status == "error" for c in attack), len(attack)) if attack else "n/a",
            rate_cell(sum(c.status == "error" for c in rows), len(rows)),
        ]
        lines.append(f"| {variant} | {max_attempts} | " + " | ".join(cells) + " |")
    return [*lines, ""]


def report_lines(answers: list[AnswerRecord], checks: list[CheckRecord]) -> list[str]:
    tools = [a for a in answers if a.tools_answer]
    lines = [
        "# Order-grounding check: real answers and attacks",
        "",
        "Generated by `make eval-order-grounding`. Real answers: the full graph, with the",
        "check off, answered `eval/drafts/order_questions.yaml` (order lookups for the demo",
        "customer). Attacks: `eval/drafts/order_grounding_attacks.yaml`, a real answer plus",
        "one claim the tool data does not support, and one recorded unsafe answer.",
        "Each case was checked repeatedly with each checker variant and retry setting.",
        "A retry happens only when the reply has no valid structured call.",
        "",
        "Checker variants:",
        "",
        *[f"- `{name}`: {text}" for name, text in VARIANTS.items()],
        "",
        f"- Questions: {len(answers)}; answered by the order tools: {len(tools)}.",
        "- Not answered by the tools (other route, handoff or fallback): "
        + (", ".join(f"`{a.item.id}`" for a in answers if not a.tools_answer) or "none"),
        "",
        "Real answers passed: higher is better. Attacks caught: must be all. An attack",
        "blocked only by a check error is not a detection; it shows the check failing.",
        "",
        *table_lines(checks),
    ]
    for variant in VARIANTS:
        rows = [c for c in checks if c.variant == variant]
        if not rows:
            continue
        missed = sorted({c.id for c in rows if c.kind == "attack" and c.status == "grounded"})
        lines.append(f"- `{variant}` attacks that passed the check at least once: {len(missed)}")
        lines += [f"  - `{i}`" for i in missed]
        retried = sum(c.attempts > 1 for c in rows)
        lines.append(f"- `{variant}` checks that used a retry: {retried}")
    latest = [c for c in checks if c.variant == list(VARIANTS)[-1] and c.kind == "order"]
    missing = Counter(claim for c in latest for claim in c.missing)
    if missing:
        lines += ["", f"Real-answer claims `{list(VARIANTS)[-1]}` found without a quote:", ""]
        lines += [f"- {count} x {claim}" for claim, count in missing.most_common(15)]
    lines += ["", "## Run metadata", "", *_meta_lines(ANSWERS)]
    for variant in VARIANTS:
        lines += _meta_lines(checks_path(variant))
    lines += [
        "",
        "## Limits",
        "",
        "The relay endpoint for `deepseek-flash` is not deterministic; repeats show spread.",
        "Every check error and every claim without a quote drops a real order answer.",
        "Questions and attacks are small, agent-authored and unreviewed sets.",
        "The attacks were also used to find the checker's failure modes; they are not a",
        "holdout for the `sentence-quotes` variant.",
        "Runs used uncommitted checker code on top of the recorded git SHA; the variant",
        "name identifies which checker ran. Default config uses template replies instead.",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=list(VARIANTS), default=list(VARIANTS)[-1])
    parser.add_argument("--attempts", type=int, nargs="+", default=[2])
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.report_only:
        load_dotenv(REPO_ROOT / ".env")
        settings = get_settings()
        meta = metadata(settings)
        collect_answers(settings, meta)
        run_checks(settings, meta, args.variant, args.attempts, args.reps)
    answers = [AnswerRecord.model_validate(row) for row in _read(ANSWERS)]
    checks = [
        CheckRecord.model_validate(row)
        for variant in VARIANTS
        for row in _read(checks_path(variant))
    ]
    write_text(REPO_ROOT / REPORT, "\n".join(report_lines(answers, checks)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
