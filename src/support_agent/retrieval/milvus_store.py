"""The only module importing pymilvus; dense and lexical index access stays here."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import Any, Protocol

import grpc  # type: ignore[import-untyped]
from pydantic import BaseModel

from support_agent.config import Settings
from support_agent.retrieval.chunking import Chunk
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.milvus_metadata import (
    DAY_FIELDS,
    LEGACY_CHUNK_FIELDS,
    METADATA_FIELDS,
    METADATA_STRINGS,
    chunk_to_row,
    row_to_chunk_fields,
)

STORE_SCHEMA_VERSION = "2"
DESCRIPTION = "support-agent dense+BM25 chunks v1"


# Bound the walk: pymilvus wraps an outage a few times, never dozens.
_MAX_CHAIN = 16


def milvus_transport_failure(error: BaseException) -> bool:
    """Recognize transient gRPC and Milvus statuses anywhere in the exception chain.

    pymilvus wraps outages several times (retry decorators, connection recovery), with
    either an explicit cause or an implicit context, so every link is checked.
    """
    seen: set[int] = set()
    link: BaseException | None = error
    while link is not None and id(link) not in seen and len(seen) < _MAX_CHAIN:
        seen.add(id(link))
        if _transient_link(link):
            return True
        link = link.__cause__ or link.__context__
    return False


def _transient_link(error: BaseException) -> bool:
    from pymilvus.client.types import Status
    from pymilvus.exceptions import (
        ConnectError,
        ErrorCode,
        MilvusException,
        MilvusUnavailableException,
    )
    from pymilvus.grpc_gen import common_pb2

    retryable_statuses = (
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
    )
    if isinstance(error, grpc.RpcError):
        return error.code() in retryable_statuses
    if not isinstance(error, MilvusException):
        return False
    return (
        isinstance(error, ConnectError | MilvusUnavailableException)
        or bool(error.retriable)
        or error.code in (*retryable_statuses, ErrorCode.RATE_LIMIT, Status.CONNECT_FAILED)
        or error.compatible_code == common_pb2.RateLimit
    )


class ChunkStore(Protocol):
    def create_or_reset(self) -> None: ...

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def count(self) -> int: ...


class VectorChunk(BaseModel):
    chunk: Chunk
    dense: list[float]


class SearchHit(Chunk):
    score: float


class SearchStore(Protocol):
    def search_dense(
        self, vector: list[float], limit: int, *, filters: RetrievalFilters | None = None
    ) -> list[SearchHit]: ...

    def search_bm25(
        self, text: str, limit: int, *, filters: RetrievalFilters | None = None
    ) -> list[SearchHit]: ...


class MilvusStore:
    def __init__(
        self,
        settings: Settings,
        client: Any = None,
        *,
        timeout_s: float | None = None,
        provenance_settings: Settings | None = None,
    ) -> None:
        from pymilvus import MilvusClient

        self.settings = settings
        self.provenance_settings = provenance_settings or settings
        self.config = settings.milvus
        self._pinned_reads: str | None = None
        self._read_target: ContextVar[str | None] = ContextVar("milvus_read_target", default=None)
        self._metadata_collections: dict[str, bool] = {}
        self._experiment_writes = False
        self._build_identity: tuple[float, str | None] | None = None
        self._chunk_snapshot: dict[str, Chunk] | None = None
        self.client: Any = (
            client
            if client is not None
            else MilvusClient(
                uri=self.config.uri,
                timeout=timeout_s if timeout_s is not None else self.config.timeout_s,
            )
        )

    def server_version(self) -> str:
        return str(self.client.get_server_version(timeout=self.config.timeout_s))

    @property
    def collection(self) -> str:
        return self.config.collection

    def has_collection(self, name: str) -> bool:
        return bool(self.client.has_collection(collection_name=name, timeout=self.config.timeout_s))

    def exists(self) -> bool:
        return self.has_collection(self.collection)

    def switch_alias(self, target: str, expected: str | None) -> None:
        alias = self.settings.index.live_alias
        if alias in self.settings.index.protected_collections or alias == target:
            raise ValueError("Invalid lifecycle alias")
        if self.alias_target(alias) != expected:
            raise ValueError("Milvus alias drift before switch")
        if self.alias_target(target) is not None or not self.has_collection(target):
            raise ValueError("Index alias needs an existing physical target")
        switch = self.client.create_alias if expected is None else self.client.alter_alias
        switch(collection_name=target, alias=alias, timeout=self.config.timeout_s)

    def pin_reads(self) -> None:
        """Bind a multi-query experiment to the alias target it started with."""
        if self.collection == self.settings.index.live_alias:
            target = self.alias_target()
            if target is None:
                raise ValueError("Serving index alias is missing; adopt or release an index first")
            self._pinned_reads = target
            self._build_identity = None

    @property
    def read_collection(self) -> str:
        return self._read_target.get() or self._pinned_reads or self.collection

    def resolve_read_target(self, *, timeout_s: float | None = None) -> str:
        target = self.read_collection
        if target != self.settings.index.live_alias:
            return target
        physical = self.alias_target(target, timeout_s=timeout_s)
        if physical is None:
            raise ValueError("Serving index alias is missing; adopt or release an index first")
        return physical

    @contextmanager
    def use_read_target(self, target: str) -> Iterator[None]:
        token = self._read_target.set(target)
        try:
            yield
        finally:
            self._read_target.reset(token)

    @contextmanager
    def filter_scope(self) -> Iterator[None]:
        # Probe and both searches refer to one physical schema even across an alias switch.
        with self.use_read_target(self.resolve_read_target()):
            yield

    def _has_metadata(self, target: str, timeout_s: float | None = None) -> bool:
        if target not in self._metadata_collections:
            description = self.client.describe_collection(
                collection_name=target,
                timeout=self.config.timeout_s if timeout_s is None else timeout_s,
            )
            names = {field["name"] for field in description.get("fields", ())}
            present = names.intersection(METADATA_FIELDS)
            if present and present != set(METADATA_FIELDS):
                raise ValueError("Milvus collection has incomplete filter metadata")
            self._metadata_collections[target] = bool(present)
        return self._metadata_collections[target]

    def supports_filters(self, *, timeout_s: float | None = None) -> bool:
        return self._has_metadata(self.resolve_read_target(timeout_s=timeout_s), timeout_s)

    def _output_fields(self, target: str, timeout_s: float | None = None) -> list[str]:
        metadata = METADATA_FIELDS if self._has_metadata(target, timeout_s) else ()
        return [*LEGACY_CHUNK_FIELDS, *metadata]

    def ready(self) -> bool:
        if self.collection != self.settings.index.live_alias:
            return self.exists()
        target = self.alias_target()
        return target is not None and self.has_collection(target)

    def invalidate_build_identity(self) -> None:
        self._build_identity = None

    def current_build_id(self) -> str | None:
        """Resolve provenance without making successful search depend on the registry."""
        at = monotonic()
        if self._build_identity is not None and at < self._build_identity[0]:
            return self._build_identity[1]
        build_id = None
        try:
            target = (
                (self._read_target.get() or self._pinned_reads or self.alias_target())
                if self.collection == self.settings.index.live_alias
                else self.collection
            )
            if target:
                prefix = self.settings.index.collection_prefix
                suffix = target.removeprefix(prefix)
                if target.startswith(prefix) and re.fullmatch(r"[a-f0-9]+", suffix):
                    build_id = suffix
                else:
                    from support_agent.retrieval.registry import IndexRegistry

                    registry = IndexRegistry.from_settings(self.provenance_settings)
                    try:
                        record = registry.get_build_by_collection(target)
                        build_id = record.build_id if record else None
                    finally:
                        registry.close()
        except Exception:
            # Build provenance is optional. The retrieval operation has its own failure path.
            pass
        self._build_identity = (at + self.settings.index.alias_ttl_s, build_id)
        return build_id

    def collection_identity(self) -> str:
        info = self.client.describe_collection(
            collection_name=self.read_collection, timeout=self.config.timeout_s
        )
        if info.get("description") != DESCRIPTION:
            raise ValueError("Expected a support-agent collection")
        return str(info["collection_id"])

    def read_chunks(self) -> list[Chunk]:
        with self.filter_scope():
            return self._read_chunks()

    def _read_chunks(self) -> list[Chunk]:
        target = self.read_collection
        count = self.count()
        if not count:
            return []
        reader = self.client.query_iterator(
            collection_name=self.read_collection,
            filter="",
            batch_size=self.config.query_batch_size,
            output_fields=self._output_fields(target),
            consistency_level="Strong",
            timeout=self.config.timeout_s,
        )
        chunks: list[Chunk] = []
        try:
            while rows := reader.next():
                chunks.extend(
                    Chunk.model_validate(
                        row_to_chunk_fields(row, self.settings.policy_versions.open_end_day)
                    )
                    for row in rows
                )
        finally:
            reader.close()
        if len(chunks) != count or len({chunk.chunk_id for chunk in chunks}) != count:
            raise ValueError("Incomplete collection snapshot")
        return chunks

    def read_vectors(self, section_ids: Sequence[str]) -> list[VectorChunk]:
        if not section_ids:
            return []
        target = self.resolve_read_target()
        reader = self.client.query_iterator(
            collection_name=target,
            filter=f"section_id in {json.dumps(list(section_ids), ensure_ascii=False)}",
            batch_size=self.config.query_batch_size,
            output_fields=[*self._output_fields(target), "dense"],
            consistency_level="Strong",
            timeout=self.config.timeout_s,
        )
        results: list[VectorChunk] = []
        try:
            while rows := reader.next():
                results.extend(
                    VectorChunk(
                        chunk=Chunk.model_validate(
                            row_to_chunk_fields(row, self.settings.policy_versions.open_end_day)
                        ),
                        dense=row["dense"],
                    )
                    for row in rows
                )
        finally:
            reader.close()
        return results

    def use_chunk_snapshot(self, chunks: list[Chunk]) -> None:
        if not chunks or len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("Need a nonempty unique chunk snapshot")
        self._chunk_snapshot = {chunk.chunk_id: chunk.model_copy(deep=True) for chunk in chunks}

    def _assert_owned(self) -> None:
        description = self.client.describe_collection(
            collection_name=self.config.collection,
            timeout=self.config.timeout_s,
        )
        if description.get("description") != DESCRIPTION:
            raise ValueError("Refusing to reset a collection not created by support-agent")

    def alias_target(
        self, alias: str | None = None, *, timeout_s: float | None = None
    ) -> str | None:
        from pymilvus.exceptions import MilvusException

        describe = getattr(self.client, "describe_alias", None)
        if describe is None:
            return None
        try:
            response = describe(
                alias=alias or self.collection,
                timeout=self.config.timeout_s if timeout_s is None else timeout_s,
            )
        except MilvusException as error:
            message = str(error.message).lower()
            if (
                not milvus_transport_failure(error)
                and "alias" in message
                and any(
                    marker in message
                    for marker in (
                        "not found",
                        "not exist",
                        "cannot find",
                        "can't find",
                        "doesn't exist",
                    )
                )
            ):
                return None
            raise
        target = response.get("collection_name")
        if not isinstance(target, str) or not target:
            raise ValueError("Invalid Milvus alias description")
        return target

    def allow_experiment_writes(self) -> None:
        """Let the retrieval experiment builder rebuild its own configured collection."""
        experiments = {
            self.settings.retrieval_eval.baseline_collection,
            self.settings.retrieval_eval.heading_ablation_collection,
        }
        if self.collection not in experiments:
            raise ValueError("Only configured experiment collections accept experiment writes")
        self._experiment_writes = True

    def _require_physical_writable(self) -> None:
        if (
            self.collection in self.settings.index.protected_collections
            and not self._experiment_writes
        ):
            raise ValueError("Refusing to modify a protected collection")
        if self.collection == self.settings.index.live_alias or self.alias_target() is not None:
            raise ValueError("Refusing to modify a collection through an alias")

    def create_or_reset(self) -> None:
        self._require_physical_writable()
        if self.exists():
            self.drop()
        self._create_schema()

    def create(self) -> None:
        self._require_physical_writable()
        if self.exists():
            raise ValueError("Refusing to replace an existing collection")
        self._create_schema()

    def _create_schema(self) -> None:
        from pymilvus import DataType, Function, FunctionType, MilvusClient

        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
            description=DESCRIPTION,
        )
        for name, limit in (
            ("chunk_id", self.config.id_max_bytes),
            ("doc_id", self.config.id_max_bytes),
            ("section_id", self.config.section_max_bytes),
            ("title", self.config.heading_max_bytes),
            ("heading_path", self.config.heading_max_bytes),
            ("text", self.config.text_max_bytes),
        ):
            options: dict[str, Any] = {"max_length": limit}
            if name == "chunk_id":
                options["is_primary"] = True
            if name == "text":
                options.update(enable_analyzer=True, analyzer_params=self.config.analyzer)
            schema.add_field(field_name=name, datatype=DataType.VARCHAR, **options)
        for field in METADATA_STRINGS:
            schema.add_field(
                field_name=field,
                datatype=DataType.VARCHAR,
                max_length=self.config.metadata_max_bytes,
            )
        for field in DAY_FIELDS:
            schema.add_field(field_name=field, datatype=DataType.INT32)
        schema.add_field(field_name="n_tokens", datatype=DataType.INT64)
        schema.add_field(
            field_name="dense",
            datatype=DataType.FLOAT_VECTOR,
            dim=self.settings.retrieval.embedding_dim,
        )
        schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="text_bm25",
                function_type=FunctionType.BM25,
                input_field_names=["text"],
                output_field_names=["sparse"],
            )
        )
        indexes = MilvusClient.prepare_index_params()
        indexes.add_index(
            field_name="dense",
            index_type="HNSW",
            metric_type="COSINE",
            params={
                "M": self.config.hnsw_m,
                "efConstruction": self.config.hnsw_ef_construction,
            },
        )
        indexes.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={
                "inverted_index_algo": self.config.sparse_algorithm,
                "bm25_k1": self.config.bm25_k1,
                "bm25_b": self.config.bm25_b,
            },
        )
        for field in METADATA_STRINGS:
            indexes.add_index(field_name=field, index_type="INVERTED")
        for field in DAY_FIELDS:
            indexes.add_index(field_name=field, index_type="STL_SORT")
        self.client.create_collection(
            collection_name=self.config.collection,
            schema=schema,
            index_params=indexes,
            consistency_level="Strong",
            timeout=self.config.timeout_s,
        )
        self._metadata_collections[self.collection] = True

    def validate(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors) or len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError("Need one vector per unique chunk")
        limits = {
            "chunk_id": self.config.id_max_bytes,
            "doc_id": self.config.id_max_bytes,
            "section_id": self.config.section_max_bytes,
            "title": self.config.heading_max_bytes,
            "heading_path": self.config.heading_max_bytes,
            "text": self.config.text_max_bytes,
            **dict.fromkeys(METADATA_STRINGS, self.config.metadata_max_bytes),
        }
        for chunk, vector in zip(chunks, vectors, strict=True):
            if (
                len(vector) != self.settings.retrieval.embedding_dim
                or not all(math.isfinite(value) for value in vector)
                or not any(vector)
            ):
                raise ValueError("Invalid dense vector dimension, values or norm")
            if chunk.effective_from is None:
                raise ValueError(
                    f"Missing section metadata for {chunk.section_id}; run make data-docs"
                )
            for field, maximum in limits.items():
                if len(str(getattr(chunk, field)).encode("utf-8")) > maximum:
                    raise ValueError(
                        f"{field} exceeds its Milvus UTF-8 byte limit: {chunk.chunk_id}"
                    )

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        self._require_physical_writable()
        self.validate(chunks, vectors)
        size = self.config.upsert_batch_size
        for offset in range(0, len(chunks), size):
            rows = [
                {**chunk_to_row(chunk, self.settings.policy_versions.open_end_day), "dense": vector}
                for chunk, vector in zip(
                    chunks[offset : offset + size],
                    vectors[offset : offset + size],
                    strict=True,
                )
            ]
            result = self.client.upsert(
                collection_name=self.config.collection, data=rows, timeout=self.config.timeout_s
            )
            if int(result["upsert_count"]) != len(rows):
                raise RuntimeError("Milvus acknowledged fewer rows than were sent")
        self.client.flush(collection_name=self.config.collection, timeout=self.config.timeout_s)
        self.client.load_collection(
            collection_name=self.config.collection, timeout=self.config.timeout_s
        )

    def count(self) -> int:
        result = self.client.query(
            collection_name=self.read_collection,
            filter="",
            output_fields=["count(*)"],
            consistency_level="Strong",
            timeout=self.config.timeout_s,
        )
        return int(result[0]["count(*)"])

    def _search(
        self,
        data: object,
        field: str,
        metric: str,
        limit: int,
        timeout_s: float | None,
        filters: RetrievalFilters | None,
    ) -> list[SearchHit]:
        if limit <= 0:
            raise ValueError("Search limit must be positive")
        params = {"ef": max(limit, self.config.hnsw_ef_search)} if field == "dense" else {}
        target = self.resolve_read_target(timeout_s=timeout_s)
        expression = (
            filters.to_expr(self.settings.retrieval.filters.category_terms) if filters else ""
        )
        if expression and not self._has_metadata(target, timeout_s):
            raise ValueError("Filtered search requires a metadata-enabled collection")
        response = self.client.search(
            collection_name=target,
            data=[data],
            anns_field=field,
            limit=limit,
            filter=expression,
            search_params={"metric_type": metric, "params": params},
            output_fields=["chunk_id"]
            if self._chunk_snapshot is not None
            else self._output_fields(target, timeout_s),
            consistency_level="Strong",
            timeout=timeout_s if timeout_s is not None else self.config.timeout_s,
        )
        results: list[SearchHit] = []
        for hit in response[0]:
            if self._chunk_snapshot is None:
                fields = row_to_chunk_fields(
                    hit["entity"], self.settings.policy_versions.open_end_day
                )
            else:
                chunk_id = str(hit["entity"]["chunk_id"])
                if chunk_id not in self._chunk_snapshot:
                    raise ValueError("Search result is absent from the verified chunk snapshot")
                fields = self._chunk_snapshot[chunk_id].model_dump()
            results.append(SearchHit(**fields, score=float(hit["distance"])))
        return results

    def search_dense(
        self,
        vector: list[float],
        limit: int | None = None,
        *,
        timeout_s: float | None = None,
        filters: RetrievalFilters | None = None,
    ) -> list[SearchHit]:
        return self._search(
            vector,
            "dense",
            "COSINE",
            self.settings.retrieval.dense_top_k if limit is None else limit,
            timeout_s,
            filters,
        )

    def search_bm25(
        self,
        text: str,
        limit: int | None = None,
        *,
        timeout_s: float | None = None,
        filters: RetrievalFilters | None = None,
    ) -> list[SearchHit]:
        return self._search(
            text,
            "sparse",
            "BM25",
            self.settings.retrieval.bm25_top_k if limit is None else limit,
            timeout_s,
            filters,
        )

    def drop(self) -> None:
        self._require_physical_writable()
        if self.exists():
            if self._aliases():
                raise ValueError("Refusing to drop a collection still referenced by an alias")
            self._assert_owned()
            self.client.drop_collection(collection_name=self.config.collection)
            self._metadata_collections.pop(self.collection, None)

    def _aliases(self) -> list[str]:
        list_aliases = getattr(self.client, "list_aliases", None)
        if list_aliases is None:
            return []
        # pymilvus returns {"aliases": [...], "collection_name": ...}, which is always truthy.
        response = list_aliases(collection_name=self.collection, timeout=self.config.timeout_s)
        aliases = response.get("aliases") if isinstance(response, dict) else response
        if not isinstance(aliases, list) or not all(isinstance(name, str) for name in aliases):
            raise ValueError("Invalid Milvus alias listing")
        return aliases

    def close(self) -> None:
        self.client.close()


def configured_build_id(settings: Settings) -> str | None:
    """A best-effort provenance read for collectors that are about to query Milvus."""
    try:
        store = MilvusStore(settings)
    except Exception:
        return None
    try:
        return store.current_build_id()
    finally:
        store.close()
