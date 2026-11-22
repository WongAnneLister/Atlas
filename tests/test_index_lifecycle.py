from pathlib import Path

import pytest
from sqlalchemy import URL

from support_agent.config import Settings
from support_agent.db.engine import make_engine
from support_agent.retrieval.index_models import BuildRecord
from support_agent.retrieval.registry import IndexRegistry
from support_agent.retrieval.tokenization import WhitespaceTokenizer
from test_index_plan import write_docs


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
    # Fail fast if a test write waits on a held SQLite write lock.
    settings.db.connect_timeout_s = 1
    store = IndexRegistry(
        make_engine(URL.create("sqlite", database=str(tmp_path / "scratch.sqlite")), settings.db)
    )
    store.initialize()
    try:
        yield settings, store, Admin()
    finally:
        store.close()


def add(setup, ident, *, mode="full", collection=None, status="built"):
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
        status=status,
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
    write_docs(tmp_path, ("returns.window", "Window", "The fixture."))
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


def test_adoption_of_exact_legacy_content_requires_full_rebuild(setup, tmp_path: Path) -> None:
    from support_agent.retrieval.chunking import chunk_document
    from support_agent.retrieval.index_plan import index_fingerprint
    from support_agent.retrieval.index_release import adopt_index
    from support_agent.retrieval.tokenization import WhitespaceTokenizer
    from test_index_plan import document

    settings, registry, admin = setup
    settings.policy_versions.enabled = False
    collection = settings.index.protected_collections[0]
    admin.collections.add(collection)
    source = ("returns.window", "Window", "The fixture.")
    write_docs(tmp_path, source)
    tokenizer = WhitespaceTokenizer()

    class Reader:
        def collection_identity(self):
            return "some"

        def read_chunks(self):
            return chunk_document(document(source), settings.chunk, tokenizer)

        def alias_target(self):
            return None

    build = adopt_index(
        settings,
        registry,
        admin,
        collection,
        docs_dir=tmp_path,
        tokenizer=tokenizer,
        reader=Reader(),
    )
    assert build.mode == "adopted"
    assert build.fingerprint != index_fingerprint(settings)
    assert admin.target == collection


def test_slow_check_holds_no_registry_lock_and_a_concurrent_release_wins(setup) -> None:
    """The release check can take an hour; other writes to the same database must not wait."""
    from eval.index_release import ReleaseDecision

    from support_agent.retrieval.index_release import release_index

    settings, registry, admin = setup
    winner = add(setup, "a")
    newcomer = add(setup, "b")

    def slow_check(candidate, live):
        # Another operator releases a build while this check is still collecting evidence.
        release_index(
            settings,
            registry,
            admin,
            winner.build_id,
            lambda *_: (ReleaseDecision("release"), "winner"),
        )
        return ReleaseDecision("release"), "newcomer"

    with pytest.raises(ValueError, match="Another release"):
        release_index(settings, registry, admin, newcomer.build_id, slow_check)
    assert admin.target == winner.collection
    assert registry.get_alias(settings.index.live_alias).build_id == winner.build_id
    assert registry.get_build(newcomer.build_id).status == "built"


def test_refused_release_takes_no_lock_and_changes_nothing(setup) -> None:
    from eval.index_release import ReleaseDecision

    from support_agent.retrieval.index_release import release_index

    settings, registry, admin = setup
    candidate = add(setup, "a")

    def refuse(target, live):
        add(setup, "b")  # a registry write during the check must not wait on a lock
        return ReleaseDecision("refuse"), "refused"

    assert release_index(settings, registry, admin, candidate.build_id, refuse).outcome == "refuse"
    assert admin.target is None
    assert registry.get_alias(settings.index.live_alias).build_id is None


def test_gc_does_not_spend_rollback_slots_on_failed_builds(setup) -> None:
    from eval.index_release import ReleaseDecision

    from support_agent.retrieval.index_release import gc_indexes, release_index

    settings, registry, admin = setup
    settings.index.keep_builds = 3
    released = [add(setup, ident) for ident in ("a", "b", "c")]
    for build in released:
        release_index(
            settings,
            registry,
            admin,
            build.build_id,
            lambda *_: (ReleaseDecision("release"), "fixture"),
        )
    # A failed build drops its own collection.
    failed = [add(setup, ident, status="failed") for ident in ("d", "e")]
    for build in failed:
        admin.collections.remove(build.collection)
    dropped = gc_indexes(settings, registry, admin, yes=True)
    assert set(dropped) == {build.collection for build in failed}
    assert {build.collection for build in released} <= admin.collections and not admin.drops
    assert {registry.get_build(build.build_id).status for build in failed} == {"dropped"}
