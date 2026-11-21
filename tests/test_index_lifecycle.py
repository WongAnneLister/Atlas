from pathlib import Path

import pytest
from sqlalchemy import URL

from support_agent.config import Settings
from support_agent.db.engine import make_engine
from support_agent.retrieval.index_models import BuildRecord
from support_agent.retrieval.registry import IndexRegistry
from support_agent.retrieval.tokenization import WhitespaceTokenizer
from test_index_plan import document


class Admin:
    def __init__(self):
        self.target = None
        self.collections = set()
        self.drops = []

    def alias_target(self):
        return self.target

    def exists(self, target):
        return target in self.collections

    def switch(self, target, expected):
        assert self.target == expected
        self.target = target

    def drop(self, name):
        self.drops.append(name)
        self.collections.remove(name)


@pytest.fixture
def setup(tmp_path):
    settings = Settings()
    settings.data.processed_dir = str(tmp_path)
    store = IndexRegistry(
        make_engine(URL.create("sqlite", database=str(tmp_path / "scratch.sqlite")), settings.db)
    )
    store.initialize()
    try:
        yield settings, store, Admin()
    finally:
        store.close()


def add(setup, ident, *, mode="full", collection=None):
    settings, registry, admin = setup
    collection = collection or settings.index.collection_prefix + ident
    build = BuildRecord(
        build_id=ident,
        collection=collection,
        mode=mode,
        fingerprint="fixture",
        embed_model="fake",
        embed_revision="fake",
        chunker_version="1",
        docs_hash="fixture",
        status="built",
    )
    registry.begin_build(build)
    admin.collections.add(collection)
    return build


def test_release_refuse_release_and_rollback(setup) -> None:
    from eval.index_release import ReleaseDecision

    from support_agent.retrieval.index_release import index_status, release_index, rollback_index

    settings, registry, admin = setup
    first = add(setup, "a")
    second = add(setup, "b")
    result = release_index(
        settings, registry, admin, first.build_id, lambda *_: (ReleaseDecision("refuse"), "fixture")
    )
    assert result.outcome == "refuse" and admin.target is None
    release_index(
        settings,
        registry,
        admin,
        first.build_id,
        lambda *_: (ReleaseDecision("release"), "first-run"),
    )
    with pytest.raises(ValueError, match="no previous"):
        rollback_index(settings, registry, admin)
    release_index(
        settings,
        registry,
        admin,
        second.build_id,
        lambda *_: (ReleaseDecision("release", override_reason="policy retired"), "second-run"),
    )
    saved = registry.get_build(second.build_id)
    assert saved.eval_run_id == "second-run" and saved.override_reason == "policy retired"
    assert not index_status(settings, registry, admin)["drift"]
    assert registry.get_alias(settings.index.live_alias).previous_build_id == first.build_id
    assert rollback_index(settings, registry, admin).build_id == first.build_id
    assert admin.target == first.collection
    admin.collections.remove(second.collection)
    with pytest.raises(ValueError, match="no previous"):
        rollback_index(settings, registry, admin)


def test_gc_and_drift_protect_registered_and_unregistered_collections(setup) -> None:
    from eval.index_release import ReleaseDecision

    from support_agent.retrieval.index_release import gc_indexes, index_status, release_index

    settings, registry, admin = setup
    original = add(setup, "a")
    adopted = add(setup, "b", mode="adopted", collection=settings.index.protected_collections[0])
    recent = add(setup, "c")
    current = add(setup, "d")
    admin.collections.add("unknown")
    for build in (recent, current):
        release_index(
            settings,
            registry,
            admin,
            build.build_id,
            lambda *_: (ReleaseDecision("release"), "fixture"),
        )
    assert gc_indexes(settings, registry, admin) == [original.collection] and not admin.drops
    admin.target = recent.collection
    assert index_status(settings, registry, admin)["drift"]
    with pytest.raises(ValueError, match="drift"):
        gc_indexes(settings, registry, admin, yes=True)
    assert not index_status(settings, registry, admin, reconcile=True)["drift"]
    assert gc_indexes(settings, registry, admin, yes=True) == [original.collection]
    assert {
        adopted.collection,
        current.collection,
        recent.collection,
        "unknown",
    } <= admin.collections


def test_adoption_refuses_mismatched_text(setup, tmp_path: Path) -> None:
    from support_agent.retrieval.index_release import adopt_index

    class Reader:
        def collection_identity(self):
            return "some"

        def read_chunks(self):
            return []

        def alias_target(self):
            return None

    settings, registry, admin = setup
    collection = settings.index.protected_collections[0]
    admin.collections.add(collection)
    (tmp_path / "returns.md").write_text(document(("returns.window", "Window", "The fixture.")))
    with pytest.raises(ValueError, match="do not match"):
        adopt_index(
            settings,
            registry,
            admin,
            collection,
            docs_dir=tmp_path,
            tokenizer=WhitespaceTokenizer(),
            reader=Reader(),
        )
    assert admin.target is None and not registry.builds()


def test_release_refuses_when_another_switch_wins(setup, monkeypatch) -> None:
    from eval.index_release import ReleaseDecision

    from support_agent.retrieval.index_models import AliasRecord
    from support_agent.retrieval.index_release import release_index

    settings, registry, admin = setup
    winner = add(setup, "a")
    newcomer = add(setup, "b")
    release_index(
        settings,
        registry,
        admin,
        winner.build_id,
        lambda *_: (ReleaseDecision("release"), "winner"),
    )
    monkeypatch.setattr(registry, "get_alias", lambda alias: AliasRecord(alias=alias))
    with pytest.raises(ValueError, match="Another release"):
        release_index(
            settings,
            registry,
            admin,
            newcomer.build_id,
            lambda *_: (ReleaseDecision("release"), "newcomer"),
        )
    assert admin.target == winner.collection
