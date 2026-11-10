"""Injectable dependencies and explicit ownership of checkpoint connections."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from support_agent.config import REPO_ROOT, Settings
from support_agent.llm import Role, get_chat_model
from support_agent.orders.service import OrderService
from support_agent.retrieval.types import Retriever


@dataclass
class GraphDeps:
    settings: Settings
    fast_model: BaseChatModel | None = None
    retriever: Retriever | None = None
    order_service: OrderService | None = None
    main_model: BaseChatModel | None = None
    _resources: ExitStack = field(default_factory=ExitStack, init=False, repr=False)
    _checkpointer: BaseCheckpointSaver[Any] | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def model(self, role: Role = "fast") -> BaseChatModel:
        if self._closed:
            raise RuntimeError("GraphDeps is closed")
        if role == "main":
            if self.main_model is None:
                self.main_model = get_chat_model("main", self.settings)
            return self.main_model
        if self.fast_model is None:
            self.fast_model = get_chat_model("fast", self.settings)
        return self.fast_model

    def checkpointer(self) -> BaseCheckpointSaver[Any]:
        if self._closed:
            raise RuntimeError("GraphDeps is closed")
        if self._checkpointer is None:
            if self.settings.graph.checkpoint_backend == "memory":
                self._checkpointer = InMemorySaver()
            else:
                try:
                    from langgraph.checkpoint.sqlite import SqliteSaver
                except ImportError as error:
                    raise RuntimeError("SQLite checkpoints require the sqlite extra") from error
                checkpoint_path = Path(self.settings.graph.checkpoint_path)
                if not checkpoint_path.is_absolute():
                    checkpoint_path = REPO_ROOT / checkpoint_path
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                self._checkpointer = self._resources.enter_context(
                    SqliteSaver.from_conn_string(str(checkpoint_path))
                )
        return self._checkpointer

    def close(self) -> None:
        self._resources.close()
        self._closed = True

    def __enter__(self) -> GraphDeps:
        if self._closed:
            raise RuntimeError("GraphDeps is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
