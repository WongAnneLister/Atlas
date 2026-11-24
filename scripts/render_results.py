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
STATS_START = "<!-- STATS:START -->"
STATS_END = "<!-- STATS:END -->"

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
    kappa = judge.bullet("Judge calibration")

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
        f"| Hallucination, judge-flagged | {flagged} ({kappa}) "
        f"| {judge.bullet('Split')} | {judge_link} |",
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
    lines += _render_phase2_section(reports_dir, link_prefix)
    lines.append(END)
    return "\n".join(lines)


def _render_phase2_section(reports_dir: Path, link_prefix: str) -> list[str]:
    """Append Phase 2 production metrics when the Phase 2 reports exist."""
    phase2_files = ("redteam.md", "context_ab.md", "memory_long.md", "load.md", "drift.md")
    if not all((reports_dir / name).is_file() for name in phase2_files):
        return []
    redteam = load(reports_dir, "redteam.md")
    ctx_ab = load(reports_dir, "context_ab.md")
    mem_long = load(reports_dir, "memory_long.md")
    load_rep = load(reports_dir, "load.md")
    drift_rep = load(reports_dir, "drift.md")

    rt_overall = redteam.row("**Overall**")[1].split(" (")[0]
    rt_benign = redteam.row("benign_lookalike", section="False blocks")[1].split(" (")[0]
    chunked = ctx_ab.row("`chunked`")
    nocache = ctx_ab.row("`chunked_nocache`")
    mem_recall_on = mem_long.row("Cross-session fact use (recall)")[2]
    mem_leaks = mem_long.row("Cross-customer leak rate (canaries)")[2]
    load_rps_before = load_rep.row("Throughput (req/s)")[1]
    load_rps_after = load_rep.row("Throughput (req/s)")[2]
    load_p95_before = load_rep.row("Overall P50 / P95 / P99 (ms)")[1]
    load_p95_after = load_rep.row("Overall P50 / P95 / P99 (ms)")[2]
    load_avail = load_rep.row("2xx success (availability)")[2]
    drift_breaches = drift_rep.bullet("Breaches detected")

    return [
        "",
        (
            "**Phase 2 production metrics** "
            "(measured in live & capacity evals; drift is a simulated week):"
        ),
        "",
        "| Area | Metric | Measured value | Source |",
        "|---|---|---:|---|",
        (
            f"| Security | Red-team v2 overall ASR | {rt_overall} "
            f"| {_link('redteam.md', link_prefix)} |"
        ),
        (
            f"| Security | Benign look-alike false blocks | {rt_benign} "
            f"| {_link('redteam.md', link_prefix)} |"
        ),
        (
            f"| Context / Cache | Prefix-cache hit ratio (`chunked` vs uncached units/conv) "
            f"| {chunked[4]} ({chunked[7]} vs {nocache[7]} units) "
            f"| {_link('context_ab.md', link_prefix)} |"
        ),
        (
            f"| Long-term Memory | Cross-session fact use (ON) "
            f"| {mem_recall_on} | {_link('memory_long.md', link_prefix)} |"
        ),
        (
            f"| Long-term Memory | Cross-customer canary leaks "
            f"| {mem_leaks} | {_link('memory_long.md', link_prefix)} |"
        ),
        (
            f"| Load / Capacity | Throughput before -> after fix (mock LLM, conc=16) "
            f"| {load_rps_before} -> {load_rps_after} req/s ({load_avail}) "
            f"| {_link('load.md', link_prefix)} |"
        ),
        (
            f"| Load / Capacity | Overall P50 / P95 / P99 before -> after "
            f"| {load_p95_before} -> {load_p95_after} ms | {_link('load.md', link_prefix)} |"
        ),
        (
            f"| Online Drift (simulated) | Day-5 missing-doc shift breaches caught "
            f"| {drift_breaches} | {_link('drift.md', link_prefix)} |"
        ),
    ]


def render_stats_block(reports_dir: Path) -> str:
    specs = (
        (
            E2E,
            "Full graph",
            (
                "false_accept",
                "false_reject",
                "pass_rate",
                "graph_recall_at_5",
                "graph_mrr_at_5",
                "citation_validity",
                "latency_p50",
                "latency_p95",
            ),
        ),
        (
            SWEEP,
            "Evidence gate alone",
            (
                "dev.false_accept",
                "dev.false_reject",
                "test.false_accept",
                "test.false_reject",
            ),
        ),
        (
            RETRIEVAL,
            "Hybrid + rerank · test",
            (
                "test.hybrid_rerank.overall.recall@5",
                "test.hybrid_rerank.overall.mrr@5",
            ),
        ),
        (INTENT, "Intent holdout", ("accuracy", "path_accuracy", "parse_failure_rate")),
        (JUDGE, "Hallucination audit", ("judge_flagged",)),
    )
    lines = [
        STATS_START,
        "<!-- Generated by `make results` from eval/reports/. Do not edit by hand. -->",
        "",
        "| Eval | Metric | Estimate and interval | Source |",
        "|---|---|---|---|",
    ]
    for filename, label, names in specs:
        report = load(reports_dir, filename)
        if filename in (E2E, JUDGE):
            label = f"{label} · {report.bullet('Split').split()[0]}"
        heading = re.search(
            r"^## (Confidence intervals|Bootstrap intervals .+)$", report.text, re.MULTILINE
        )
        if heading is None:
            raise ReportError(f"{filename}: missing confidence interval table")
        section = report.section(heading.group(1))
        rows = {
            _cells(line)[0]: _cells(line)[1]
            for line in section.splitlines()
            if line.startswith("| ") and len(_cells(line)) == 2
        }
        for name in names:
            key = name
            if filename == JUDGE:
                key = f"{name} ({report.bullet('Judge calibration')})"
            if key not in rows:
                raise ReportError(f"{filename}: missing interval for {key}")
            lines.append(
                f"| {label} | {key} | {rows[key]} | {_link(filename, '../eval/reports')} |"
            )
    lines.extend(["", STATS_END])
    return "\n".join(lines)


def replace_block(readme: str, block: str, start: str = START, end: str = END) -> str:
    if readme.count(start) != 1 or readme.count(end) != 1:
        raise ReportError("Document must contain exactly one results start and end marker")
    head, rest = readme.split(start)
    _, tail = rest.split(end)
    return head + block + tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, default=Path("eval/reports"))
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--results-doc", type=Path)
    args = parser.parse_args(argv)
    readme = args.readme.read_text(encoding="utf-8")
    updated = replace_block(readme, render_block(args.reports))
    if args.results_doc:
        results = args.results_doc.read_text(encoding="utf-8")
        updated_results = replace_block(
            results, render_stats_block(args.reports), STATS_START, STATS_END
        )
        if updated_results != results:
            args.results_doc.write_text(updated_results, encoding="utf-8")
    if updated != readme:
        args.readme.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
