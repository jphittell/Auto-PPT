"""Top-level orchestration for Phase 1 ingestion and indexing."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pptx_gen.ingestion.chunker import chunk_document
from pptx_gen.ingestion.parser import parse_source
from pptx_gen.ingestion.schemas import ChunkRecord, IngestionOptions, IngestionRequest
from pptx_gen.indexing.embedder import SentenceTransformerEmbedder, SupportsEmbedding
from pptx_gen.indexing.vector_store import InMemoryVectorStore


class ExportStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"


class ExportKind(str, Enum):
    RENDER_PPTX = "render_pptx"
    RENDER_PDF = "render_pdf"
    VENDOR_EXPORT = "vendor_export"


class ExportError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ExportJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    id: str = Field(min_length=1)
    kind: ExportKind
    status: ExportStatus
    artifact_urls: list[str] | None = None
    error: ExportError | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> "ExportJob":
        if self.status is ExportStatus.IN_PROGRESS and self.artifact_urls:
            raise ValueError("artifact_urls must be absent while status is in_progress")
        return self

    @classmethod
    def ensure_valid_transition(cls, previous: ExportStatus, new: ExportStatus) -> None:
        allowed = {
            ExportStatus.IN_PROGRESS: {ExportStatus.SUCCESS, ExportStatus.FAILED},
            ExportStatus.SUCCESS: set(),
            ExportStatus.FAILED: set(),
        }
        if new not in allowed[previous]:
            raise ValueError(f"invalid status transition: {previous} -> {new}")


class IngestionIndexResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    source_id: str
    ingestion_request: IngestionRequest
    n_elements: int = Field(ge=0)
    n_chunks: int = Field(ge=0)
    chunk_ids: list[str] = Field(default_factory=list)
    chunks: list[ChunkRecord] = Field(default_factory=list)


def ingest_and_index(
    source_path: str | Path,
    *,
    title: str | None = None,
    language: str = "en",
    options: IngestionOptions | None = None,
    embedder: SupportsEmbedding | None = None,
    vector_store: InMemoryVectorStore | None = None,
) -> IngestionIndexResult:
    request = parse_source(source_path, title=title, language=language, options=options)
    chunks = chunk_document(request)

    embedder = embedder or SentenceTransformerEmbedder()
    vector_store = vector_store or InMemoryVectorStore()
    embeddings = embedder.encode([chunk.text for chunk in chunks])
    vector_store.upsert_chunks(chunks, embeddings)

    return IngestionIndexResult(
        doc_id=request.document.elements[0].doc_id,
        source_id=request.source.id,
        ingestion_request=request,
        n_elements=len(request.document.elements),
        n_chunks=len(chunks),
        chunk_ids=[chunk.chunk_id for chunk in chunks],
        chunks=chunks,
    )


def generate_deck(*args: Any, **kwargs: Any) -> None:
    """TODO: connect planning, layout, assets, rendering, and QA stages."""

    raise NotImplementedError("Deck generation is not implemented in Phase 1.")

