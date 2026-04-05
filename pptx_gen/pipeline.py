"""Top-level orchestration for ingestion, indexing, and deterministic deck export."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pptx_gen.ingestion.chunker import chunk_document
from pptx_gen.ingestion.parser import parse_source
from pptx_gen.ingestion.schemas import ChunkRecord, IngestionOptions, IngestionRequest
from pptx_gen.indexing.embedder import SentenceTransformerEmbedder, SupportsEmbedding
from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.layout.resolver import resolve_deck_layout
from pptx_gen.layout.schemas import ResolvedDeckLayout
from pptx_gen.planning.prompt_chain import StructuredLLMClient, revise_for_design_quality
from pptx_gen.planning.schemas import PresentationSpec
from pptx_gen.renderer.pptx_exporter import export_pptx
from pptx_gen.renderer.qa import QAReport, validate_export, validate_layout


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


class DeckGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presentation_spec: PresentationSpec
    resolved_layout: ResolvedDeckLayout
    layout_report: QAReport
    export_report: QAReport
    export_job: ExportJob
    output_path: str
    refinement_applied: bool = False
    refinement_status: str = Field(min_length=1)


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


def generate_deck(
    *,
    presentation_spec: PresentationSpec,
    output_path: str | Path,
    template_path: str | Path | None = None,
    enable_refinement: bool = False,
    llm_client: StructuredLLMClient | None = None,
    user_brief: str | None = None,
) -> DeckGenerationResult:
    """Resolve, validate, render, and optionally refine a deck once before delivery."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    first_pass_path = output_path if not enable_refinement else output_path.with_name(f"{output_path.stem}.first-pass{output_path.suffix}")

    first_layout = resolve_deck_layout(presentation_spec)
    first_layout_report = validate_layout(first_layout, style_tokens=presentation_spec.theme.style_tokens)
    first_render_error: Exception | None = None
    try:
        export_pptx(
            layout=first_layout,
            style_tokens=presentation_spec.theme.style_tokens,
            output_path=first_pass_path,
            template_path=template_path,
        )
    except Exception as exc:
        first_render_error = exc

    first_export_report = validate_export(
        first_pass_path,
        layout=first_layout,
        style_tokens=presentation_spec.theme.style_tokens,
        render_error=first_render_error,
    )
    if first_render_error is not None:
        return DeckGenerationResult(
            presentation_spec=presentation_spec,
            resolved_layout=first_layout,
            layout_report=first_layout_report,
            export_report=first_export_report,
            export_job=ExportJob(
                id=_job_id_from_path(output_path),
                kind=ExportKind.RENDER_PPTX,
                status=ExportStatus.FAILED,
                error=ExportError(code="render_failed", message=str(first_render_error)),
            ),
            output_path=str(first_pass_path),
            refinement_applied=False,
            refinement_status="render failed before refinement",
        )

    refinement_status = "refinement disabled"
    resolved_layout = first_layout
    layout_report = first_layout_report
    export_report = first_export_report
    final_spec = presentation_spec
    refinement_applied = False

    if enable_refinement:
        try:
            revised_spec, refinement_status, refinement_applied = revise_for_design_quality(
                presentation_spec,
                qa_report_json=first_export_report.model_dump_json(indent=2),
                render_artifact_path=first_pass_path,
                llm_client=llm_client,
                user_brief=user_brief,
                enabled=True,
            )
        except Exception as exc:
            revised_spec = presentation_spec
            refinement_status = f"refinement skipped: {exc}"
            refinement_applied = False

        if refinement_applied:
            final_spec = revised_spec
            resolved_layout = resolve_deck_layout(final_spec)
            layout_report = validate_layout(resolved_layout, style_tokens=final_spec.theme.style_tokens)
            final_render_error: Exception | None = None
            try:
                export_pptx(
                    layout=resolved_layout,
                    style_tokens=final_spec.theme.style_tokens,
                    output_path=output_path,
                    template_path=template_path,
                )
            except Exception as exc:
                final_render_error = exc
            export_report = validate_export(
                output_path,
                layout=resolved_layout,
                style_tokens=final_spec.theme.style_tokens,
                render_error=final_render_error,
            )
            if final_render_error is not None:
                return DeckGenerationResult(
                    presentation_spec=final_spec,
                    resolved_layout=resolved_layout,
                    layout_report=layout_report,
                    export_report=export_report,
                    export_job=ExportJob(
                        id=_job_id_from_path(output_path),
                        kind=ExportKind.RENDER_PPTX,
                        status=ExportStatus.FAILED,
                        error=ExportError(code="render_failed", message=str(final_render_error)),
                    ),
                    output_path=str(output_path),
                    refinement_applied=True,
                    refinement_status=refinement_status,
                )
        else:
            shutil.copyfile(first_pass_path, output_path)
            export_report = validate_export(
                output_path,
                layout=resolved_layout,
                style_tokens=final_spec.theme.style_tokens,
            )
    else:
        export_report = first_export_report

    export_status = ExportStatus.SUCCESS if export_report.passed else ExportStatus.FAILED
    artifact_urls = [str(output_path)] if output_path.exists() else None
    return DeckGenerationResult(
        presentation_spec=final_spec,
        resolved_layout=resolved_layout,
        layout_report=layout_report,
        export_report=export_report,
        export_job=ExportJob(
            id=_job_id_from_path(output_path),
            kind=ExportKind.RENDER_PPTX,
            status=export_status,
            artifact_urls=artifact_urls if export_status is ExportStatus.SUCCESS else None,
            error=None if export_status is ExportStatus.SUCCESS else ExportError(code="qa_failed", message=export_report.design_summary),
        ),
        output_path=str(output_path),
        refinement_applied=refinement_applied,
        refinement_status=refinement_status,
    )


def _job_id_from_path(output_path: Path) -> str:
    return f"export-{output_path.stem}"
