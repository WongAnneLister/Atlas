"""Command-line operations on the Atlas serving index."""

import argparse
import sys
from pathlib import Path

from eval.index_release_runner import check_for
from support_agent.config import Settings, get_settings
from support_agent.data.doc_models import json_text, write_text
from support_agent.retrieval.index_build import build_index
from support_agent.retrieval.index_plan import default_docs_dir, load_corpus, plan_index
from support_agent.retrieval.index_release import (
    MilvusAdmin,
    adopt_index,
    gc_indexes,
    index_status,
    release_index,
    rollback_index,
)
from support_agent.retrieval.registry import IndexRegistry


def _render(data: object) -> None:
    sys.stdout.write(json_text(data) + "\n")


def _run(args: argparse.Namespace, settings: Settings, registry: IndexRegistry) -> int:
    if args.command == "plan":
        corpus = load_corpus(args.docs_dir or default_docs_dir(settings))
        live = registry.get_build(registry.get_alias(settings.index.live_alias).build_id)
        sections = registry.build_sections(live.build_id) if live else {}
        _render(plan_index(corpus, live, sections, settings, force_full=args.full).model_dump())
        return 0
    checks = (
        check_for(
            settings, reranker_device=args.reranker_device, override_reason=args.override_reason
        )
        if args.command in {"ingest", "release"}
        else None
    )
    if args.command in {"build", "ingest"}:
        candidate = build_index(settings, registry, docs_dir=args.docs_dir, force_full=args.full)
        _render(candidate.model_dump(mode="json"))
        if args.command == "build":
            return 0
        args.build_id = candidate.build_id
    admin = MilvusAdmin(settings)
    try:
        if checks is not None:
            decision = release_index(settings, registry, admin, args.build_id, checks)
            report = decision.markdown()
            sys.stdout.write(report)
            if args.output:
                write_text(args.output, report)
            return int(decision.outcome != "release")
        if args.command == "rollback":
            _render(rollback_index(settings, registry, admin).model_dump(mode="json"))
        elif args.command == "adopt":
            _render(
                adopt_index(
                    settings,
                    registry,
                    admin,
                    args.collection,
                    docs_dir=args.docs_dir,
                ).model_dump(mode="json")
            )
        elif args.command == "gc":
            _render(
                {
                    "applied": args.yes,
                    "collections": gc_indexes(settings, registry, admin, yes=args.yes),
                }
            )
        else:
            status = index_status(settings, registry, admin, reconcile=args.reconcile)
            _render(status)
            return int(bool(status["drift"]))
        return 0
    finally:
        admin.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "build", "ingest", "release", "rollback", "status", "adopt", "gc"):
        cli = commands.add_parser(command)
        if command in {"plan", "build", "ingest", "adopt"}:
            cli.add_argument("--docs-dir", type=Path)
        if command in {"plan", "build", "ingest"}:
            modes = cli.add_mutually_exclusive_group()
            modes.add_argument("--full", action="store_true", help="embed the complete corpus")
            modes.add_argument(
                "--incremental",
                action="store_true",
                help="reuse unchanged vectors when compatible (the default)",
            )
        if command in {"ingest", "release"}:
            cli.add_argument("--reranker-device")
            cli.add_argument("--override-reason")
            cli.add_argument("--output", type=Path)
        if command == "release":
            cli.add_argument("build_id")
        if command == "adopt":
            cli.add_argument("collection")
        if command == "status":
            cli.add_argument("--reconcile", action="store_true")
        if command == "gc":
            cli.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    try:
        registry = IndexRegistry.from_settings(settings)
        try:
            return _run(args, settings, registry)
        finally:
            registry.close()
    except (ValueError, RuntimeError, OSError) as error:
        sys.stderr.write(f"Index operation failed: {error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
