"""Optional vLLM KV-cache prefix reuse benchmark; skips cleanly without a GPU."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def has_nvidia_gpu() -> bool:
    return shutil.which("nvidia-smi") is not None


def run_kv_benchmark(
    *,
    prompts_path: Path | None = None,
    vllm_url: str | None = None,
    model: str = "Qwen/Qwen2.5-3B-Instruct",
) -> dict[str, Any]:
    """Replay saved prompt sequences against vLLM, or skip cleanly when no GPU is present."""
    if not vllm_url and not has_nvidia_gpu():
        return {"status": "skipped", "reason": "no GPU available"}
    if prompts_path is None or not prompts_path.exists():
        return {"status": "skipped", "reason": "prompts.jsonl not provided"}

    endpoint = (vllm_url or "http://127.0.0.1:8001").rstrip("/")
    rows = [
        json.loads(line)
        for line in prompts_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_strategy: dict[str, list[float]] = {}
    with httpx.Client(timeout=60.0) as client:
        for row in rows:
            started = time.perf_counter()
            resp = client.post(
                f"{endpoint}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": row["user_message"]}],
                    "max_tokens": 16,
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            by_strategy.setdefault(row["strategy"], []).append(time.perf_counter() - started)
    return {
        "status": "completed",
        "model": model,
        "mean_latency_s": {k: sum(v) / len(v) for k, v in by_strategy.items() if v},
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Optional vLLM KV-cache benchmark.")
    parser.add_argument("--prompts", type=Path, default=None)
    parser.add_argument("--vllm-url", type=str, default=None)
    parser.add_argument("--model", type=str, default="Qwen/Qwen2.5-3B-Instruct")
    args = parser.parse_args(argv)
    result = run_kv_benchmark(prompts_path=args.prompts, vllm_url=args.vllm_url, model=args.model)
    logger.info("KV benchmark: %s", json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
