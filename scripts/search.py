"""Inspect retrieval results without generating an answer."""

from __future__ import annotations

import argparse
import json
import logging
import os

from support_agent.config import get_settings
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.milvus_store import MilvusStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=os.environ.get("Q", ""))
    parser.add_argument(
        "--mode", choices=["dense", "bm25", "hybrid", "hybrid_rerank"], default="hybrid"
    )
    args = parser.parse_args(argv)
    if not args.query.strip():
        parser.error('Supply a query with make search Q="..." or --query')
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    store: MilvusStore | None = None
    try:
        if args.mode == "hybrid_rerank":
            build_retriever(args.mode)  # Fail before opening a connection or loading a model.
        settings = get_settings()
        store = MilvusStore(settings)
        store.server_version()  # Check connectivity before loading model weights.
        retriever = build_retriever(args.mode, settings=settings, store=store)
        results = retriever.retrieve(args.query, settings.retrieval.search_top_k)
        for rank, result in enumerate(results, start=1):
            print(f"{rank}. {result.section_id} [{result.chunk_id}]")
            print(f"   {result.heading_path}")
            print(f"   ranks={json.dumps(result.ranks, sort_keys=True)}")
            print(f"   scores={json.dumps(result.scores, sort_keys=True)}")
        if not results:
            print("No results.")
    except Exception as exc:
        logging.getLogger(__name__).error("search failed: %s", exc)
        return 1
    finally:
        if store is not None:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
