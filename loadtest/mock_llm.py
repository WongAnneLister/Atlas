"""Deterministic OpenAI-compatible mock LLM server for capacity load testing ONLY.

Never import or use this module in quality evaluations.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


@dataclass(frozen=True)
class MockLLMConfig:
    base_latency_ms: float = 30.0
    tokens_per_sec: float = 200.0
    model_name: str = "mock-load-llm"


def _deterministic_reply(messages: list[dict[str, Any]]) -> str:
    joined = " ".join(str(m.get("content", "")) for m in messages).casefold()
    if "classify" in joined or "intent" in joined:
        return json.dumps({"intent": "policy_question", "confidence": 0.95})
    if "refund" in joined and "eligible" in joined:
        return json.dumps({"eligible": False, "reason": "Requires human review [1].", "items": []})
    return "You can return unopened electronics within 30 days of delivery [1]."


def create_mock_llm_app(config: MockLLMConfig | None = None) -> FastAPI:
    cfg = config or MockLLMConfig(
        base_latency_ms=float(os.getenv("MOCK_LLM_LATENCY_MS", "30")),
        tokens_per_sec=float(os.getenv("MOCK_LLM_TOKENS_PER_SEC", "200")),
    )
    app = FastAPI(title="Atlas Load-Test Mock LLM")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model": cfg.model_name}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Any:
        body: dict[str, Any] = await request.json()
        messages = list(body.get("messages") or [])
        stream = bool(body.get("stream", False))
        model = str(body.get("model") or cfg.model_name)
        reply = _deterministic_reply(messages)
        completion_id = f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        tokens = reply.split(" ")

        if cfg.base_latency_ms > 0:
            await asyncio.sleep(cfg.base_latency_ms / 1000.0)

        if not stream:
            if cfg.tokens_per_sec > 0 and tokens:
                await asyncio.sleep(len(tokens) / cfg.tokens_per_sec)
            return JSONResponse(
                {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": reply},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": max(1, sum(len(str(m)) // 4 for m in messages)),
                        "completion_tokens": len(tokens),
                        "total_tokens": max(1, sum(len(str(m)) // 4 for m in messages))
                        + len(tokens),
                    },
                }
            )

        async def event_stream() -> AsyncGenerator[str, None]:
            delay = (1.0 / cfg.tokens_per_sec) if cfg.tokens_per_sec > 0 else 0.0
            for idx, word in enumerate(tokens):
                chunk_text = word if idx == 0 else f" {word}"
                payload = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": chunk_text}
                            if idx == 0
                            else {"content": chunk_text},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(payload)}\n\n"
                if delay > 0:
                    await asyncio.sleep(delay)
            final = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


app = create_mock_llm_app()
