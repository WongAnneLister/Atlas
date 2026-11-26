"""Offline unit tests for versioned three-layer caching."""

from __future__ import annotations

from datetime import date
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

from support_agent.cache.eligibility import (
    answer_cache_lookup_eligibility,
    answer_cache_write_eligibility,
)
from support_agent.cache.keys import (
    answer_cache_key,
    build_revision,
    embedding_cache_key,
    prompt_version_hash,
    retrieval_cache_key,
    retrieval_config_hash,
)
from support_agent.cache.layers import (
    AnswerCache,
    CachedAnswer,
    CachedEmbedder,
    CachedRetriever,
    bump_index_revision,
)
from support_agent.cache.settings import CacheSettings
from support_agent.config import Settings, get_settings
from support_agent.gate.evidence import GateResult
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS
from support_agent.graph.intents import Intent, Path
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.grounding.claims import ClaimAssessment
from support_agent.infra.redis import NullRedis
from support_agent.memory.short_term.compaction import SummaryBlock
from support_agent.observability.metrics import AtlasMetrics
from support_agent.retrieval.embed import FakeEmbedder
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk


class BrokenRedis(NullRedis):
    def get(self, key: str) -> str | None:
        raise ConnectionError("redis down")

    def set(self, key: str, value: str, ttl_s: int) -> None:
        raise ConnectionError("redis down")

    def incr(self, key: str, ttl_s: int) -> int:
        raise ConnectionError("redis down")


class CountingEmbedder:
    def __init__(self, dim: int = 8) -> None:
        self.inner = FakeEmbedder(dim)
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return self.inner.embed(texts)


class StaticVectorEmbedder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.vectors[text] for text in texts]


class CountingRetriever:
    def __init__(self, chunks_by_build: dict[str, list[RetrievedChunk]], build_ref: list[str]):
        self.chunks_by_build = chunks_by_build
        self.build_ref = build_ref
        self.calls: list[tuple[str, int, RetrievalFilters | None]] = []

    def supports_filters(self) -> bool:
        return True

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        self.calls.append((query, top_k, filters))
        return list(self.chunks_by_build[self.build_ref[0]][:top_k])


class StructuredFake(FakeListChatModel):
    payloads: list[dict[str, Any]]
    calls: int = 0

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        def invoke(_: Any) -> dict[str, Any]:
            self.calls += 1
            index = min(self.calls - 1, len(self.payloads) - 1)
            return {
                "parsed": schema.model_validate(self.payloads[index]),
                "raw": None,
                "parsing_error": None,
            }

        return RunnableLambda(invoke)


def _chunk(chunk_id: str, text: str, score: float = 0.92) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="returns",
        title="Returns",
        section_id="returns.maktek_faqs.window",
        heading_path="Returns > Return Window",
        text=text,
        n_tokens=len(text.split()),
        scores={"rerank": score, "rerank_logit": 2.4},
        ranks={"rerank": 1},
    )


def _settings(dim: int = 8) -> Settings:
    settings = get_settings().model_copy(deep=True)
    settings.retrieval.embedding_dim = dim
    settings.planning.enabled = False
    settings.grounding.enabled = True
    settings.cache.enabled = True
    return settings


def _passed_gate() -> GateResult:
    return GateResult(
        passed=True,
        score=0.85,
        threshold=0.15,
        signals={"top_score": 0.92, "good_count": 1.0, "margin": 0.4, "key_hit": 1.0},
        reason="passed",
    )


def test_key_builders_include_all_version_dimensions() -> None:
    settings = _settings()
    r = settings.retrieval
    f1 = RetrievalFilters(as_of=date(2026, 11, 9), product_category="hair_dryers")
    f2 = RetrievalFilters(as_of=date(2026, 8, 1), product_category="hair_dryers")

    # Embedding key: whitespace-normalised, sensitive to model/revision/text.
    assert embedding_cache_key("p", r, "return   policy") == embedding_cache_key(
        "p", r, " return policy "
    )
    r_other = r.model_copy(update={"embedding_revision": "other-rev"})
    assert embedding_cache_key("p", r, "return policy") != embedding_cache_key(
        "p", r_other, "return policy"
    )

    # Retrieval key: sensitive to filters, build revision, top_k, and retrieval config.
    cfg_hash = retrieval_config_hash(r)
    k1 = retrieval_cache_key("p", "Return policy?", f1, 5, "build-a", cfg_hash)
    assert k1 == retrieval_cache_key("p", "  return   policy ", f1, 5, "build-a", cfg_hash)
    assert k1 != retrieval_cache_key("p", "Return policy?", f2, 5, "build-a", cfg_hash)
    assert k1 != retrieval_cache_key("p", "Return policy?", f1, 5, "build-b", cfg_hash)
    assert k1 != retrieval_cache_key("p", "Return policy?", f1, 10, "build-a", cfg_hash)
    assert k1 != retrieval_cache_key("p", "Return policy?", f1, 5, "build-a", "other-cfg")

    # Answer key: sensitive to build revision, filters, prompt version, and models.
    pv = prompt_version_hash(PROMPTS, settings)
    ak1 = answer_cache_key("p", "Return policy?", f1, "build-a", pv, {"main": "m1"})
    assert ak1 != answer_cache_key("p", "Return policy?", f2, "build-a", pv, {"main": "m1"})
    assert ak1 != answer_cache_key("p", "Return policy?", f1, "build-b", pv, {"main": "m1"})
    assert ak1 != answer_cache_key("p", "Return policy?", f1, "build-a", "other-pv", {"main": "m1"})
    assert ak1 != answer_cache_key("p", "Return policy?", f1, "build-a", pv, {"main": "m2"})

    assert build_revision(None) is None
    assert build_revision("abc") == "abc"
    assert build_revision("abc", "2") == "abc:r2"


def test_answer_cache_eligibility_rules() -> None:
    cfg = CacheSettings(enabled=True)
    base = ConversationState(
        messages=[HumanMessage(content="What is the return window?")],
        rewritten_query="What is the return window?",
        intent=Intent.POLICY_QUESTION,
        path=Path.KNOWLEDGE,
        route_source="whole",
        retrieval=[_chunk("c1", "Returns within 30 days.")],
        retrieval_build_id="build-1",
        gate=_passed_gate(),
        answer="Returns are accepted within 30 days [1].",
        citations=[CitationRecord(n=1, chunk_id="c1", section_id="s1", heading_path="Returns")],
        claims=[
            ClaimAssessment(
                part=0,
                text="Returns within 30 days.",
                verdict="supported",
                reason="ok",
                removed=False,
            )
        ],
        answer_status="answered",
    )
    assert answer_cache_lookup_eligibility(base, cfg) == (True, "eligible")
    assert answer_cache_write_eligibility(base, cfg, grounding_enabled=True) == (True, "eligible")

    ineligible_cases = [
        base.model_copy(update={"path": Path.TOOLS, "intent": Intent.ORDER_STATUS}),
        base.model_copy(update={"path": Path.AFTER_SALES, "intent": Intent.REFUND_REQUEST}),
        base.model_copy(update={"fallback_to_knowledge": True}),
        base.model_copy(update={"route_source": "parts"}),
        base.model_copy(update={"guardrail_flags": ["direct_injection"]}),
        base.model_copy(update={"input_guard_action": "allow_flagged"}),
        base.model_copy(update={"order_context": {"order_id": "ORD-000001"}}),
        base.model_copy(update={"refund_order_id": "ORD-000001"}),
        base.model_copy(update={"rewritten_query": "Can I return ORD-000065?"}),
        base.model_copy(update={"rewritten_query": "Email me at user@example.com about returns"}),
        base.model_copy(
            update={
                "messages": [
                    HumanMessage(content="Check ORD-000065"),
                    ToolMessage(content='{"status":"delivered"}', tool_call_id="t1"),
                    HumanMessage(content="What is the return window?"),
                ]
            }
        ),
    ]
    # Context the answer prompt sees but the cache key omits.
    ineligible_cases += [
        base.model_copy(update={"customer_profile": "Owns a Philips W40."}),
        base.model_copy(update={"turn_memory_hints": ["Prefers email updates."]}),
        base.model_copy(
            update={
                "messages": [
                    HumanMessage(content="I bought it last week."),
                    HumanMessage(content="What is the return window?"),
                ]
            }
        ),
        base.model_copy(
            update={
                "compacted_blocks": [
                    SummaryBlock(
                        block_id="b1", turns=(1, 6), text="Earlier chat.", created_at_turn=7
                    )
                ]
            }
        ),
    ]
    for case in ineligible_cases:
        ok, _ = answer_cache_lookup_eligibility(case, cfg)
        assert not ok
        write_ok, _ = answer_cache_write_eligibility(case, cfg, grounding_enabled=True)
        assert not write_ok

    # Write-only rejections
    assert not answer_cache_write_eligibility(
        base.model_copy(update={"claims": None}), cfg, grounding_enabled=True
    )[0]
    assert not answer_cache_write_eligibility(
        base.model_copy(update={"retrieval_build_id": None}), cfg, grounding_enabled=True
    )[0]
    assert not answer_cache_write_eligibility(
        base.model_copy(update={"output_guard_flag": "foreign_pii"}), cfg, grounding_enabled=True
    )[0]


def test_embedding_cache_hit_miss_and_redis_down() -> None:
    settings = _settings(dim=8)
    inner = CountingEmbedder(dim=8)
    store = NullRedis()
    metrics = AtlasMetrics(settings)
    cached = CachedEmbedder(inner, store, settings.retrieval, settings.cache, observer=metrics)

    first = cached.embed(["Return policy", "Shipping policy"])
    second = cached.embed(["Return   policy", "Warranty policy"])

    assert first == inner.inner.embed(["Return policy", "Shipping policy"])
    assert second == inner.inner.embed(["Return policy", "Warranty policy"])
    assert len(inner.calls) == 2
    assert inner.calls[0] == ["Return policy", "Shipping policy"]
    assert inner.calls[1] == ["Warranty policy"]

    # Redis down -> bypass without error
    broken_cached = CachedEmbedder(
        inner, BrokenRedis(), settings.retrieval, settings.cache, observer=metrics
    )
    assert broken_cached.embed(["Return policy"]) == inner.inner.embed(["Return policy"])
    rendered, _ = metrics.render(GraphDeps(settings=settings).circuits, "text/plain")
    text = rendered.decode("utf-8")
    assert 'atlas_cache_requests_total{layer="embedding",outcome="hit"} 1.0' in text
    assert 'atlas_cache_requests_total{layer="embedding",outcome="error"}' in text


def test_retrieval_cache_invalidation_and_redis_down() -> None:
    settings = _settings()
    store = NullRedis()
    build = ["build-1"]
    chunks = {
        "build-1": [_chunk("c1", "Returns within 30 days.")],
        "build-2": [_chunk("c2", "Returns within 45 days.")],
    }
    inner = CountingRetriever(chunks, build)
    cached = CachedRetriever(inner, store, lambda: build[0], settings.retrieval, settings.cache)
    f = RetrievalFilters(as_of=date(2026, 11, 9))

    out1 = cached.retrieve("Return window?", 5, filters=f)
    out2 = cached.retrieve("return window", 5, filters=f)
    assert out1 == out2
    assert len(inner.calls) == 1

    # Bump Redis index revision -> immediate invalidation even before build_id changes.
    bump_index_revision(store, settings.cache)
    cached.retrieve("Return window?", 5, filters=f)
    assert len(inner.calls) == 2

    # Switch build_id -> immediate miss and new chunks.
    build[0] = "build-2"
    out3 = cached.retrieve("Return window?", 5, filters=f)
    assert out3[0].chunk_id == "c2"
    assert len(inner.calls) == 3

    # Missing build_id -> bypass, never cached.
    no_build = CachedRetriever(inner, store, lambda: None, settings.retrieval, settings.cache)
    no_build.retrieve("Return window?", 5, filters=f)
    no_build.retrieve("Return window?", 5, filters=f)
    assert len(inner.calls) == 5

    # Redis down -> bypass without failing.
    broken = CachedRetriever(
        inner, BrokenRedis(), lambda: build[0], settings.retrieval, settings.cache
    )
    assert broken.retrieve("Return window?", 5, filters=f)[0].chunk_id == "c2"


def test_answer_cache_near_duplicate_respects_flag_and_bucket() -> None:
    settings = _settings(dim=3)
    settings.cache.answer.near_duplicate.enabled = True
    settings.cache.answer.near_duplicate.similarity_threshold = 0.95
    store = NullRedis()
    embedder = StaticVectorEmbedder(
        {
            "what is the return window": [1.0, 0.0, 0.0],
            "how many days for returns": [0.99, 0.14, 0.0],  # cosine ~0.99
            "what is the shipping cost": [0.0, 1.0, 0.0],  # cosine 0.0
        }
    )
    cache = AnswerCache(store, settings.cache, embedder=embedder)
    f = RetrievalFilters(as_of=date(2026, 11, 9))
    entry = CachedAnswer(
        answer="Returns within 30 days [1].",
        citations=[CitationRecord(n=1, chunk_id="c1", section_id="s1", heading_path="Returns")],
        retrieval=[_chunk("c1", "Returns within 30 days.")],
        gate=_passed_gate(),
        retrieval_build_id="build-1",
    )
    assert cache.set(
        query="What is the return window?",
        filters=f,
        build_id="build-1",
        prompt_version="pv1",
        models={"main": "m1"},
        entry=entry,
    )

    hit, layer = cache.get(
        query="How many days for returns?",
        filters=f,
        build_id="build-1",
        prompt_version="pv1",
        models={"main": "m1"},
    )
    assert hit is not None and layer == "answer_semantic"
    assert hit.answer == entry.answer

    # Unrelated query misses.
    miss, _ = cache.get(
        query="What is the shipping cost?",
        filters=f,
        build_id="build-1",
        prompt_version="pv1",
        models={"main": "m1"},
    )
    assert miss is None

    # Different build_id -> different bucket -> misses.
    miss_build, _ = cache.get(
        query="How many days for returns?",
        filters=f,
        build_id="build-2",
        prompt_version="pv1",
        models={"main": "m1"},
    )
    assert miss_build is None


def test_graph_end_to_end_caching_staleness_isolation_and_redis_down() -> None:
    settings = _settings()
    settings.grounding.enabled = False
    store = NullRedis()
    build = ["build-30"]
    chunks = {
        "build-30": [_chunk("c30", "Generic store returns are accepted within 30 days.")],
        "build-45": [_chunk("c45", "Generic store returns are accepted within 45 days.")],
    }
    retriever = CountingRetriever(chunks, build)

    classify_payload = {"intent": "policy_question", "confidence": 0.99}
    answer_30 = {
        "parts": [
            {
                "question": "What is the return window?",
                "supported": True,
                "explicit": True,
                "answer": "Returns are accepted within 30 days.",
                "evidence": [{"source": 1, "quote": "returns are accepted within 30 days"}],
            }
        ]
    }
    answer_45 = {
        "parts": [
            {
                "question": "What is the return window?",
                "supported": True,
                "explicit": True,
                "answer": "Returns are accepted within 45 days.",
                "evidence": [{"source": 1, "quote": "returns are accepted within 45 days"}],
            }
        ]
    }

    fast_model = StructuredFake(responses=["ok"], payloads=[classify_payload])
    main_model = StructuredFake(responses=["ok"], payloads=[answer_30, answer_45])
    deps = GraphDeps(
        settings=settings,
        fast_model=fast_model,
        main_model=main_model,
        retriever=retriever,
        cache_store=store,
        build_id_provider=lambda: build[0],
        allow_untuned_gate=True,
    )
    graph = build_graph(deps)

    # 1. Cold miss populates cache.
    r1 = graph.invoke(
        {
            "messages": [HumanMessage(content="What is the return window?")],
            "customer_id": "CUST-0001",
        },
        {"configurable": {"thread_id": "t1"}},
    )
    assert r1["answer_status"] == "answered"
    assert "30 days" in r1["answer"]
    assert r1["answer_cache_hit"] is None
    assert r1["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "answer",
        "output_guard",
    ]
    assert len(retriever.calls) == 1
    assert main_model.calls == 1

    # 2. Second identical question hits Layer 3 answer cache (0 extra retriever/main calls).
    r2 = graph.invoke(
        {
            "messages": [HumanMessage(content="What is the return window?")],
            "customer_id": "CUST-0002",
        },
        {"configurable": {"thread_id": "t2"}},
    )
    assert r2["answer"] == r1["answer"]
    assert r2["citations"] == r1["citations"]
    assert r2["answer_cache_hit"] == "answer"
    assert r2["trace"] == ["input_guard", "rewrite", "classify", "retrieve", "output_guard"]
    assert len(retriever.calls) == 1
    assert main_model.calls == 1

    # 3. Staleness: new build_id invalidates cache and serves 45 days.
    build[0] = "build-45"
    r3 = graph.invoke(
        {
            "messages": [HumanMessage(content="What is the return window?")],
            "customer_id": "CUST-0003",
        },
        {"configurable": {"thread_id": "t3"}},
    )
    assert "45 days" in r3["answer"]
    assert r3["answer_cache_hit"] is None
    assert len(retriever.calls) == 2
    assert main_model.calls == 2

    # 4. Isolation: customer A with order context bypasses answer cache completely.
    r4 = graph.invoke(
        {
            "messages": [HumanMessage(content="What is the return window for ORD-000065?")],
            "customer_id": "CUST-0001",
            "order_context": {"order_id": "ORD-000065", "canary": "SECRET-CANARY-A"},
        },
        {"configurable": {"thread_id": "t4"}},
    )
    assert r4["answer_cache_hit"] is None
    assert any(ev.layer == "answer" and ev.outcome == "bypass" for ev in r4["cache_events"])
    deps.close()


def test_graph_answer_cache_never_serves_one_customers_memory_to_another() -> None:
    settings = _settings()
    settings.grounding.enabled = False
    retriever = CountingRetriever(
        {"b1": [_chunk("c1", "Generic store returns are accepted within 30 days.")]}, ["b1"]
    )

    def answer(text: str) -> dict[str, Any]:
        quote = "returns are accepted within 30 days"
        return {
            "parts": [
                {
                    "question": "What is the return window?",
                    "supported": True,
                    "explicit": True,
                    "answer": text,
                    "evidence": [{"source": 1, "quote": quote}],
                }
            ]
        }

    # Customer A's answer is shaped by A's long-term memory (the canary).
    main_model = StructuredFake(
        responses=["ok"],
        payloads=[
            answer("Returns are accepted within 30 days, CANARY-A."),
            answer("Returns are accepted within 30 days."),
        ],
    )
    deps = GraphDeps(
        settings=settings,
        fast_model=StructuredFake(
            responses=["ok"], payloads=[{"intent": "policy_question", "confidence": 0.99}]
        ),
        main_model=main_model,
        retriever=retriever,
        cache_store=NullRedis(),
        build_id_provider=lambda: "b1",
        allow_untuned_gate=True,
    )
    graph = build_graph(deps)
    question = [HumanMessage(content="What is the return window?")]
    a = graph.invoke(
        {
            "messages": question,
            "customer_id": "CUST-0001",
            "customer_profile": "CANARY-A owns a Philips W40.",
            "customer_profile_loaded": True,
        },
        {"configurable": {"thread_id": "a"}},
    )
    b = graph.invoke(
        {"messages": question, "customer_id": "CUST-0002"},
        {"configurable": {"thread_id": "b"}},
    )
    assert "CANARY-A" in a["answer"]
    assert "CANARY-A" not in b["answer"]
    assert b["answer_cache_hit"] is None
    assert main_model.calls == 2
    deps.close()


def test_graph_miss_path_matches_no_cache_path_and_handles_redis_down() -> None:
    def _run(cache_enabled: bool, store: Any) -> dict[str, Any]:
        settings = _settings()
        settings.grounding.enabled = False
        settings.cache.enabled = cache_enabled
        build = ["build-1"]
        retriever = CountingRetriever(
            {"build-1": [_chunk("c1", "Generic store returns are accepted within 30 days.")]},
            build,
        )
        fast = StructuredFake(
            responses=["ok"], payloads=[{"intent": "policy_question", "confidence": 0.99}]
        )
        main = StructuredFake(
            responses=["ok"],
            payloads=[
                {
                    "parts": [
                        {
                            "question": "What is the return window?",
                            "supported": True,
                            "explicit": True,
                            "answer": "Returns are accepted within 30 days.",
                            "evidence": [
                                {"source": 1, "quote": "returns are accepted within 30 days"}
                            ],
                        }
                    ]
                }
            ],
        )
        deps = GraphDeps(
            settings=settings,
            fast_model=fast,
            main_model=main,
            retriever=retriever,
            cache_store=store,
            build_id_provider=lambda: build[0],
            allow_untuned_gate=True,
        )
        try:
            graph = build_graph(deps)
            return graph.invoke(
                {
                    "messages": [HumanMessage(content="What is the return window?")],
                    "customer_id": "CUST-0001",
                },
                {"configurable": {"thread_id": "t-same"}},
            )
        finally:
            deps.close()

    no_cache = _run(False, None)
    miss_cache = _run(True, NullRedis())
    broken_redis = _run(True, BrokenRedis())

    for result in (miss_cache, broken_redis):
        assert result["answer"] == no_cache["answer"]
        assert result["citations"] == no_cache["citations"]
        assert result["trace"] == no_cache["trace"]
        assert result["answer_status"] == no_cache["answer_status"]
        assert result["gate"] == no_cache["gate"]


def test_cache_eval_harness_offline() -> None:
    from eval.cache_eval import (
        evaluate_isolation,
        evaluate_near_duplicate_pairs,
        evaluate_replay,
        evaluate_staleness,
        load_contrast_pairs,
        render_report,
    )

    pairs = load_contrast_pairs()
    assert len(pairs) >= 20
    near_dup = evaluate_near_duplicate_pairs(FakeEmbedder(16), pairs, configured_threshold=0.97)
    assert near_dup["total"] == len(pairs)

    settings = _settings()
    settings.grounding.enabled = False
    store = NullRedis()
    build = ["build-1"]
    chunks = {
        "build-1": [_chunk("c1", "Generic store returns are accepted within 30 days.")],
        "build-2": [_chunk("c2", "Generic store returns are accepted within 45 days.")],
    }
    retriever = CountingRetriever(chunks, build)
    fast = StructuredFake(
        responses=["ok"], payloads=[{"intent": "policy_question", "confidence": 0.99}]
    )
    main = StructuredFake(
        responses=["ok"],
        payloads=[
            {
                "parts": [
                    {
                        "question": "What is the return window?",
                        "supported": True,
                        "explicit": True,
                        "answer": "Returns are accepted within 30 days.",
                        "evidence": [{"source": 1, "quote": "returns are accepted within 30 days"}],
                    }
                ]
            },
            {
                "parts": [
                    {
                        "question": "What is the return window?",
                        "supported": True,
                        "explicit": True,
                        "answer": "Returns are accepted within 45 days.",
                        "evidence": [{"source": 1, "quote": "returns are accepted within 45 days"}],
                    }
                ]
            },
        ],
    )
    deps = GraphDeps(
        settings=settings,
        fast_model=fast,
        main_model=main,
        retriever=retriever,
        cache_store=store,
        build_id_provider=lambda: build[0],
        allow_untuned_gate=True,
    )
    try:
        graph = build_graph(deps)
        replay = evaluate_replay(graph, [("q1", "What is the return window?")], "CUST-0001")
        assert replay["pass2_answer_hits"] == 1
        assert replay["mismatches_on_hit"] == []

        staleness = evaluate_staleness(
            graph,
            store,
            settings,
            "What is the return window?",
            "CUST-0001",
            bump_build=lambda: build.__setitem__(0, "build-2"),
        )
        assert staleness["passed"] is True

        isolation = evaluate_isolation(graph, "What is the return window?")
        assert isolation["passed"] is True
    finally:
        deps.close()

    md = render_report(
        settings,
        mode="offline-fixture",
        eval_file="fixture",
        replay=replay,
        staleness=staleness,
        isolation=isolation,
        near_duplicate=near_dup,
    )
    assert "Cache correctness and efficiency report" in md
    assert "PASS" in md
