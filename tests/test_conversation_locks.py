import pytest

from support_agent.api.locks import ConversationLocks, LockUnavailable
from support_agent.infra.redis import NullRedis
from test_api import QUESTION, REQUEST, client


def test_expired_owner_cannot_release_successor() -> None:
    now = 0.0
    store = NullRedis(clock=lambda: now)
    first = ConversationLocks(store, 5)
    second = ConversationLocks(store, 5)
    old_token = first.acquire("customer:thread")
    assert old_token is not None
    assert second.acquire("customer:thread") is None

    first.release("customer:thread", "stranger")
    assert second.acquire("customer:thread") is None
    now = 5.0
    token = second.acquire("customer:thread")
    assert token is not None and token != old_token

    first.release("customer:thread", old_token)
    assert first.acquire("customer:thread") is None
    second.release("customer:thread", token)
    assert first.acquire("customer:thread") is not None


class DownStore(NullRedis):
    def set_if_absent(self, key: str, value: str, ttl_s: int) -> bool:
        raise ConnectionError("private connection detail")


def test_lock_acquisition_needs_a_working_store() -> None:
    with pytest.raises(LockUnavailable, match="Conversation lock unavailable"):
        ConversationLocks(DownStore(), 5).acquire("customer:thread")


async def test_chat_and_resume_refuse_to_run_when_lock_store_is_down(seeded) -> None:
    async with client(seeded, lock_store=DownStore()) as api:
        for url, payload in (
            ("/api/chat", QUESTION),
            ("/api/resume", {**REQUEST, "value": "none"}),
        ):
            response = await api.post(url, json=payload)
            assert response.status_code == 503
            assert response.json() == {"detail": "Conversation lock unavailable"}


async def test_an_active_stream_renews_its_lease(seeded) -> None:
    import asyncio
    import threading

    from test_graph_knowledge import FixedRetriever, evidence

    settings, _ = seeded
    settings.reliability.locks.conversation_ttl_s = 1
    settings.reliability.locks.renew_interval_s = 0.02
    now = 0.0
    renewed = threading.Event()
    entered = threading.Event()
    release = threading.Event()

    class Store(NullRedis):
        def refresh_if_value(self, key: str, value: str, ttl_s: int) -> bool:
            refreshed = super().refresh_if_value(key, value, ttl_s)
            if refreshed and now >= 0.75:
                renewed.set()
            return refreshed

    class BlockingRetriever(FixedRetriever):
        def retrieve(self, query, top_k):
            entered.set()
            assert release.wait(5)
            return super().retrieve(query, top_k)

    store = Store(clock=lambda: now)
    async with client(seeded, lock_store=store, retriever=BlockingRetriever(evidence(0.99))) as api:
        first = asyncio.create_task(api.post("/api/chat", json=QUESTION))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            now = 0.75
            assert await asyncio.to_thread(renewed.wait, 2)
            now = 1.25
            assert (await api.post("/api/chat", json=QUESTION)).status_code == 409
        finally:
            release.set()
            assert (await first).status_code == 200
