"""Isolate each eval invocation's conversation checkpoints."""

from uuid import uuid4


class EvalThreads:
    def __init__(self, experiment: str) -> None:
        self.namespace = f"{experiment}:{uuid4().hex}"

    def __call__(self, *item_parts: str) -> str:
        return ":".join((self.namespace, *item_parts))
