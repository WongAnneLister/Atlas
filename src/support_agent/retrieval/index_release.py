"""Release and restore immutable index builds under one registry lock."""

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

from support_agent.config import Settings
from support_agent.retrieval.index_build import new_build, save_build_snapshot, store_for
from support_agent.retrieval.index_models import BuildRecord
from support_agent.retrieval.index_plan import (
    chunks_for,
    default_docs_dir,
    index_fingerprint,
    load_corpus,
)
from support_agent.retrieval.milvus_store import MilvusStore
from support_agent.retrieval.registry import AliasTransaction, IndexRegistry
from support_agent.retrieval.tokenization import BgeTokenizer, Tokenizer


class CollectionAdmin(Protocol):
    def alias_target(self) -> str | None: ...
    def switch(self, target: str, expected: str | None) -> None: ...
    def exists(self, name: str) -> bool: ...
    def drop(self, name: str) -> None: ...


class MilvusAdmin:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = store_for(settings, settings.index.live_alias)

    def close(self) -> None:
        self.store.close()

    def alias_target(self) -> str | None:
        return self.store.alias_target()

    def switch(self, target: str, expected: str | None) -> None:
        self.store.switch_alias(target, expected)

    def exists(self, name: str) -> bool:
        return self.store.has_collection(name)

    def drop(self, name: str) -> None:
        store = store_for(self.settings, name)
        try:
            store.drop()
        finally:
            store.close()


class Decision(Protocol):
    @property
    def outcome(self) -> Literal["release", "refuse", "invalid"]: ...

    @property
    def override_reason(self) -> str | None: ...

    def markdown(self) -> str: ...


Check = Callable[[BuildRecord, BuildRecord | None], tuple[Decision, str]]


def _aligned(lock: AliasTransaction, admin: CollectionAdmin) -> BuildRecord | None:
    build = lock.get_build(lock.current.build_id)
    expected = build.collection if build else None
    if admin.alias_target() != expected:
        raise ValueError("Index alias drift; inspect index-status before releasing or collecting")
    return build


def release_index(
    settings: Settings,
    registry: IndexRegistry,
    admin: CollectionAdmin,
    build_id: str,
    check: Check,
) -> Decision:
    expected = registry.get_alias(settings.index.live_alias).build_id
    with registry.locked_alias(settings.index.live_alias) as lock:
        if lock.current.build_id != expected:
            raise ValueError("Another release changed the index alias; retry with fresh evidence")
        live = _aligned(lock, admin)
        target = lock.get_build(build_id)
        if target is None or target.status != "built" or target.mode == "adopted":
            raise ValueError("Release requires a completed private candidate build")
        if not admin.exists(target.collection):
            raise ValueError("Candidate collection is missing")
        decision, evidence = check(target, live)
        if decision.outcome == "release":
            admin.switch(target.collection, live.collection if live else None)
            lock.swap(
                live.build_id if live else None,
                build_id,
                eval_run_id=evidence,
                override_reason=decision.override_reason,
            )
        return decision


def rollback_index(
    settings: Settings, registry: IndexRegistry, admin: CollectionAdmin
) -> BuildRecord:
    with registry.locked_alias(settings.index.live_alias) as lock:
        live = _aligned(lock, admin)
        target = lock.get_build(lock.current.previous_build_id)
        if (
            target is None
            or target.status not in {"retired", "released"}
            or target.released_at is None
            or not admin.exists(target.collection)
        ):
            raise ValueError("There is no previous released collection to restore")
        admin.switch(target.collection, live.collection if live else None)
        lock.swap(live.build_id if live else None, target.build_id)
        return target


def index_status(
    settings: Settings,
    registry: IndexRegistry,
    admin: CollectionAdmin,
    *,
    reconcile: bool = False,
) -> dict[str, object]:
    alias = settings.index.live_alias
    if reconcile:
        registry.initialize()
        with registry.locked_alias(alias) as lock:
            actual = admin.alias_target()
            matches = [build for build in lock.builds() if build.collection == actual]
            if actual is not None and not matches:
                raise ValueError("Milvus alias targets an unregistered collection")
            lock.swap(lock.current.build_id, matches[0].build_id if matches else None)
    entry = registry.get_alias(alias)
    build = registry.get_build(entry.build_id)
    expected = build.collection if build else None
    actual = admin.alias_target()
    return {
        "alias": alias,
        "milvus_collection": actual,
        "registry_collection": expected,
        "drift": actual != expected,
        "registry": entry.model_dump(),
        "builds": [item.model_dump(mode="json") for item in registry.builds()],
    }


def gc_indexes(
    settings: Settings,
    registry: IndexRegistry,
    admin: CollectionAdmin,
    *,
    yes: bool = False,
) -> list[str]:
    with registry.locked_alias(settings.index.live_alias) as lock:
        _aligned(lock, admin)
        builds = lock.builds()
        keep = {lock.current.build_id, lock.current.previous_build_id}
        keep.update(build.parent_build_id for build in builds if build.status == "building")
        eligible = [
            build
            for build in builds
            if build.mode != "adopted"
            and build.status in {"released", "retired", "built", "failed"}
            and build.collection == settings.index.collection_prefix + build.build_id
            and build.collection not in settings.index.protected_collections
        ]
        candidates = [
            build for build in eligible[settings.index.keep_builds :] if build.build_id not in keep
        ]
        if yes:
            for build in candidates:
                admin.drop(build.collection)
                lock.mark_dropped(build.build_id)
        return [build.collection for build in candidates]


def adopt_index(
    settings: Settings,
    registry: IndexRegistry,
    admin: CollectionAdmin,
    collection: str,
    *,
    docs_dir: Path | None = None,
    tokenizer: Tokenizer | None = None,
    reader: MilvusStore | None = None,
) -> BuildRecord:
    registry.initialize()
    with registry.locked_alias(settings.index.live_alias) as lock:
        if _aligned(lock, admin) is not None:
            raise ValueError("Adoption is only available before the first release")
        if collection == settings.index.live_alias or not admin.exists(collection):
            raise ValueError("Adoption requires an existing physical collection")
        corpus = load_corpus(docs_dir or default_docs_dir(settings))
        splitter = tokenizer or BgeTokenizer(settings.retrieval)
        expected = chunks_for(corpus, sorted(corpus.sections), settings, splitter)
        store = reader or store_for(settings, collection)
        try:
            if store.alias_target() is not None:
                raise ValueError("Adoption requires a physical collection")
            store.collection_identity()
            actual = store.read_chunks()
        finally:
            if reader is None:
                store.close()
        if {chunk.chunk_id: chunk for chunk in actual} != {
            chunk.chunk_id: chunk for chunk in expected
        }:
            raise ValueError("Existing collection chunks do not match the on-disk documents")
        prior = next((build for build in lock.builds() if build.collection == collection), None)
        fingerprint = index_fingerprint(settings)
        if prior is None:
            record = new_build(settings, corpus, fingerprint, mode="adopted", collection=collection)
            save_build_snapshot(settings, record.build_id, actual)
            lock.record_adoption(record, corpus, Counter(chunk.section_id for chunk in expected))
        elif (
            prior.mode == "adopted"
            and prior.docs_hash == corpus.docs_hash
            and prior.fingerprint == fingerprint
        ):
            record = prior
        else:
            raise ValueError("Collection already has a different registry record")
    # Commit the build before the external switch so status can reconcile a crash.
    with registry.locked_alias(settings.index.live_alias) as lock:
        if _aligned(lock, admin) is not None:
            raise ValueError("Adoption requires an empty live alias")
        admin.switch(collection, None)
        lock.swap(None, record.build_id)
        result = lock.get_build(record.build_id)
        if result is None:
            raise RuntimeError("Adopted build revision cannot be found")
        return result
