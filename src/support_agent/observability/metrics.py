"""Low-cardinality metrics for graph calls and API responses."""

from collections.abc import Mapping
from typing import Any, get_args

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import choose_encoder

from support_agent.cache.metrics import CacheLayer, CacheOutcome
from support_agent.config import Settings
from support_agent.context.builder import ContextCallRecord
from support_agent.gate.evidence import GateResult
from support_agent.graph.handoff import HandoffPayload, HandoffReason
from support_agent.graph.intents import Path
from support_agent.guardrails.input import InputFlag
from support_agent.guardrails.output import OutputFlag
from support_agent.llm import Role, resolve_model
from support_agent.reliability.circuit import CircuitRegistry
from support_agent.reliability.llm_calls import CallSite

LLM_CALL_SITES = get_args(CallSite)
_INPUT_FLAGS = frozenset(get_args(InputFlag))
_CACHE_LAYERS = frozenset(get_args(CacheLayer))
_CACHE_OUTCOMES = frozenset(get_args(CacheOutcome))

ENDPOINTS = {
    "/": "index",
    "/api/chat": "chat",
    "/api/resume": "resume",
    "/api/session": "session",
    "/api/customers": "customers",
    "/api/feedback": "feedback",
    "/api/health": "health",
    "/api/health/live": "live",
    "/api/health/ready": "ready",
    "/metrics": "metrics",
}
OUTCOMES = frozenset({"success", "invalid", "conflict", "unavailable", "error"})
MODEL_OUTCOMES = frozenset({"success", "error"})
ROLES: tuple[Role, ...] = ("fast", "main")


class AtlasMetrics:
    def __init__(self, settings: Settings, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        self.models = {"injected", "unconfigured"}
        for role in ROLES:
            name, _ = resolve_model(role, settings.llm)
            if name:
                self.models.add(name)
            self.models.update(getattr(settings.llm.fallbacks, role))
        self.dependencies = {"milvus", "reranker", "orders_db"} | {
            f"llm:{model}" for model in self.models
        }
        self.paths = frozenset(path.value for path in Path)
        self.requests = Counter(
            "atlas_requests_total", "HTTP requests", ("endpoint", "outcome"), registry=self.registry
        )
        self.request_seconds = Histogram(
            "atlas_request_seconds",
            "HTTP request duration",
            ("endpoint",),
            registry=self.registry,
            buckets=settings.reliability.metrics.latency_buckets_s,
        )
        self.llm_calls = Counter(
            "atlas_llm_calls_total",
            "Model attempts",
            ("role", "model", "outcome"),
            registry=self.registry,
        )
        self.llm_seconds = Histogram(
            "atlas_llm_seconds",
            "Model attempt duration",
            ("role", "model"),
            registry=self.registry,
            buckets=settings.reliability.metrics.latency_buckets_s,
        )
        self.retries = Counter(
            "atlas_retries_total", "Retry attempts", ("dependency",), registry=self.registry
        )
        self.fallbacks = Counter(
            "atlas_fallbacks_total", "Model fallback calls", ("role",), registry=self.registry
        )
        self.repairs = Counter(
            "atlas_repairs_total",
            "Structured output repairs",
            ("call_site", "outcome"),
            registry=self.registry,
        )
        self.circuit = Gauge(
            "atlas_circuit_state",
            "Circuit state (0 closed, 1 half-open, 2 open)",
            ("dependency",),
            registry=self.registry,
        )
        self.handoffs = Counter(
            "atlas_handoffs_total", "Handoffs", ("reason",), registry=self.registry
        )
        self.gates = Counter(
            "atlas_gate_evaluations_total",
            "Evidence gate evaluations",
            ("passed",),
            registry=self.registry,
        )
        self.guardrail_flags = Counter(
            "atlas_guardrail_flags_total", "Guardrail flags", ("flag",), registry=self.registry
        )
        self.path = Counter("atlas_path_total", "Graph paths", ("path",), registry=self.registry)
        self.cache_requests = Counter(
            "atlas_cache_requests_total",
            "Cache lookups by layer and outcome",
            ("layer", "outcome"),
            registry=self.registry,
        )
        self.context_tokens = Counter(
            "atlas_context_tokens_total",
            "Context tokens per node and kind",
            ("node", "kind"),
            registry=self.registry,
        )
        self.feedback = Counter(
            "atlas_feedback_total",
            "Explicit customer feedback on AI answers",
            ("rating",),
            registry=self.registry,
        )
        self.drift = Gauge(
            "atlas_drift_metric",
            "Latest online drift signal value",
            ("metric",),
            registry=self.registry,
        )
        self.online_citations = Counter(
            "atlas_online_citation_valid_total",
            "Online automatic citation validity checks",
            ("valid",),
            registry=self.registry,
        )
        self.context_cache_hit_ratio = Gauge(
            "atlas_context_cache_hit_ratio",
            "Latest prompt-prefix cache hit ratio per node",
            ("node",),
            registry=self.registry,
        )
        self.context_overflows = Counter(
            "atlas_context_overflow_total",
            "Context budget overflows per node",
            ("node",),
            registry=self.registry,
        )

    def request(self, path: str, outcome: str, seconds: float, trace_id: str) -> None:
        endpoint = ENDPOINTS.get(path, "static" if path.startswith("/static/") else "other")
        exemplar = {"trace_id": trace_id}
        self.requests.labels(endpoint, outcome if outcome in OUTCOMES else "error").inc(
            exemplar=exemplar,
        )
        self.request_seconds.labels(endpoint).observe(seconds, exemplar=exemplar)

    def llm_attempt(self, role: Role, model: str, outcome: str, seconds: float) -> None:
        if role in ROLES and outcome in MODEL_OUTCOMES:
            model = model if model in self.models else "unconfigured"
            self.llm_calls.labels(role, model, outcome).inc()
            self.llm_seconds.labels(role, model).observe(seconds)

    def retry(self, dependency: str) -> None:
        if dependency in self.dependencies:
            self.retries.labels(dependency).inc()

    def fallback(self, role: Role) -> None:
        if role in ROLES:
            self.fallbacks.labels(role).inc()

    def repair(self, call_site: str, outcome: str) -> None:
        if call_site in LLM_CALL_SITES and outcome in MODEL_OUTCOMES:
            self.repairs.labels(call_site, outcome).inc()

    def cache_event(self, layer: CacheLayer, outcome: CacheOutcome) -> None:
        if layer in _CACHE_LAYERS and outcome in _CACHE_OUTCOMES:
            self.cache_requests.labels(layer, outcome).inc()

    def context_call(self, record: ContextCallRecord) -> None:
        node = record.node if record.node in LLM_CALL_SITES else "other"
        if record.input_tokens:
            self.context_tokens.labels(node, "input").inc(record.input_tokens)
        if record.cache_read_tokens:
            self.context_tokens.labels(node, "cache_read").inc(record.cache_read_tokens)
        if record.cache_write_tokens:
            self.context_tokens.labels(node, "cache_write").inc(record.cache_write_tokens)
        self.context_cache_hit_ratio.labels(node).set(record.cache_hit_ratio)

    def context_overflow(self, node: str) -> None:
        label = node if node in LLM_CALL_SITES else "other"
        self.context_overflows.labels(label).inc()

    def handoff(self, reason: HandoffReason) -> None:
        self.handoffs.labels(reason.value).inc()

    def record_feedback(self, rating: str) -> None:
        if rating in {"up", "down"}:
            self.feedback.labels(rating).inc()

    def drift_metric(self, name: str, value: float) -> None:
        self.drift.labels(name).set(value)

    def citation_check(self, valid: bool) -> None:
        self.online_citations.labels(str(valid).lower()).inc()

    def graph_update(self, update: Mapping[str, Any], *, publish_handoff: bool = True) -> None:
        if (output_flag := update.get("output_guard_flag")) in get_args(OutputFlag):
            self.guardrail_flags.labels(output_flag).inc()
        for flag in update.get("guardrail_flags", []):
            if not output_flag and flag in _INPUT_FLAGS:
                self.guardrail_flags.labels(flag).inc()
        if isinstance(gate := update.get("gate"), GateResult):
            self.gates.labels(str(gate.passed).lower()).inc()
        if publish_handoff and isinstance(handoff := update.get("handoff"), HandoffPayload):
            self.handoff(handoff.reason)
        if isinstance(path := update.get("path"), str) and path in self.paths:
            self.path.labels(path).inc()

    def render(self, circuits: CircuitRegistry, accept: str) -> tuple[bytes, str]:
        for name in self.dependencies:
            self.circuit.labels(name).set(circuits.state(name).value)
        encode, content_type = choose_encoder(accept)
        return encode(self.registry), content_type
