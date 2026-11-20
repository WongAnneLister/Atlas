"""Bound synchronous work without queuing behind stalled operations."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


class BoundedExecutor:
    def __init__(self, max_workers: int, *, thread_name_prefix: str) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=thread_name_prefix
        )
        self._slots = BoundedSemaphore(max_workers)

    def run(self, fn: Callable[[], T], timeout_s: float) -> T:
        deadline = monotonic() + timeout_s
        if timeout_s <= 0 or not self._slots.acquire(timeout=timeout_s):
            raise TimeoutError("No worker slot available within the deadline")
        try:
            if monotonic() >= deadline:
                raise TimeoutError("Operation deadline exceeded")
            future = self._executor.submit(copy_context().run, fn)
        except BaseException:
            self._slots.release()
            raise
        # Timed-out running calls still own their slots until they finish.
        future.add_done_callback(lambda _: self._slots.release())
        try:
            result = future.result(timeout=max(0, deadline - monotonic()))
            if monotonic() > deadline:
                raise TimeoutError("Operation deadline exceeded")
            return result
        except TimeoutError:
            future.cancel()
            raise

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
