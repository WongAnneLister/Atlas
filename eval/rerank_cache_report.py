"""Measure the rerank score cache on a one-section change and render its report.

``measure`` collects three release-evidence runs in order, on one device, with a fresh
cache file: the live collection with the cache (cold, fills it), the candidate without
the cache, then the candidate with the warm cache. ``report`` compares the last two.
"""

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from eval.index_release import collect_run, load_release_set
from eval.rerank_cache import cache_path
from eval.run_record import RUNS, Run, format_summary, git, read_run
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import json_text, write_text

REPORT = REPO_ROOT / "eval/reports/rerank_cache.md"
PREFIX = "rerank-cache-"
ROLES = {
    "live_cold": "Live collection, cache on (cold; fills the cache)",
    "candidate_uncached": "Candidate collection, cache off",
    "candidate_warm": "Candidate collection, cache on (warm)",
}


def measure(args: argparse.Namespace) -> Path:
    settings = get_settings().model_copy(deep=True)
    settings.retrieval.reranker_device = args.reranker_device
    default = cache_path(settings)
    if default is None:
        raise ValueError("The rerank cache is disabled in the config")
    cache = default.parent / f"measure-{uuid4().hex}.sqlite"
    selected = load_release_set(settings)
    plan = [
        ("live_cold", args.live, args.live_build, True),
        ("candidate_uncached", args.candidate, args.candidate_build, False),
        ("candidate_warm", args.candidate, args.candidate_build, True),
    ]
    runs: dict[str, str] = {}
    for role, collection, build_id, cached in plan:
        config = settings.model_copy(deep=True)
        config.index.release.rerank_cache.enabled = cached
        config.index.release.rerank_cache.path = str(cache)
        path = collect_run(config, collection, build_id=build_id, release_set=selected)
        runs[role] = path.name
        sys.stdout.write(f"{role}: {path}\n")
    stamp = datetime.now(UTC)
    output = RUNS / f"{PREFIX}{stamp:%Y%m%d}-{git('rev-parse', 'HEAD')[:8]}-{uuid4().hex[:8]}"
    write_text(
        output / "measurement.json",
        json_text(
            {
                "device": args.reranker_device,
                "cache_file": cache.name,
                "live_collection": args.live,
                "candidate_collection": args.candidate,
                "runs": runs,
                "ended_at": stamp.isoformat(),
            }
        ),
    )
    return output


def _minutes(run: Run) -> float:
    manifest = run.manifest
    if manifest.started_at is None or manifest.ended_at is None:
        raise ValueError("Run has no start or end time")
    return (manifest.ended_at - manifest.started_at).total_seconds() / 60


def _scores(run: Run) -> dict[str, int]:
    summary = run.manifest.source.get("rerank_scores")
    if not isinstance(summary, dict):
        raise ValueError("Run predates the rerank score counts")
    return {"from_cache": int(summary["from_cache"]), "scored": int(summary["scored"])}


def _profile(cache: Path, key: str | None) -> dict[str, object] | None:
    if key is None or not cache.exists():
        return None
    with sqlite3.connect(cache) as connection:
        row = connection.execute(
            "SELECT profile_json FROM profiles WHERE profile_hash = ?", (key,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def _identity(warm: Run, plain: Run) -> list[str]:
    before = {row.id: row for row in plain.items}
    if before.keys() != {row.id for row in warm.items}:
        raise ValueError("Runs hold different items")
    same_rows = sum(row.model_dump() == before[row.id].model_dump() for row in warm.items)
    same_metrics = sum(row.metrics == before[row.id].metrics for row in warm.items)
    same_top = sum(
        row.payload.get("top_chunk_ids") == before[row.id].payload.get("top_chunk_ids")
        for row in warm.items
    )
    gaps = [
        abs(row.payload["gate_score"] - before[row.id].payload["gate_score"])
        for row in warm.items
        if "gate_score" in row.payload and "gate_score" in before[row.id].payload
    ]
    n = len(warm.items)
    differing = {}
    for row in warm.items:
        old = before[row.id]
        fields = sorted(
            key
            for key in row.payload.keys() | old.payload.keys()
            if row.payload.get(key) != old.payload.get(key)
        ) + (["metrics"] if row.metrics != old.metrics else [])
        if fields:
            differing[row.id] = fields
    detail = [f"  - `{ident}`: {', '.join(fields)}" for ident, fields in sorted(differing.items())]
    return [
        f"- Rows identical (metrics, top-5 chunk ids, gate score, errors): {same_rows}/{n}",
        *(["- Rows that differ, and the fields that differ:", *detail] if detail else []),
        f"- Metrics identical: {same_metrics}/{n}; top-5 lists identical: {same_top}/{n}",
        f"- Largest gate-score difference: {max(gaps, default=0.0):.3g} over {len(gaps)} items",
        f"- Aggregate metrics identical: {warm.metrics == plain.metrics}",
    ]


def render(measurement: Path, settings: Settings) -> str:
    record = json.loads((measurement / "measurement.json").read_text(encoding="utf-8"))
    runs = {role: read_run(RUNS / record["runs"][role]) for role in ROLES}
    warm, plain = runs["candidate_warm"], runs["candidate_uncached"]
    manifest = warm.manifest
    default = cache_path(settings)
    cache = (default.parent if default else REPO_ROOT) / record["cache_file"]
    profile = _profile(cache, manifest.source["rerank_scores"].get("profile"))
    lines = [
        "# Rerank score cache on a one-section change",
        "",
        f"- Report git SHA: {git('rev-parse', 'HEAD')}",
        f"- Run git SHA: {manifest.git_sha} (dirty: {manifest.dirty})",
        f"- Evidence config hash: {manifest.config_hash}",
        f"- Models: {', '.join(manifest.models.values())}",
        "- Dataset versions: "
        + ", ".join(f"{k} {v.version} (`{v.sha256[:12]}`)" for k, v in manifest.datasets.items()),
        f"- Eval split: {manifest.split}",
        f"- Reranker device: {record['device']}",
        f"- Live collection: `{record['live_collection']}`",
        f"- Candidate collection: `{record['candidate_collection']}`",
        f"- Measured: {manifest.started_at:%Y-%m-%d} UTC, three runs in order, one at a time",
    ]
    if profile:
        lines.append(f"- Score key profile: `{json.dumps(profile, sort_keys=True)}`")
    lines.extend(
        [
            "",
            "Wall clock is the run manifest's start to end: model loading, Milvus search "
            "over the SSH tunnel, reranking and the gate. The cache file started empty.",
            "",
            "| Run | Minutes | Pairs from cache | Pairs scored | Items with errors "
            "| Items retried |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for role, run in runs.items():
        scores = _scores(run)
        errors = sum(bool(row.payload.get("error_type")) for row in run.items)
        retried = sum(bool(row.payload.get("retries")) for row in run.items)
        lines.append(
            f"| {ROLES[role]} (`{run.manifest.source['collection']}`) | {_minutes(run):.1f} | "
            f"{scores['from_cache']} | {scores['scored']} | {errors}/{len(run.items)} | "
            f"{retried} |"
        )
    warm_scores, total = _scores(warm), sum(_scores(warm).values())
    lines.extend(
        [
            "",
            "## Candidate: cache on against cache off",
            "",
            f"- Wall clock: {_minutes(plain):.1f} min without the cache, "
            f"{_minutes(warm):.1f} min with it "
            f"({_minutes(plain) - _minutes(warm):.1f} min saved, "
            f"{_minutes(plain) / _minutes(warm):.1f}x faster).",
            f"- Pairs reused: {warm_scores['from_cache']}/{total} "
            f"({warm_scores['from_cache'] / total:.2%}); scored again: {warm_scores['scored']}.",
            f"- Cold run cost: the live run filled the cache in {_minutes(runs['live_cold']):.1f} "
            "min. It is a different collection, so it is context, not a paired measurement.",
            *_identity(warm, plain),
            "- A cached logit is reused bit for bit. A pair scored again runs in a smaller "
            "batch than without the cache, and FlagReranker pads each batch, so its logit can "
            "differ in the last float bits. Any gate-score difference above comes from that.",
            "",
            "| Metric | Cache off | Cache on |",
            "|---|---|---|",
        ]
    )
    for name, summary in plain.metrics.metrics.items():
        other = warm.metrics.metrics[name]
        cells = [format_summary(value, rate=name != "rr_at_5") for value in (summary, other)]
        lines.append(f"| {name} | {cells[0]} | {cells[1]} |")
    lines.extend(["", "Run records:", *(f"- {role}: `{record['runs'][role]}`" for role in ROLES)])
    return "\n".join(lines) + "\n"


def latest() -> Path:
    found = sorted(path for path in RUNS.glob(f"{PREFIX}*") if (path / "measurement.json").exists())
    if not found:
        raise FileNotFoundError("No rerank cache measurement; run `measure` first")
    return found[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("measure")
    run.add_argument("--live", required=True)
    run.add_argument("--candidate", required=True)
    run.add_argument("--live-build")
    run.add_argument("--candidate-build")
    run.add_argument("--reranker-device", required=True)
    report = commands.add_parser("report")
    report.add_argument("--measurement", type=Path)
    args = parser.parse_args()
    if args.command == "measure":
        sys.stdout.write(f"{measure(args)}\n")
        return 0
    write_text(REPORT, render(args.measurement or latest(), get_settings()))
    sys.stdout.write(f"{REPORT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
