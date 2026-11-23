"""In-process pub/sub broker for streaming human agent replies to customer chats via SSE."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any


class HandoffEventBroker:
    """Broadcast human agent replies and resolution events per conversation thread."""

    def __init__(self, *, max_backlog: int = 50) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[tuple[str, dict[str, Any]]]]] = defaultdict(
            set
        )
        self._backlog: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        self._max_backlog = max_backlog

    def publish(self, thread_id: str, event: str, data: dict[str, Any]) -> None:
        item = (event, data)
        history = self._backlog[thread_id]
        history.append(item)
        if len(history) > self._max_backlog:
            del history[: len(history) - self._max_backlog]
        for queue in list(self._subscribers.get(thread_id, ())):
            queue.put_nowait(item)

    async def subscribe(
        self, thread_id: str, *, replay_backlog: bool = True
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._subscribers[thread_id].add(queue)
        try:
            if replay_backlog:
                for item in list(self._backlog.get(thread_id, ())):
                    yield item
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers[thread_id].discard(queue)
            if not self._subscribers[thread_id]:
                self._subscribers.pop(thread_id, None)
