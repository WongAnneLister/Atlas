import pytest


def test_null_redis_expires_values_and_keeps_the_first_increment_deadline() -> None:
    from support_agent.infra.redis import NullRedis

    now = 0.0
    store = NullRedis(clock=lambda: now)
    assert store.ping()
    assert store.set_if_absent("lock", "owner", 2)
    assert not store.set_if_absent("lock", "other", 10)
    assert store.get("lock") == "owner"
    assert store.incr("rate", 2) == 1

    now = 1.0
    assert store.incr("rate", 10) == 2
    assert store.get("rate") == "2"
    assert store.delete("lock")
    assert not store.delete("lock")
    store.set("lock", "other", 1)

    now = 2.0
    assert store.get("rate") is None
    assert store.get("lock") is None
    assert store.incr("rate", 5) == 1


def test_null_redis_rejects_nonpositive_ttl() -> None:
    from support_agent.infra.redis import NullRedis

    store = NullRedis()
    with pytest.raises(ValueError, match="TTL"):
        store.set("key", "value", 0)
    with pytest.raises(ValueError, match="TTL"):
        store.incr("key", -1)
