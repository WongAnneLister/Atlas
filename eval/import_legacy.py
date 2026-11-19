"""Convert saved v1 evaluation artifacts without calling a model."""

import argparse
import sys
from pathlib import Path

from eval.e2e_runs import import_e2e, load_e2e
from eval.judge import read_review, save_judge
from eval.legacy_core import import_intent, import_retrieval
from eval.retrieval_csv_runs import import_retrieval_csv
from eval.run_record import RUNS
from eval.sweep_runs import import_sweep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=RUNS)
    parser.add_argument("--suffix", default="legacy")
    commands = parser.add_subparsers(dest="kind", required=True)
    for kind in ("e2e", "intent", "retrieval"):
        commands.add_parser(kind).add_argument("source", type=Path)
    judge = commands.add_parser("judge")
    judge.add_argument("review", type=Path)
    judge.add_argument("e2e", type=Path)
    csv = commands.add_parser("retrieval-csv")
    csv.add_argument("sources", nargs="+", type=Path)
    csv.add_argument("--report", type=Path, default=Path("eval/reports/retrieval.md"))
    sweep = commands.add_parser("sweep")
    sweep.add_argument("dev", type=Path)
    sweep.add_argument("test", type=Path)
    sweep.add_argument("--rule", choices=["lowest", "midpoint"], default="lowest")
    args = parser.parse_args(argv)
    options = {"root": args.root, "suffix": args.suffix}
    if args.kind == "sweep":
        path = import_sweep(args.dev, args.test, rule=args.rule, **options)
    elif args.kind == "retrieval-csv":
        path = import_retrieval_csv(args.sources, args.report, **options)
    elif args.kind == "judge":
        metadata, source_records = load_e2e(args.e2e)
        review = read_review(args.review)
        if len({row.item_id for row in review}) != len(review) or {
            row.item_id for row in review
        } != {row.item.id for row in source_records}:
            raise ValueError("Judge review and E2E run must have the same unique item IDs")
        path = save_judge(
            review, metadata, command=["eval-import-legacy", "judge", args.review.name], **options
        )
    else:
        importer = {"e2e": import_e2e, "intent": import_intent, "retrieval": import_retrieval}
        path = importer[args.kind](args.source, **options)
    sys.stdout.write(f"{path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
