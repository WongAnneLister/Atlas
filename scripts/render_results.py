"""Write the README results block from the reports in eval/reports (``make results``).

Every number between the markers is read from a generated report. The README text
around the markers is hand-written and must not contain metrics (see tests).
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

START = "<!-- RESULTS:START -->"
END = "<!-- RESULTS:END -->"

E2E = "e2e.md"
RETRIEVAL = "retrieval.md"
INTENT = "intent.md"
JUDGE = "hallucination_review.md"
SWEEP = "threshold_sweep.md"

RETRIEVAL_MODES = {
    "dense": "Dense only (BGE-M3)",
    "bm25": "BM25 only",
    "hybrid": "Hybrid (dense + BM25, RRF)",
    "hybrid_rerank": "Hybrid + rerank (shipped)",
    "hybrid_heading_off": "Hybrid, heading prefix off",
    "hybrid_normaliser_off": "Hybrid, model-number normaliser off",
}


class ReportError(ValueError):
    """A report is missing or does not contain an expected value."""


@dataclass(frozen=True)
class Report:
    name: str
    text: str

    def bullet(self, *labels: str) -> str:
        """Return the value of a ``- Label: value`` metadata line."""
        for label in labels:
            match = re.search(rf"^- {re.escape(label)}: (.+)$", self.text, re.MULTILINE)
            if match:
                return match.group(1).strip().strip("`").strip('"').strip("*")
        raise ReportError(f"{self.name}: no metadata line {labels}")

    def row(self, *keys: str, section: str | None = None) -> list[str]:
        """Return the cells of the first table row that starts with these cells."""
        text = self.section(section) if section else self.text
        for line in text.splitlines():
            cells = _cells(line)
            if cells[: len(keys)] == list(keys):
                return cells
        raise ReportError(f"{self.name}: no table row {keys!r}")

    def section(self, heading: str) -> str:
        """Return the text under a markdown heading, up to the next heading of that level."""
        match = re.search(rf"^(#+) {re.escape(heading)}\s*$", self.text, re.MULTILINE)
        if not match:
            raise ReportError(f"{self.name}: no section {heading!r}")
        level = len(match.group(1))
        rest = self.text[match.end() :]
        end = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
        return rest[: end.start()] if end else rest

    def run_info(self) -> tuple[str, str]:
        """Return the short git SHA and the date of the run."""
        sha = self.bullet("Git SHA", "Git SHA (base revision)", "Git Sha")
        date = self.bullet("Date (UTC)", "Date")
        return sha.strip('"`')[:7], date.strip('"`')[:10]


def _cells(line: str) -> list[str]:
    line = line.strip()
    if not line.startswith("|") or set(line) <= {"|", "-", ":", " "}:
        return []
    return [cell.strip() for cell in line.strip("|").split("|")]


def load(reports_dir: Path, name: str) -> Report:
    path = reports_dir / name
    if not path.is_file():
        raise ReportError(f"missing report {path}")
    return Report(name, path.read_text(encoding="utf-8"))


def _link(name: str, prefix: str) -> str:
    return f"[`{name}`]({prefix}/{name})"


def _cost_summary(e2e: Report) -> str:
    """Mean cost, tokens and LLM calls per conversation, weighted by items per intent."""
    rows = [
        cells
        for line in e2e.section("Cost by intent").splitlines()
        if (cells := _cells(line)) and cells[0] != "Intent"
    ]
    if not rows:
        raise ReportError(f"{e2e.name}: empty cost table")
    items = [int(cells[1]) for cells in rows]
    total = sum(items)
    calls = sum(n * float(cells[2]) for n, cells in zip(items, rows, strict=True)) / total
    tokens = sum(n * float(cells[3]) for n, cells in zip(items, rows, strict=True)) / total
    costs = [cells[5] for cells in rows]
    if any(not cost.startswith("$") for cost in costs):
        cost = "price not set"
    else:
        mean = sum(n * float(c.lstrip("$")) for n, c in zip(items, costs, strict=True)) / total
        cost = f"${mean:.5f}"
    return f"{cost} ({tokens:.0f} tokens, {calls:.2f} LLM calls, mean)"


def render_block(reports_dir: Path, link_prefix: str = "eval/reports") -> str:
    e2e = load(reports_dir, E2E)
    retrieval = load(reports_dir, RETRIEVAL)
    intent = load(reports_dir, INTENT)
    judge = load(reports_dir, JUDGE)
    sweep = load(reports_dir, SWEEP)

    def metric(name: str) -> str:
        return e2e.row(name, section="Outcome metrics")[1]

    test_split = e2e.bullet("Split").split(" ")[0]
    rerank = retrieval.row("hybrid_rerank", "overall", section="test")
    e2e_link, ret_link = _link(E2E, link_prefix), _link(RETRIEVAL, link_prefix)
    intent_link, judge_link = _link(INTENT, link_prefix), _link(JUDGE, link_prefix)
    sweep_link = _link(SWEEP, link_prefix)
    questions = intent.row("Questions")[1]
    latency = f"{metric('Latency P50 full answer')} / {metric('Latency P95 full answer')}"
    flagged = judge.bullet("Judge-flagged rate (all evaluation rows)")

    lines = [
        START,
        "<!-- Generated by `make results` from eval/reports/. Do not edit by hand. -->",
        "",
        "| Metric | Value | Eval set | Source |",
        "|---|---:|---|---|",
        f"| No-answer false accept (full graph) | {metric('False accept')} | {test_split} "
        f"| {e2e_link} |",
        f"| Answerable false reject (full graph) | {metric('False reject')} | {test_split} "
        f"| {e2e_link} |",
        f"| Accepted outcomes | {metric('Accepted')} | {test_split} | {e2e_link} |",
        f"| Retrieval Recall@5 (hybrid + rerank) | {rerank[5]} | test, answerable | {ret_link} |",
        f"| Retrieval MRR@5 (hybrid + rerank) | {rerank[6]} | test, answerable | {ret_link} |",
        f"| Recall@5 inside the full graph | {metric('Recall@5 from graph retrieval')} "
        f"| {test_split} | {e2e_link} |",
        f"| Citation validity (gold-section overlap) | {metric('Citation validity')} "
        f"| {test_split} | {e2e_link} |",
        f"| Intent accuracy | {intent.row('Intent accuracy')[1]} "
        f"| intent holdout ({questions}) | {intent_link} |",
        f"| Hallucination, judge-flagged | {flagged} | {judge.bullet('Split')} | {judge_link} |",
        f"| Hallucination, human-confirmed | {judge.bullet('Human-confirmed rate')} "
        f"| {judge.bullet('Split')} | {judge_link} |",
        f"| Latency P50 / P95 (full answer) | {latency} | {test_split} | {e2e_link} |",
        f"| Cost per conversation | {_cost_summary(e2e)} | {test_split} | {e2e_link} |",
        "",
        "**Retrieval modes** (test split, answerable questions only):",
        "",
        "| Mode | Recall@5 | MRR@5 | Mean latency (s) |",
        "|---|---:|---:|---:|",
    ]
    for mode, label in RETRIEVAL_MODES.items():
        cells = retrieval.row(mode, "overall", section="test")
        lines.append(f"| {label} | {cells[5]} | {cells[6]} | {cells[8]} |")

    threshold = sweep.bullet("Selected threshold")
    dev = sweep.row(threshold, section="Selection")
    held_out = sweep.section("Held-out test")
    test = Report(sweep.name, held_out)
    lines += [
        "",
        f"**Evidence gate alone** (no LLM), threshold `{threshold}` picked on dev ({sweep_link}):",
        "",
        "| Split | False accept | False reject |",
        "|---|---:|---:|",
        f"| dev (tuning) | {dev[1]} | {dev[2]} |",
        f"| test (reported once) | {test.bullet('False accept')} | {test.bullet('False reject')} |",
        "",
        "**Report runs.** Each report records its own run:",
        "",
        "| Report | Git SHA | Date (UTC) |",
        "|---|---|---|",
    ]
    for report in (e2e, retrieval, intent, judge, sweep):
        sha, date = report.run_info()
        lines.append(f"| {_link(report.name, link_prefix)} | `{sha}` | {date} |")
    if judge.run_info()[1] < e2e.run_info()[1]:
        lines += [
            "",
            f"The hallucination review audits an earlier test run ({judge.run_info()[1]}) "
            f"than the full-graph report ({e2e.run_info()[1]}).",
        ]
    lines.append(END)
    return "\n".join(lines)


def replace_block(readme: str, block: str) -> str:
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise ReportError("README must contain exactly one results start and end marker")
    head, rest = readme.split(START)
    _, tail = rest.split(END)
    return head + block + tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, default=Path("eval/reports"))
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    args = parser.parse_args(argv)
    readme = args.readme.read_text(encoding="utf-8")
    updated = replace_block(readme, render_block(args.reports))
    if updated != readme:
        args.readme.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
