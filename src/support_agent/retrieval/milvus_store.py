"""The only module importing pymilvus; dense and lexical index access stays here."""

from __future__ import annotations

import math
from typing import Any, Protocol

from support_agent.config import Settings
from support_agent.retrieval.chunking import Chunk

DESCRIPTION = "support-agent dense+BM25 chunks v1"


class ChunkStore(Protocol):
    def create_or_reset(self) -> None: ...

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def count(self) -> int: ...


class SearchHit(Chunk):
    score: float


class SearchStore(Protocol):
    def search_dense(self, vector: list[float], limit: int) -> list[SearchHit]: ...

    def search_bm25(self, text: str, limit: int) -> list[SearchHit]: ...


class MilvusStore:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        from pymilvus import MilvusClient

        self.settings = settings
        self.config = settings.milvus
        self._chunk_snapshot: dict[str, Chunk] | None = None
        self.client: Any = (
            client
            if client is not None
            else MilvusClient(
                uri=self.config.uri,
                timeout=self.config.timeout_s,
            )
        )

    def server_version(self) -> str:
        return str(self.client.get_server_version(timeout=self.config.timeout_s))

    @property
    def collection(self) -> str:
        return self.config.collection

    def exists(self) -> bool:
        return bool(self.client.has_collection(collection_name=self.config.collection))

    def collection_identity(self) -> str:
        info = self.client.describe_collection(
            collection_name=self.config.collection, timeout=self.config.timeout_s
        )
        if info.get("description") != DESCRIPTION:
            raise ValueError("Expected a support-agent collection")
        return str(info["collection_id"])

    def read_chunks(self) -> list[Chunk]:
        count = self.count()
        if not count:
            return []
        reader = self.client.query_iterator(
            collection_name=self.config.collection,
            filter="",
            batch_size=self.config.query_batch_size,
            output_fields=list(Chunk.model_fields),
            consistency_level="Strong",
            timeout=self.config.timeout_s,
        )
        chunks: list[Chunk] = []
        try:
            while rows := reader.next():
                chunks.extend(Chunk.model_validate(row) for row in rows)
        finally:
            reader.close()
        if len(chunks) != count or len({chunk.chunk_id for chunk in chunks}) != count:
            raise ValueError("Incomplete collection snapshot")
        return chunks

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

    def create_or_reset(self) -> None:
        from pymilvus import DataType, Function, FunctionType, MilvusClient

        if self.client.has_collection(collection_name=self.config.collection):
            self._assert_owned()
            self.client.drop_collection(collection_name=self.config.collection)
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
        self.client.create_collection(
            collection_name=self.config.collection,
            schema=schema,
            index_params=indexes,
            consistency_level="Strong",
            timeout=self.config.timeout_s,
        )

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
        }
        for chunk, vector in zip(chunks, vectors, strict=True):
            if (
                len(vector) != self.settings.retrieval.embedding_dim
                or not all(math.isfinite(value) for value in vector)
                or not any(vector)
            ):
                raise ValueError("Invalid dense vector dimension, values or norm")
            for field, maximum in limits.items():
                if len(str(getattr(chunk, field)).encode("utf-8")) > maximum:
                    raise ValueError(
                        f"{field} exceeds its Milvus UTF-8 byte limit: {chunk.chunk_id}"
                    )

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        self.validate(chunks, vectors)
        size = self.config.upsert_batch_size
        for offset in range(0, len(chunks), size):
            rows = [
                {**chunk.model_dump(), "dense": vector}
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
            collection_name=self.config.collection,
            filter="",
            output_fields=["count(*)"],
            consistency_level="Strong",
            timeout=self.config.timeout_s,
        )
        return int(result[0]["count(*)"])

    def _search(self, data: object, field: str, metric: str, limit: int) -> list[SearchHit]:
        if limit <= 0:
            raise ValueError("Search limit must be positive")
        params = {"ef": max(limit, self.config.hnsw_ef_search)} if field == "dense" else {}
        response = self.client.search(
            collection_name=self.config.collection,
            data=[data],
            anns_field=field,
            limit=limit,
            search_params={"metric_type": metric, "params": params},
            output_fields=["chunk_id"]
            if self._chunk_snapshot is not None
            else list(Chunk.model_fields),
            consistency_level="Strong",
            timeout=self.config.timeout_s,
        )
        results: list[SearchHit] = []
        for hit in response[0]:
            if self._chunk_snapshot is None:
                fields = hit["entity"]
            else:
                chunk_id = str(hit["entity"]["chunk_id"])
                if chunk_id not in self._chunk_snapshot:
                    raise ValueError("Search result is absent from the verified chunk snapshot")
                fields = self._chunk_snapshot[chunk_id].model_dump()
            results.append(SearchHit(**fields, score=float(hit["distance"])))
        return results

    def search_dense(self, vector: list[float], limit: int | None = None) -> list[SearchHit]:
        return self._search(
            vector,
            "dense",
            "COSINE",
            self.settings.retrieval.dense_top_k if limit is None else limit,
        )

    def search_bm25(self, text: str, limit: int | None = None) -> list[SearchHit]:
        return self._search(
            text, "sparse", "BM25", self.settings.retrieval.bm25_top_k if limit is None else limit
        )

    def drop(self) -> None:
        if self.client.has_collection(collection_name=self.config.collection):
            self._assert_owned()
            self.client.drop_collection(collection_name=self.config.collection)

    def close(self) -> None:
        self.client.close()
