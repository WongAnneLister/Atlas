"""Injectable dependencies and explicit ownership of checkpoint connections."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from types import TracebackType
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from support_agent.config import REPO_ROOT, Settings
from support_agent.graph.postgres import postgres_saver
from support_agent.llm import Role, get_chat_model, resolve_model
from support_agent.orders.service import OrderService
from support_agent.reliability.chaos import ChaosInjector
from support_agent.reliability.circuit import CircuitRegistry
from support_agent.reliability.events import ReliabilityObserver
from support_agent.reliability.guards import DependencyGuards
from support_agent.reliability.llm_calls import LLMFault, ModelMessages, ReliableModels
from support_agent.reliability.stores import GuardedMilvusSearch, GuardedOrders, GuardedReranker
from support_agent.reliability.timeouts import BoundedExecutor
from support_agent.retrieval.embed import BgeM3Embedder
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.rerank import BgeReranker
from support_agent.retrieval.types import Retriever


@dataclass
class GraphDeps:
    settings: Settings
    fast_model: BaseChatModel | None = None
    retriever: Retriever | None = None
    order_service: OrderService | None = None
    main_model: BaseChatModel | None = None
    allow_untuned_gate: bool = False
    observer: ReliabilityObserver | None = None
    llm_fault: LLMFault | None = None
    model_messages: ModelMessages | None = None
    chaos_injector: ChaosInjector = field(init=False, repr=False)
    circuits: CircuitRegistry = field(init=False, repr=False)
    model_workers: BoundedExecutor = field(init=False, repr=False)
    models: ReliableModels = field(init=False, repr=False)
    _model_cache: dict[tuple[Role, str, float], BaseChatModel] = field(
        default_factory=dict, init=False, repr=False
    )
    _resources: ExitStack = field(default_factory=ExitStack, init=False, repr=False)
    _checkpointer: BaseCheckpointSaver[Any] | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.chaos_injector = ChaosInjector(self.settings.chaos)
        if self.llm_fault is None:
            self.llm_fault = self.chaos_injector.llm
        self.circuits = CircuitRegistry(self.settings.reliability.circuit)
        self.model_workers = BoundedExecutor(
            self.settings.reliability.llm_max_in_flight, thread_name_prefix="atlas-llm"
        )
        self._resources.callback(self.model_workers.close)
        self.models = ReliableModels(self)

    def primary_model_name(self, role: Role) -> str:
        name, _ = resolve_model(role, self.settings.llm)
        if name:
            return name
        return "injected" if self._injected_model(role) is not None else "unconfigured"

    def _injected_model(self, role: Role) -> BaseChatModel | None:
        return self.main_model if role == "main" else self.fast_model

    def model_for(
        self, role: Role, name: str, timeout_s: float, *, cache: bool = True
    ) -> BaseChatModel:
        if self._closed:
            raise RuntimeError("GraphDeps is closed")
        primary = name == self.primary_model_name(role)
        if primary and (injected := self._injected_model(role)) is not None:
            return injected
        key = (role, name, timeout_s)
        if cache and (cached := self._model_cache.get(key)) is not None:
            return cached
        model = get_chat_model(
            role, self.settings, model_name=None if primary else name, timeout_s=timeout_s
        )
        return self._model_cache.setdefault(key, model) if cache else model

    def model(self, role: Role = "fast") -> BaseChatModel:
        """Use the configured role model in standalone eval and tooling."""
        return self.model_for(role, self.primary_model_name(role), self.settings.llm.timeout_s)

    def checkpointer(self) -> BaseCheckpointSaver[Any]:
        if self._closed:
            raise RuntimeError("GraphDeps is closed")
        if self._checkpointer is None:
            if self.settings.graph.checkpoint_backend == "memory":
                self._checkpointer = InMemorySaver()
            elif self.settings.graph.checkpoint_backend == "postgres":
                self._checkpointer = self._resources.enter_context(postgres_saver(self.settings))
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

    def orders(self) -> OrderService:
        if self._closed:
            raise RuntimeError("GraphDeps is closed")
        if self.order_service is None:
            self.order_service = OrderService(platform=self.settings)
            self._resources.callback(self.order_service.close)
        return self.order_service

    @cached_property
    def dependency_guards(self) -> DependencyGuards:
        guards = DependencyGuards(
            self.settings, self.circuits, self.observer, self.chaos_injector.dependency
        )
        self._resources.callback(guards.close)
        return guards

    def guarded_orders(self) -> GuardedOrders:
        return GuardedOrders(self.orders, self.dependency_guards)

    def knowledge_retriever(self) -> Retriever:
        if self._closed:
            raise RuntimeError("GraphDeps is closed")
        if self.retriever is None:
            store = GuardedMilvusSearch(self.settings, self.dependency_guards)
            self._resources.callback(store.close)
            self.retriever = build_retriever(
                "hybrid_rerank",
                settings=self.settings,
                store=store,
                embedder=BgeM3Embedder(self.settings.retrieval),
                reranker=GuardedReranker(
                    lambda: BgeReranker(self.settings.retrieval), self.dependency_guards
                ),
            )
        return self.retriever

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
