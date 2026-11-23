"""Offline unit tests for governed long-term customer memory (Commit 30)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from support_agent.api.app import create_app
from support_agent.api.deps import ApiDeps
from support_agent.config import get_settings
from support_agent.context.builder import ContextBuilder
from support_agent.graph.deps import GraphDeps
from support_agent.graph.nodes.rewrite import make_rewrite_node
from support_agent.graph.state import ConversationState
from support_agent.memory.long_term.models import MemoryCandidate
from support_agent.memory.long_term.policy import apply_write_policy, evaluate_candidate
from support_agent.memory.long_term.reader import (
    format_turn_memory_messages,
    load_session_profile,
    lookup_turn_memories,
)
from support_agent.memory.long_term.store import CustomerMemoryStore, CustomerScopeError
from support_agent.memory.settings import LongTermMemorySettings
from support_agent.orders.models import CustomerSummary
from support_agent.retrieval.types import RetrievedChunk


def _store() -> CustomerMemoryStore:
    return CustomerMemoryStore.from_sqlite_path(":memory:")


def test_write_policy_rules_pii_redaction_and_ttl() -> None:
    cfg = LongTermMemorySettings(enabled=True)
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    # Disallowed kind
    bad_kind = evaluate_candidate(
        MemoryCandidate(kind="random_note", content="Customer likes coffee", confidence=0.95),
        [],
        cfg,
        now=now,
    )
    assert not bad_kind.accepted and bad_kind.reason == "disallowed_kind"

    # Low confidence
    low_conf = evaluate_candidate(
        MemoryCandidate(kind="preference", content="Prefers email updates", confidence=0.4),
        [],
        cfg,
        now=now,
    )
    assert not low_conf.accepted and low_conf.reason == "low_confidence"

    # Payment data rejected (keyword and Luhn card number)
    pay_kw = evaluate_candidate(
        MemoryCandidate(kind="open_issue", content="Credit card CVV 123 failed", confidence=0.95),
        [],
        cfg,
        now=now,
    )
    assert not pay_kw.accepted and pay_kw.reason == "payment_data"

    # Third-party personal data rejected
    third_party = evaluate_candidate(
        MemoryCandidate(
            kind="open_issue",
            content="My wife Jane at jane@example.com ordered a dryer",
            confidence=0.95,
        ),
        [],
        cfg,
        now=now,
    )
    assert not third_party.accepted and third_party.reason == "third_party_personal_data"

    # Free-text over max_content_chars rejected
    too_long = evaluate_candidate(
        MemoryCandidate(kind="open_issue", content="x" * 300, confidence=0.95),
        [],
        cfg,
        now=now,
    )
    assert not too_long.accepted and too_long.reason == "content_too_long"

    # Valid memory: PII redacted and TTL set per kind
    good_pref = evaluate_candidate(
        MemoryCandidate(
            kind="preference",
            content="Prefers contact via alice@example.com in Spanish",
            structured={"subject": "contact_language", "note": "555-123-4567"},
            confidence=0.9,
        ),
        [],
        cfg,
        now=now,
    )
    assert good_pref.accepted and good_pref.action == "insert"
    assert "[EMAIL]" in good_pref.redacted_content
    assert "alice@example.com" not in good_pref.redacted_content
    assert good_pref.redacted_structured["note"] == "[PHONE]"
    assert good_pref.expires_at == now + timedelta(days=cfg.ttl_days["preference"])

    good_issue = evaluate_candidate(
        MemoryCandidate(
            kind="open_issue",
            content="Philips BHD340/10 hair dryer overheats after 2 minutes",
            confidence=0.88,
        ),
        [],
        cfg,
        now=now,
    )
    assert good_issue.accepted
    assert good_issue.expires_at == now + timedelta(days=cfg.ttl_days["open_issue"])


def test_supersede_refresh_and_idempotency() -> None:
    store = _store()
    cfg = LongTermMemorySettings(enabled=True)
    t1 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)

    # First insert
    res1 = apply_write_policy(
        store,
        "CUST-0001",
        [
            MemoryCandidate(
                kind="preference",
                content="Prefers email updates in French",
                structured={"subject": "contact_language"},
                confidence=0.9,
            )
        ],
        conversation_id="conv-1",
        settings=cfg,
        now=t1,
    )
    assert res1[0][0].action == "insert"
    first = res1[0][1]
    assert first is not None

    # Exact duplicate refreshes last_used_at instead of inserting a second row
    res2 = apply_write_policy(
        store,
        "CUST-0001",
        [
            MemoryCandidate(
                kind="preference",
                content="Prefers email updates in French",
                structured={"subject": "contact_language"},
                confidence=0.9,
            )
        ],
        conversation_id="conv-2",
        settings=cfg,
        now=t2,
    )
    assert res2[0][0].action == "refresh"
    active = store.list_active("CUST-0001", now=t2)
    assert len(active) == 1
    assert active[0].id == first.id
    assert active[0].last_used_at == t2

    # Same subject with updated value supersedes the old memory
    t3 = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
    res3 = apply_write_policy(
        store,
        "CUST-0001",
        [
            MemoryCandidate(
                kind="preference",
                content="Prefers phone updates in English",
                structured={"subject": "contact_language"},
                confidence=0.95,
            )
        ],
        conversation_id="conv-3",
        settings=cfg,
        now=t3,
    )
    assert res3[0][0].action == "supersede"
    active_after = store.list_active("CUST-0001", now=t3)
    assert len(active_after) == 1
    assert "English" in active_after[0].content
    old_row = store.get("CUST-0001", first.id)
    assert old_row is not None and old_row.superseded_by == active_after[0].id
    store.close()


def test_repository_guard_and_cross_customer_isolation() -> None:
    store = _store()
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    # Missing, blank, wildcard, or non-string customer_id must raise CustomerScopeError
    for bad in ("", "   ", "*", "%", "CUST-*", None):
        with pytest.raises(CustomerScopeError):
            store.list_active(bad, now=now)  # type: ignore[arg-type]

    mem_a = store.insert(
        "CUST-A",
        kind="product_owned",
        content="Owns CANARY-SECRET-A123",
        structured={},
        source_conversation_id="c1",
        source_turn=1,
        expires_at=now + timedelta(days=30),
        confidence=0.9,
        now=now,
    )
    # Customer B cannot read, get, refresh, or delete Customer A's memory
    assert store.list_active("CUST-B", now=now) == []
    assert store.get("CUST-B", mem_a.id) is None
    assert not store.soft_delete("CUST-B", mem_a.id, now=now)
    assert store.soft_delete_all("CUST-B", now=now) == 0
    assert len(store.list_active("CUST-A", now=now)) == 1
    store.close()


def test_deleted_and_expired_memories_never_returned() -> None:
    store = _store()
    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    m_live = store.insert(
        "CUST-0002",
        kind="product_owned",
        content="Owns Philips BHD340/10 hair dryer",
        structured={},
        source_conversation_id="c1",
        source_turn=1,
        expires_at=t0 + timedelta(days=30),
        confidence=0.9,
        now=t0,
    )
    m_expiring = store.insert(
        "CUST-0002",
        kind="open_issue",
        content="Delayed parcel for ORD-000010",
        structured={},
        source_conversation_id="c1",
        source_turn=1,
        expires_at=t0 + timedelta(days=5),
        confidence=0.9,
        now=t0,
    )
    assert len(store.list_active("CUST-0002", now=t0 + timedelta(days=1))) == 2
    # After 6 days, m_expiring is expired and ignored
    after_expiry = store.list_active("CUST-0002", now=t0 + timedelta(days=6))
    assert [m.id for m in after_expiry] == [m_live.id]

    # Soft-deleting m_live removes it immediately
    assert store.soft_delete("CUST-0002", m_live.id, now=t0 + timedelta(days=6))
    assert store.list_active("CUST-0002", now=t0 + timedelta(days=6)) == []
    assert store.get("CUST-0002", m_live.id) is None
    assert m_expiring.id != m_live.id
    store.close()


def test_gate_ignores_memory_content() -> None:
    settings = get_settings().model_copy(deep=True)
    settings.memory.long_term.enabled = True
    # Strong memory mentioning the exact answer, paired with weak retrieval -> still fails gate!
    weak_chunks = [
        RetrievedChunk(
            chunk_id=f"c{i}",
            doc_id="d1",
            section_id="s1",
            title="General FAQ",
            heading_path="General > FAQ",
            text="Unrelated shipping info",
            n_tokens=10,
            dense_score=0.05,
            bm25_score=0.0,
            rrf_score=0.01,
            rerank_score=-6.0,
            source_rank=i,
        )
        for i in (1, 2)
    ]
    from support_agent.graph.nodes.knowledge import KnowledgePath, route_after_gate

    deps = GraphDeps(settings=settings)
    kp = KnowledgePath(deps)
    state = ConversationState(
        customer_id="CUST-0001",
        rewritten_query="Can I buy gold bars on Flipkart?",
        customer_profile=(
            "On 2026-10-01 (past_resolution): Flipkart sells gold bars with 30-day return."
        ),
        retrieval=weak_chunks,
    )
    out = kp.gate(state)
    state.gate = out["gate"]
    assert state.gate is not None
    assert not state.gate.passed
    assert route_after_gate(state) == "handoff"
    deps.close()


def test_l1_bytes_identical_across_turns_even_with_mid_turn_l4_lookup() -> None:
    store = _store()
    settings = get_settings()
    lt_cfg = LongTermMemorySettings(
        enabled=True,
        session_top_k=1,
        mid_turn_top_k=2,
        mid_turn_min_relevance=0.25,
    )
    now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

    store.insert(
        "CUST-0003",
        kind="product_owned",
        content="Owns Philips BHD340/10 hair dryer",
        structured={"subject": "BHD340/10"},
        source_conversation_id="prev-1",
        source_turn=1,
        expires_at=now + timedelta(days=100),
        confidence=0.95,
        now=now - timedelta(days=2),
    )
    store.insert(
        "CUST-0003",
        kind="preference",
        content="Prefers warranty updates in Spanish email",
        structured={"subject": "warranty_language"},
        source_conversation_id="prev-2",
        source_turn=1,
        expires_at=now + timedelta(days=100),
        confidence=0.92,
        now=now - timedelta(days=3),
    )

    # Turn 1 loads top-1 into L1_session and freezes it
    profile_t1, loaded_ids = load_session_profile(
        store, "CUST-0003", "My Philips BHD340/10 dryer is loud", lt_cfg, now=now
    )
    assert profile_t1 is not None
    assert len(loaded_ids) == 1

    # Turn 2 asks about warranty updates -> mid-turn lookup returns the second memory for L4_turn
    l4_hints_t2 = lookup_turn_memories(
        store,
        "CUST-0003",
        "Send my warranty updates in Spanish",
        already_loaded_ids=loaded_ids,
        settings=lt_cfg,
        now=now,
    )
    assert len(l4_hints_t2) == 1
    assert "Spanish" in l4_hints_t2[0]

    # Build Turn 1 and Turn 2 contexts; L0+L1 message bytes must remain identical!
    builder = ContextBuilder(settings.context)
    ctx_t1 = builder.build(
        "answer",
        task_prompt="Answer using sources.",
        user_text="My Philips BHD340/10 dryer is loud",
        customer_profile=profile_t1,
    )
    ctx_t2 = builder.build(
        "answer",
        task_prompt="Answer using sources.",
        user_text="Send my warranty updates in Spanish",
        history=[
            HumanMessage(content="My Philips BHD340/10 dryer is loud"),
            AIMessage(content="Let me check the manual."),
        ],
        customer_profile=profile_t1,
        extra_l4_messages=format_turn_memory_messages(l4_hints_t2),
    )
    # Message index 0 is L0_global, message index 1 is L1_session
    assert ctx_t1.messages[0].content == ctx_t2.messages[0].content
    assert ctx_t1.messages[1].content == ctx_t2.messages[1].content
    assert any("Spanish" in str(m.content) for m in ctx_t2.messages[2:])
    store.close()


def test_memory_off_by_config_does_not_load_profile() -> None:
    store = _store()
    now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    store.insert(
        "CUST-0004",
        kind="preference",
        content="Prefers Spanish",
        structured={},
        source_conversation_id="prev",
        source_turn=1,
        expires_at=now + timedelta(days=30),
        confidence=0.9,
        now=now,
    )
    settings = get_settings().model_copy(deep=True)
    settings.memory.long_term.enabled = False
    deps = GraphDeps(settings=settings, memory_store=store)
    rewrite = make_rewrite_node(deps.models, settings, memory_store_provider=deps.long_term_memory)
    state = ConversationState(
        customer_id="CUST-0004",
        messages=[HumanMessage(content="Hello")],
    )
    out = rewrite(state)
    assert out["customer_profile"] is None
    assert out["customer_profile_loaded"] is False
    assert out["turn_memory_hints"] == []
    deps.close()
    store.close()


class _FakeOrders:
    def list_customers(self, limit: int = 10) -> list[CustomerSummary]:
        return [
            CustomerSummary(customer_id="CUST-A", name="Alice Example", email="a@example.com"),
            CustomerSummary(customer_id="CUST-B", name="Bob Example", email="b@example.com"),
        ][:limit]


def test_api_customer_memory_controls_and_isolation() -> None:
    store = _store()
    now = datetime.now(UTC)
    mem_a = store.insert(
        "CUST-A",
        kind="product_owned",
        content="Owns Philips BHD340/10",
        structured={},
        source_conversation_id="c1",
        source_turn=1,
        expires_at=now + timedelta(days=30),
        confidence=0.9,
        now=now,
    )
    store.insert(
        "CUST-B",
        kind="open_issue",
        content="Canary secret for B",
        structured={},
        source_conversation_id="c2",
        source_turn=1,
        expires_at=now + timedelta(days=30),
        confidence=0.9,
        now=now,
    )
    settings = get_settings().model_copy(deep=True)
    settings.memory.long_term.enabled = True
    graph_deps = GraphDeps(settings=settings, memory_store=store)
    api_deps = ApiDeps(
        settings=settings,
        graph_deps=graph_deps,
        order_service=_FakeOrders(),  # type: ignore[arg-type]
        milvus_check=lambda: True,
        warmup=False,
    )
    app = create_app(api_deps)
    with TestClient(app) as client:
        # Unauthenticated request is rejected with 401
        assert client.get("/api/me/memories").status_code == 401

        tok_a = client.post("/api/session", json={"customer_id": "CUST-A"}).json()["token"]
        tok_b = client.post("/api/session", json={"customer_id": "CUST-B"}).json()["token"]

        # Customer A sees only their own memory
        list_a: list[dict[str, Any]] = client.get(
            "/api/me/memories", headers={"Authorization": f"Bearer {tok_a}"}
        ).json()
        assert len(list_a) == 1
        assert list_a[0]["id"] == mem_a.id
        assert "Canary" not in str(list_a)

        # Customer B cannot delete Customer A's memory (404)
        del_cross = client.delete(
            f"/api/me/memories/{mem_a.id}",
            headers={"Authorization": f"Bearer {tok_b}"},
        )
        assert del_cross.status_code == 404

        # Customer A deletes their own memory
        del_own = client.delete(
            f"/api/me/memories/{mem_a.id}",
            headers={"Authorization": f"Bearer {tok_a}"},
        )
        assert del_own.status_code == 200
        assert del_own.json() == {"deleted": 1}
        after_a = client.get("/api/me/memories", headers={"Authorization": f"Bearer {tok_a}"})
        assert after_a.json() == []

        # Customer B deletes all their memories
        del_all = client.delete("/api/me/memories", headers={"Authorization": f"Bearer {tok_b}"})
        assert del_all.status_code == 200
        assert del_all.json() == {"deleted": 1}
        after_b = client.get("/api/me/memories", headers={"Authorization": f"Bearer {tok_b}"})
        assert after_b.json() == []
    store.close()
