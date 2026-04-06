"""Chroma-backed in-memory vector store."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from pptx_gen.ingestion.schemas import ChunkRecord
from pptx_gen.planning.schemas import RetrievedChunk


class InMemoryVectorStore:
    """Thin wrapper around an in-memory Chroma collection."""

    def __init__(self, collection_name: str | None = None, client: Any | None = None) -> None:
        import chromadb

        self.client = client or chromadb.Client()
        self.collection_name = collection_name or f"pptx-gen-{uuid4().hex[:8]}"
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
    ) -> list[RetrievedChunk]:
        results = self.collection.query(
            query_embeddings=[list(map(float, query_embedding))],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
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
                        "page": metadata.get("page"),
                    },
                )
            )
        return retrieved

    @staticmethod
    def _metadata_for_chunk(chunk: ChunkRecord) -> dict[str, Any]:
        return {
            "doc_id": chunk.doc_id,
            "source_id": chunk.source_id,
            "element_id": chunk.element_id,
            "element_type": chunk.element_type.value,
            "page": chunk.page,
            "locator": chunk.locator,
        }
