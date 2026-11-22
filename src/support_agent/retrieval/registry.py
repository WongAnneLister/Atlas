"""Store index versions and serialize changes to an alias."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from support_agent.config import Settings
from support_agent.db.engine import make_engine, postgres_url, sqlite_path, transaction
from support_agent.retrieval.index_models import AliasRecord, BuildRecord, BuildSection, Corpus, now
from support_agent.retrieval.index_tables import (
    build_sections,
    documents,
    index_alias,
    index_builds,
    metadata,
    sections,
)


class AliasTransaction:
    def __init__(self, connection: sa.Connection, current: AliasRecord) -> None:
        self.connection = connection
        self.current = current

    def get_build(self, build_id: str | None) -> BuildRecord | None:
        return _build(self.connection, build_id)

    def builds(self) -> list[BuildRecord]:
        return _builds(self.connection)

    def swap(
        self,
        expected: str | None,
        target: str | None,
        *,
        eval_run_id: str | None = None,
        override_reason: str | None = None,
    ) -> None:
        row = (
            self.connection.execute(
                index_alias.select().where(index_alias.c.alias == self.current.alias)
            )
            .mappings()
            .one()
        )
        if row["build_id"] != expected:
            raise RuntimeError("Index alias changed; inspect status and retry")
        new = self.get_build(target)
        if target is not None and (
            new is None or new.status not in {"built", "released", "retired"}
        ):
            raise ValueError("Alias target must be a complete index build")
        if target == expected:
            return
        timestamp = now()
        if expected is not None:
            self.connection.execute(
                index_builds.update()
                .where(index_builds.c.build_id == expected)
                .values(status="retired")
            )
        if new is not None:
            self.connection.execute(
                index_builds.update()
                .where(index_builds.c.build_id == target)
                .values(
                    status="released",
                    released_at=new.released_at or timestamp,
                    eval_run_id=eval_run_id if eval_run_id is not None else new.eval_run_id,
                    override_reason=override_reason
                    if eval_run_id is not None
                    else new.override_reason,
                )
            )
        self.connection.execute(
            index_alias.update()
            .where(index_alias.c.alias == self.current.alias)
            .values(
                build_id=target,
                previous_build_id=expected,
                updated_at=timestamp,
            )
        )
        self.current = AliasRecord(
            alias=self.current.alias, build_id=target, previous_build_id=expected
        )

    def record_adoption(
        self, build: BuildRecord, corpus: Corpus, counts: Mapping[str, int]
    ) -> None:
        if build.mode != "adopted":
            raise ValueError("Expected an adoption record")
        self.connection.execute(index_builds.insert().values(**build.model_dump()))
        finish_build(self.connection, build.build_id, corpus, counts)

    def mark_dropped(self, build_id: str) -> None:
        build = self.get_build(build_id)
        if (
            build is None
            or build.mode == "adopted"
            or build.status not in {"retired", "failed", "built"}
            or build_id in {self.current.build_id, self.current.previous_build_id}
        ):
            raise ValueError("Build is protected from garbage collection")
        self.connection.execute(
            index_builds.update()
            .where(index_builds.c.build_id == build_id)
            .values(status="dropped")
        )


def _build(connection: sa.Connection, build_id: str | None) -> BuildRecord | None:
    if build_id is None:
        return None
    row = (
        connection.execute(index_builds.select().where(index_builds.c.build_id == build_id))
        .mappings()
        .one_or_none()
    )
    return BuildRecord.model_validate(row) if row else None


def _builds(connection: sa.Connection) -> list[BuildRecord]:
    query = index_builds.select().order_by(
        index_builds.c.created_at.desc(), index_builds.c.build_id
    )
    return [BuildRecord.model_validate(row) for row in connection.execute(query).mappings()]


class IndexRegistry:
    def __init__(self, engine: sa.Engine) -> None:
        self.engine = engine

    @classmethod
    def from_settings(cls, settings: Settings) -> "IndexRegistry":
        if settings.db.backend == "postgres":
            url = postgres_url(settings)
            if url.port is None or url.port in settings.index.blocked_postgres_ports:
                raise ValueError("Index operations require a dedicated Atlas PostgreSQL port")
        else:
            url = sa.URL.create("sqlite", database=str(sqlite_path(settings)))
        return cls(make_engine(url, settings.db))

    def close(self) -> None:
        self.engine.dispose()

    def initialize(self) -> None:
        if self.engine.dialect.name == "sqlite":
            # The local order fixture creates only its own tables.
            with transaction(self.engine, write=True) as connection:
                metadata.create_all(connection)

    def _has_sqlite_file(self) -> bool:
        from pathlib import Path

        name = self.engine.url.database
        return self.engine.dialect.name != "sqlite" or (name is not None and Path(name).is_file())

    def get_alias(self, name: str) -> AliasRecord:
        if self._has_sqlite_file():
            with self.engine.connect() as connection:
                if sa.inspect(connection).has_table(index_alias.name):
                    raw = (
                        connection.execute(index_alias.select().where(index_alias.c.alias == name))
                        .mappings()
                        .one_or_none()
                    )
                    if raw:
                        return AliasRecord.model_validate(raw)
        return AliasRecord(alias=name)

    def get_build(self, build_id: str | None) -> BuildRecord | None:
        if build_id is None:
            return None
        with self.engine.connect() as connection:
            return _build(connection, build_id)

    def build_sections(self, build_id: str) -> dict[str, BuildSection]:
        query = build_sections.select().where(build_sections.c.build_id == build_id)
        with self.engine.connect() as connection:
            return {
                row["section_id"]: BuildSection.model_validate(row)
                for row in connection.execute(query).mappings()
            }

    def builds(self) -> list[BuildRecord]:
        if not self._has_sqlite_file():
            return []
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "sqlite" and not sa.inspect(connection).has_table(
                index_builds.name
            ):
                return []
            return _builds(connection)

    def get_build_by_collection(self, collection: str) -> BuildRecord | None:
        if not self._has_sqlite_file():
            return None
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "sqlite" and not sa.inspect(connection).has_table(
                index_builds.name
            ):
                return None
            query = index_builds.select().where(index_builds.c.collection == collection)
            row = connection.execute(query).mappings().one_or_none()
            return BuildRecord.model_validate(row) if row else None

    @contextmanager
    def locked_alias(self, name: str) -> Iterator[AliasTransaction]:
        with transaction(self.engine, write=True) as connection:
            values = {"alias": name, "updated_at": now()}
            query = index_alias.select().where(index_alias.c.alias == name).with_for_update()
            if connection.dialect.name == "postgresql":
                connection.execute(pg_insert(index_alias).values(**values).on_conflict_do_nothing())
            elif connection.execute(query).first() is None:
                connection.execute(index_alias.insert().values(**values))
            current = AliasRecord.model_validate(connection.execute(query).mappings().one())
            yield AliasTransaction(connection, current)

    def begin_build(self, build: BuildRecord) -> None:
        with transaction(self.engine, write=True) as connection:
            connection.execute(index_builds.insert().values(**build.model_dump()))

    def fail_build(self, build_id: str) -> None:
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                index_builds.update()
                .where(index_builds.c.build_id == build_id, index_builds.c.status == "building")
                .values(status="failed")
            )

    def finish_build(
        self,
        build_id: str,
        corpus: Corpus,
        chunk_counts: Mapping[str, int],
        *,
        deleted: Sequence[str] = (),
    ) -> None:
        with transaction(self.engine, write=True) as connection:
            finish_build(connection, build_id, corpus, chunk_counts, deleted=deleted)


def finish_build(
    connection: sa.Connection,
    build_id: str,
    corpus: Corpus,
    chunk_counts: Mapping[str, int],
    *,
    deleted: Sequence[str] = (),
) -> None:
    build = _build(connection, build_id)
    if build is None or build.status != "building" or set(chunk_counts) != set(corpus.sections):
        raise ValueError("Build and chunk counts must cover the complete corpus")
    timestamp = now()
    # Serialize the global version ledger across independent builds on PostgreSQL.
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("LOCK TABLE documents IN SHARE ROW EXCLUSIVE MODE")
    latest = {
        row["section_id"]: dict(row)
        for row in connection.execute(sections.select().order_by(sections.c.version)).mappings()
    }
    changed_docs = {
        section.doc_id
        for section in corpus.sections.values()
        if (old := latest.get(section.section_id)) is None
        or old["is_deleted"]
        or old["content_hash"] != section.content_hash
    }
    tombstones = [latest[sid] for sid in deleted if sid in latest and not latest[sid]["is_deleted"]]
    changed_docs.update(row["doc_id"] for row in tombstones)
    existing = {row["doc_id"]: row for row in connection.execute(documents.select()).mappings()}
    for doc in corpus.documents.values():
        stored_doc = existing.get(doc.doc_id)
        fields = doc.model_dump()
        if stored_doc is None:
            connection.execute(documents.insert().values(**fields, version=1, updated_at=timestamp))
        elif doc.doc_id in changed_docs or (stored_doc["title"], stored_doc["source"]) != (
            doc.title,
            doc.source,
        ):
            connection.execute(
                documents.update()
                .where(documents.c.doc_id == doc.doc_id)
                .values(
                    **fields,
                    version=stored_doc["version"] + 1,
                    updated_at=timestamp,
                )
            )
    for doc_id in changed_docs - corpus.documents.keys():
        connection.execute(
            documents.update()
            .where(documents.c.doc_id == doc_id)
            .values(
                version=documents.c.version + 1,
                updated_at=timestamp,
            )
        )
    for section in corpus.sections.values():
        previous = latest.get(section.section_id)
        version = previous["version"] if previous else 0
        if (
            previous is None
            or previous["content_hash"] != section.content_hash
            or previous["is_deleted"]
        ):
            version += 1
            fields = section.model_dump(exclude={"heading", "metadata"})
            connection.execute(
                sections.insert().values(
                    **fields,
                    version=version,
                    metadata={
                        "heading": section.heading,
                        **section.metadata.model_dump(mode="json"),
                    },
                    is_deleted=False,
                    created_at=timestamp,
                )
            )
        connection.execute(
            build_sections.insert().values(
                build_id=build_id,
                section_id=section.section_id,
                section_version=version,
                content_hash=section.content_hash,
                chunk_count=chunk_counts[section.section_id],
            )
        )
    for old in tombstones:
        connection.execute(
            sections.insert().values(
                {
                    **old,
                    "version": old["version"] + 1,
                    "is_deleted": True,
                    "created_at": timestamp,
                }
            )
        )
    connection.execute(
        index_builds.update().where(index_builds.c.build_id == build_id).values(status="built")
    )
