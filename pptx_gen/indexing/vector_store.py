"""Chroma-backed vector store with optional disk persistence."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from pptx_gen.ingestion.schemas import ChunkRecord, ContentClassification
from pptx_gen.planning.schemas import RetrievedChunk
from pptx_gen.settings import SETTINGS


_PERSISTENT_CLIENTS: dict[str, Any] = {}
_PERSISTENT_CLIENTS_LOCK = Lock()


def _normalize_collection_name(collection_name: str | None) -> str:
    base = (collection_name or f"pptx-gen-{uuid4().hex[:8]}").strip().lower()
    if not base.startswith("pptx-gen-"):
        base = f"pptx-gen-{base}"
    normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in base)
    normalized = normalized.strip("-_") or f"pptx-gen-{uuid4().hex[:8]}"
    if len(normalized) < 3:
        normalized = f"pptx-gen-{normalized}"
    return normalized[:63]


def _persistent_client(persist_path: str | Path) -> Any:
    import chromadb

    resolved = str(Path(persist_path).expanduser().resolve())
    with _PERSISTENT_CLIENTS_LOCK:
        client = _PERSISTENT_CLIENTS.get(resolved)
        if client is None:
            Path(resolved).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=resolved)
            _PERSISTENT_CLIENTS[resolved] = client
        return client


class InMemoryVectorStore:
    """Thin wrapper around a Chroma collection.

    Despite the historical class name, the default backend can now be either
    an in-memory Chroma client or a disk-backed PersistentClient depending on
    AUTOPPT_VECTOR_STORE_BACKEND.
    """

    def __init__(
        self,
        collection_name: str | None = None,
        client: Any | None = None,
        *,
        backend: str | None = None,
        persist_path: str | Path | None = None,
    ) -> None:
        import chromadb

        resolved_backend = (backend or SETTINGS.vector_store_backend).strip().lower()
        if client is not None:
            self.client = client
        elif resolved_backend == "disk":
            self.client = _persistent_client(persist_path or SETTINGS.vector_store_path)
        elif resolved_backend == "memory":
            self.client = chromadb.Client()
        else:
            raise ValueError(f"Unknown vector store backend: {resolved_backend!r}. Use 'memory' or 'disk'.")
        self.backend = resolved_backend
        self.persist_path = str(persist_path or SETTINGS.vector_store_path)
        self.collection_name = _normalize_collection_name(collection_name)
        self.collection = self.client.get_or_create_collection(name=self.collection_name)

    def upsert_chunks(
        self,
        chunks: Sequence[ChunkRecord],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=[list(map(float, embedding)) for embedding in embeddings],
            metadatas=[self._metadata_for_chunk(chunk) for chunk in chunks],
        )

    def query(
        self,
        *,
        query_embedding: Sequence[float],
        n_results: int = 5,
        exclude_classifications: Sequence[ContentClassification] | None = None,
    ) -> list[RetrievedChunk]:
        where_filter = None
        if exclude_classifications:
            where_filter = {"classification": {"$nin": [classification.value for classification in exclude_classifications]}}
        results = self.collection.query(
            query_embeddings=[list(map(float, query_embedding))],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
            where=where_filter,
        )
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        if not distances:
            distances = [None] * len(ids)

        retrieved: list[RetrievedChunk] = []
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            metadata = metadata or {}
            score = None
            if distance is not None:
                score = max(0.0, min(1.0, 1.0 / (1.0 + float(distance))))
            retrieved.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    text=document,
                    source_id=str(metadata.get("source_id", "")),
                    locator=str(metadata.get("locator", "")),
                    score=score,
                    metadata={
                        "doc_id": metadata.get("doc_id"),
                        "element_id": metadata.get("element_id"),
                        "element_type": metadata.get("element_type"),
                        "classification": metadata.get("classification"),
                        "page": metadata.get("page"),
                    },
                )
            )
        return retrieved

    def merge(self, other: "InMemoryVectorStore") -> None:
        """Copy all entries from *other* into this store."""
        all_data = other.collection.get(include=["documents", "metadatas", "embeddings"])
        ids = all_data.get("ids", [])
        if not ids:
            return
        self.collection.upsert(
            ids=ids,
            documents=all_data.get("documents", []),
            embeddings=all_data.get("embeddings", []),
            metadatas=all_data.get("metadatas", []),
        )

    def count(self) -> int:
        return int(self.collection.count())

    def has_data(self) -> bool:
        return self.count() > 0

    def clear(self) -> None:
        if self.count() == 0:
            return
        ids = self.collection.get().get("ids", [])
        if ids:
            self.collection.delete(ids=ids)

    @staticmethod
    def _metadata_for_chunk(chunk: ChunkRecord) -> dict[str, Any]:
        return {
            "doc_id": chunk.doc_id,
            "source_id": chunk.source_id,
            "element_id": chunk.element_id,
            "element_type": chunk.element_type.value,
            "classification": chunk.classification.value,
            "page": chunk.page,
            "locator": chunk.locator,
        }
