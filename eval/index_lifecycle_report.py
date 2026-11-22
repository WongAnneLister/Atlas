"""Render the commit 22b index lifecycle evidence from saved outputs and run records."""

import argparse
import json
import math
import sys
from pathlib import Path

from eval.index_release import absolute_ids, evaluate_release, load_release_set
from eval.paired import comparison_lines
from eval.run_record import RUNS, Run, format_summary, git, read_run
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import write_text
from support_agent.retrieval.index_build import store_for
from support_agent.retrieval.index_models import BuildRecord
from support_agent.retrieval.registry import IndexRegistry

EVIDENCE = RUNS / "index-lifecycle-22b"
DEVICE = "mps"
REPORT = REPO_ROOT / "eval/reports/index_lifecycle.md"


def vector_drift(first: str, second: str) -> dict[str, object]:
    """Compare the stored dense vectors of two collections chunk by chunk."""
    settings = get_settings()
    vectors = []
    for name in (first, second):
        store = store_for(settings, name)
        try:
            rows = store.read_vectors(sorted({chunk.section_id for chunk in store.read_chunks()}))
        finally:
            store.close()
        vectors.append({row.chunk.chunk_id: row.dense for row in rows})
    a, b = vectors
    if a.keys() != b.keys():
        raise ValueError("Collections hold different chunk ids")
    worst = max(max(abs(x - y) for x, y in zip(a[k], b[k], strict=True)) for k in a)
    cosine = min(
        sum(x * y for x, y in zip(a[k], b[k], strict=True))
        / (math.sqrt(sum(x * x for x in a[k])) * math.sqrt(sum(y * y for y in b[k])))
        for k in a
    )
    identical = sum(a[k] == b[k] for k in a)
    return {
        "first": first,
        "second": second,
        "chunks": len(a),
        "bit_identical_chunks": identical,
        "max_abs_difference": worst,
        "min_cosine": cosine,
    }


def _runs() -> list[tuple[Path, Run]]:
    found = []
    for path in RUNS.glob("index-release-*"):
        try:
            found.append((path, read_run(path)))
        except (OSError, ValueError):
            continue
    return sorted(found, key=lambda item: item[1].manifest.started_at)


def _errors(run: Run) -> int:
    return sum(1 for row in run.items if row.payload.get("error_type"))


def _retried(run: Run) -> int:
    return sum(1 for row in run.items if row.payload.get("retries"))


def _run_for(runs: list[tuple[Path, Run]], **source: object) -> tuple[Path, Run]:
    """The latest error-free MPS run for a source; failed attempts are listed separately."""
    matches = [
        (path, run)
        for path, run in runs
        if run.manifest.source.get("reranker_device") == DEVICE
        and not _errors(run)
        and not run.manifest.dirty
        and all(run.manifest.source.get(key) == value for key, value in source.items())
    ]
    if not matches:
        raise ValueError(f"No complete release run for {source}")
    return matches[-1]


def _top_changes(first: Run, second: Run) -> tuple[int, float]:
    a = {row.id: row.payload for row in first.items}
    b = {row.id: row.payload for row in second.items}
    changed = sum(a[key]["top_chunk_ids"] != b[key]["top_chunk_ids"] for key in a)
    gap = max(abs(a[key]["gate_score"] - b[key]["gate_score"]) for key in a)
    return changed, gap


def _attempts(runs: list[tuple[Path, Run]], names: dict[str, str]) -> list[str]:
    lines = [
        "| Started (UTC) | Collection | Device | Minutes | Items with errors | Items retried |",
        "|---|---|---|---:|---:|---:|",
    ]
    for _, run in runs:
        manifest = run.manifest
        minutes = (manifest.ended_at - manifest.started_at).total_seconds() / 60
        collection = str(manifest.source.get("collection"))
        lines.append(
            f"| {manifest.started_at:%Y-%m-%d %H:%M} | {names.get(collection, collection)} | "
            f"{manifest.source.get('reranker_device')} | {minutes:.0f} | {_errors(run)}/"
            f"{len(run.items)} | {_retried(run)} |"
        )
    return lines


def _build_output(build_id: str) -> dict[str, object]:
    return dict(json.loads((EVIDENCE / f"build-{build_id}.json").read_text(encoding="utf-8")))


def _decision_section(
    title: str,
    candidate: tuple[Path, Run],
    live: tuple[Path, Run] | None,
    absolute: frozenset[str],
) -> list[str]:
    old = evaluate_release(candidate[1], live[1] if live else None, absolute=None)
    decision = evaluate_release(candidate[1], live[1] if live else None, absolute=absolute)
    lines = [
        f"### {title}",
        "",
        f"- Outcome under the current rule: **{decision.outcome}**",
        *[f"  - Reason: {reason}" for reason in decision.reasons],
        *[f"  - Note: {note}" for note in decision.notes],
        f"- Outcome under the planned rule (zero passes on every no-answer item): "
        f"**{old.outcome}**",
        *[f"  - Reason: {reason}" for reason in old.reasons],
        f"- Candidate run: `{candidate[0].relative_to(REPO_ROOT)}`",
    ]
    if live:
        lines.append(f"- Live run: `{live[0].relative_to(REPO_ROOT)}`")
    lines += ["", "| Metric | Candidate [95% CI] |", "|---|---|"]
    for name, summary in candidate[1].metrics.metrics.items():
        lines.append(f"| {name} | {format_summary(summary, rate=name != 'rr_at_5')} |")
    if decision.comparisons:
        lines += ["", *comparison_lines(decision.comparisons)]
    for metric, ids in decision.changes.items():
        lines.append(f"- Items that changed on {metric}: {len(ids)}")
    if live:
        changed, gap = _top_changes(live[1], candidate[1])
        lines += [
            "",
            f"- Items whose top-{get_settings().index.release.hit_k} chunk list differs from the "
            f"live run: {changed}/{len(candidate[1].items)}; largest gate-score "
            f"difference: {gap:.3g}.",
        ]
    return [*lines, ""]


def _builds_table(builds: list[BuildRecord]) -> list[str]:
    lines = [
        "| Build | Collection | Mode | Status | Parent | Docs hash | Release evidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for build in sorted(builds, key=lambda item: item.created_at):
        lines.append(
            f"| `{build.build_id[:8]}` | `{build.collection}` | {build.mode} | {build.status} | "
            f"{(build.parent_build_id or '—')[:8]} | `{build.docs_hash[:12]}` | "
            f"{build.eval_run_id or '—'} |"
        )
    return lines


def _chat(name: str) -> list[str]:
    path = EVIDENCE / f"chat-{name}.txt"
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [f"> {line}" if line else ">" for line in lines if line.strip()] or ["> (empty)"]


def render() -> str:
    settings = get_settings()
    registry = IndexRegistry.from_settings(settings)
    try:
        builds = registry.builds()
        alias = registry.get_alias(settings.index.live_alias)
    finally:
        registry.close()
    adopted = next(build for build in builds if build.mode == "adopted")
    full = next(b for b in builds if b.mode == "full" and b.parent_build_id == adopted.build_id)
    incremental = next(build for build in builds if build.mode == "incremental")
    runs = _runs()
    absolute = absolute_ids(load_release_set(settings), settings)
    live_adopted = _run_for(runs, build_id=adopted.build_id)
    full_run = _run_for(runs, build_id=full.build_id)
    incremental_run = _run_for(runs, build_id=incremental.build_id)
    control = _run_for(runs, collection=settings.retrieval_eval.heading_ablation_collection)
    full_out, inc_out = _build_output(full.build_id), _build_output(incremental.build_id)
    plan = json.loads((EVIDENCE / "plan-incremental.json").read_text(encoding="utf-8"))
    drift = json.loads((EVIDENCE / "vectors-adopted-vs-full.json").read_text(encoding="utf-8"))
    expectation = (EVIDENCE / "negative-control-expectation.md").read_text(encoding="utf-8")
    manifest = full_run[1].manifest
    names = {
        adopted.collection: "adopted",
        full.collection: "full rebuild",
        incremental.collection: "incremental",
        settings.retrieval_eval.heading_ablation_collection: "negative control",
    }
    lines = [
        "# Index lifecycle evidence (commit 22b)",
        "",
        f"- Report git SHA: {git('rev-parse', 'HEAD')}",
        f"- Release-check git SHA: {manifest.git_sha} (dirty: {manifest.dirty})",
        f"- Release-check config hash: {manifest.config_hash}",
        f"- Models: {', '.join(manifest.models.values())}",
        "- Dataset versions: "
        + ", ".join(
            f"{name} {item.version} (`{item.sha256[:12]}`)"
            for name, item in sorted(manifest.datasets.items())
        ),
        f"- Eval split: {manifest.split} (frozen dev items plus the frozen smoke items)",
        f"- Reranker device: {manifest.source.get('reranker_device')}",
        f"- Collected: {manifest.started_at:%Y-%m-%d} UTC",
        "- Release checks use retrieval and the evidence gate only. No LLM is called.",
        "",
        "## Registry",
        "",
        *_builds_table(builds),
        "",
        f"Alias `{alias.alias}` now targets `{(alias.build_id or '—')[:8]}`; "
        f"previous `{(alias.previous_build_id or '—')[:8]}`.",
        "",
        "## Every release-check run",
        "",
        "All collection attempts are listed, including those cut short by drops of the SSH",
        "tunnel to Milvus. Decisions below use only the complete MPS runs. An attempt with too",
        "many errors is invalid; one with an unassessed no-answer item is refused. The alias",
        "never moved on a failed attempt. Per-question retries were added after the CPU attempts.",
        "",
        *_attempts(runs, names),
        "",
        "## 1. Adoption",
        "",
        f"`support_chunks` was registered as build `{adopted.build_id[:8]}` without a release "
        "check. Its chunks matched the on-disk documents exactly.",
        "",
        "## 2. Identical full rebuild",
        "",
        f"- Embedded {full_out['embedded_chunks']} chunks, copied {full_out['copied_chunks']}, "
        f"total {full_out['chunk_count']}, in {full_out['elapsed_s']:.1f} s.",
        f"- Stored vectors against the adopted collection: {drift['bit_identical_chunks']}/"
        f"{drift['chunks']} chunks bit-identical, max absolute difference "
        f"{drift['max_abs_difference']:.3g}, minimum cosine {drift['min_cosine']:.10f}.",
        "",
        *_decision_section(
            "Release check: full rebuild against adopted", full_run, live_adopted, absolute
        ),
        "## 3. Negative control",
        "",
        "Expectation, written before any release output was seen:",
        "",
        *[f"> {line}" if line else ">" for line in expectation.strip().splitlines()],
        "",
        *_decision_section(
            "Release check: no-heading collection against live", control, full_run, absolute
        ),
        "## 4. One-section change",
        "",
        f"- Plan: {len(plan['changed'])} changed, {len(plan['added'])} added, "
        f"{len(plan['deleted'])} deleted, {len(plan['unchanged'])} unchanged; "
        f"mode {plan['mode']}.",
        f"- Incremental build: embedded {inc_out['embedded_chunks']} chunks, copied "
        f"{inc_out['copied_chunks']}, total {inc_out['chunk_count']}, in "
        f"{inc_out['elapsed_s']:.1f} s (full rebuild: {full_out['embedded_chunks']} embedded, "
        f"{full_out['elapsed_s']:.1f} s).",
        "",
        *_decision_section(
            "Release check: incremental against full", incremental_run, full_run, absolute
        ),
        "### Real app after release (`make chat`)",
        "",
        *_chat("released"),
        "",
        "### Real app after `make index-rollback`",
        "",
        *_chat("rollback"),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    drift = commands.add_parser("vectors")
    drift.add_argument("first")
    drift.add_argument("second")
    drift.add_argument("--output", type=Path, required=True)
    commands.add_parser("report")
    args = parser.parse_args()
    if args.command == "vectors":
        write_text(args.output, json.dumps(vector_drift(args.first, args.second), indent=2) + "\n")
        return 0
    write_text(REPORT, render())
    sys.stdout.write(f"{REPORT.relative_to(REPO_ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
