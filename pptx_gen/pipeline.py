"""Top-level orchestration for the schema-first PPTX generation pipeline."""

from __future__ import annotations

import shutil
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pptx_gen.assets.resolver import AssetManifest, ResolvedAssetBundle, resolve_assets
from pptx_gen.ingestion.chunker import chunk_document
from pptx_gen.ingestion.parser import parse_source
from pptx_gen.ingestion.schemas import ChunkRecord, ContentClassification, IngestionOptions, IngestionRequest
from pptx_gen.indexing.embedder import SentenceTransformerEmbedder, SupportsEmbedding
from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.layout.resolver import resolve_deck_layout
from pptx_gen.layout.schemas import ResolvedDeckLayout, StyleTokens
from pptx_gen.planning.llm_client import build_default_structured_llm_client
from pptx_gen.planning.prompt_chain import (
    StructuredLLMClient,
    build_retrieval_plan,
    collect_deck_brief,
    execute_retrieval_plan,
    generate_outline,
    generate_presentation_spec,
    revise_for_design_quality,
)
from pptx_gen.planning.schemas import DeckBrief, OutlineSpec, PresentationSpec, RetrievalPlan
from pptx_gen.renderer.pptx_exporter import export_pptx
from pptx_gen.renderer.qa import QAReport, validate_export, validate_layout


DEFAULT_STYLE_TOKENS = {
    "fonts": {"heading": "Aptos Display", "body": "Aptos", "mono": "Cascadia Code"},
    "colors": {"bg": "#FFFFFF", "text": "#111111", "accent": "#0A84FF", "muted": "#6B7280"},
    "spacing": {"margin_in": 0.5, "gutter_in": 0.25},
    "images": {"source_policy": "provided_only", "style_prompt": "clean editorial visuals"},
}


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
    artifacts_dir: str
    asset_manifest: AssetManifest
    refinement_applied: bool = False
    refinement_status: str = Field(min_length=1)
    brief: DeckBrief | None = None
    outline: OutlineSpec | None = None
    retrieval_plan: RetrievalPlan | None = None
    ingestion_result: IngestionIndexResult | None = None


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
    output_path: str | Path,
    source_path: str | Path | None = None,
    presentation_spec: PresentationSpec | None = None,
    audience: str | None = None,
    goal: str | None = None,
    tone: str = "executive",
    slide_count_target: int = 6,
    title: str | None = None,
    template_path: str | Path | None = None,
    enable_refinement: bool = False,
    llm_client: StructuredLLMClient | None = None,
    user_brief: str | None = None,
    language: str = "en-US",
    style_tokens: StyleTokens | None = None,
    theme_name: str = "Auto PPT",
    ingest_options: IngestionOptions | None = None,
    embedder: SupportsEmbedding | None = None,
    vector_store: InMemoryVectorStore | None = None,
) -> DeckGenerationResult:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts_dir = output_path.parent / f"{output_path.stem}_artifacts"
    assets_dir = artifacts_dir / "assets"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    style_tokens = style_tokens or StyleTokens(**DEFAULT_STYLE_TOKENS)
    embedder = embedder or SentenceTransformerEmbedder()
    vector_store = vector_store or InMemoryVectorStore()
    requested_llm_client = llm_client
    llm_client = llm_client or build_default_structured_llm_client()
    allow_deterministic_fallback = requested_llm_client is None and llm_client is not None

    brief: DeckBrief | None = None
    outline: OutlineSpec | None = None
    retrieval_plan: RetrievalPlan | None = None
    ingestion_result: IngestionIndexResult | None = None

    if presentation_spec is None:
        if source_path is None:
            raise ValueError("generate_deck requires source_path when presentation_spec is not provided")
        if not audience:
            raise ValueError("generate_deck requires audience when generating from source content")
        if not goal:
            raise ValueError("generate_deck requires goal when generating from source content")

        ingestion_result = ingest_and_index(
            source_path,
            title=title,
            language=language,
            options=ingest_options,
            embedder=embedder,
            vector_store=vector_store,
        )
        planning_inputs = {
            "user_request": user_brief or goal,
            "audience": audience,
            "goal": goal,
            "tone": tone,
            "slide_count_target": slide_count_target,
            "source_corpus_ids": [ingestion_result.source_id],
            "document_title": title or ingestion_result.ingestion_request.document.title,
            "source_texts": [
                chunk.text
                for chunk in ingestion_result.chunks
                if chunk.classification is ContentClassification.AUDIENCE_CONTENT
            ],
        }
        deck_title = title or ingestion_result.ingestion_request.document.title or "Untitled Presentation"
        try:
            brief = collect_deck_brief(llm_client=llm_client, **planning_inputs)
            outline = generate_outline(brief, llm_client=llm_client)
            retrieval_plan = build_retrieval_plan(brief, outline, llm_client=llm_client)
            retrieved_chunks = execute_retrieval_plan(retrieval_plan, vector_store=vector_store, embedder=embedder)
            presentation_spec = generate_presentation_spec(
                brief,
                outline,
                retrieved_chunks,
                deck_title=deck_title,
                style_tokens=style_tokens,
                theme_name=theme_name,
                language=language,
                llm_client=llm_client,
            )
        except Exception:
            if not allow_deterministic_fallback:
                raise
            brief = collect_deck_brief(llm_client=None, **planning_inputs)
            outline = generate_outline(brief, llm_client=None)
            retrieval_plan = build_retrieval_plan(brief, outline, llm_client=None)
            retrieved_chunks = execute_retrieval_plan(retrieval_plan, vector_store=vector_store, embedder=embedder)
            presentation_spec = generate_presentation_spec(
                brief,
                outline,
                retrieved_chunks,
                deck_title=deck_title,
                style_tokens=style_tokens,
                theme_name=theme_name,
                language=language,
                llm_client=None,
            )
        _persist_json(artifacts_dir / "brief.json", brief)
        _persist_json(artifacts_dir / "outline.json", outline)
        _persist_json(artifacts_dir / "retrieval_plan.json", retrieval_plan)
    else:
        if not isinstance(presentation_spec, PresentationSpec):
            presentation_spec = PresentationSpec.model_validate(presentation_spec)

    _persist_json(artifacts_dir / "presentation_spec.json", presentation_spec)

    first_pass_path = output_path if not enable_refinement else output_path.with_name(f"{output_path.stem}.first-pass{output_path.suffix}")
    first_bundle = _resolve_and_validate_assets(presentation_spec, assets_dir)
    layout_report = validate_layout(first_bundle.resolved_layout, style_tokens=presentation_spec.theme.style_tokens)
    _persist_json(artifacts_dir / "layout_report.json", layout_report)
    _persist_json(artifacts_dir / "asset_manifest.json", first_bundle.manifest)

    first_render_error: Exception | None = None
    try:
        export_pptx(
            layout=first_bundle.resolved_layout,
            style_tokens=presentation_spec.theme.style_tokens,
            output_path=first_pass_path,
            template_path=template_path,
        )
    except Exception as exc:
        first_render_error = exc

    export_report = validate_export(
        first_pass_path,
        layout=first_bundle.resolved_layout,
        style_tokens=presentation_spec.theme.style_tokens,
        render_error=first_render_error,
    )
    _persist_json(artifacts_dir / "export_report.json", export_report)
    if first_render_error is not None:
        return _failed_result(
            presentation_spec=presentation_spec,
            resolved_layout=first_bundle.resolved_layout,
            layout_report=layout_report,
            export_report=export_report,
            output_path=first_pass_path,
            artifacts_dir=artifacts_dir,
            asset_manifest=first_bundle.manifest,
            brief=brief,
            outline=outline,
            retrieval_plan=retrieval_plan,
            ingestion_result=ingestion_result,
            message=str(first_render_error),
            refinement_status="render failed before refinement",
            refinement_applied=False,
        )

    refinement_applied = False
    refinement_status = "refinement disabled"
    final_bundle = first_bundle
    final_spec = presentation_spec

    if enable_refinement:
        try:
            revised_spec, refinement_status, refinement_applied = revise_for_design_quality(
                presentation_spec,
                qa_report_json=export_report.model_dump_json(indent=2),
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
            _persist_json(artifacts_dir / "presentation_spec.refined.json", final_spec)
            final_bundle = _resolve_and_validate_assets(final_spec, assets_dir)
            layout_report = validate_layout(final_bundle.resolved_layout, style_tokens=final_spec.theme.style_tokens)
            _persist_json(artifacts_dir / "layout_report.json", layout_report)
            _persist_json(artifacts_dir / "asset_manifest.json", final_bundle.manifest)
            final_render_error: Exception | None = None
            try:
                export_pptx(
                    layout=final_bundle.resolved_layout,
                    style_tokens=final_spec.theme.style_tokens,
                    output_path=output_path,
                    template_path=template_path,
                )
            except Exception as exc:
                final_render_error = exc
            export_report = validate_export(
                output_path,
                layout=final_bundle.resolved_layout,
                style_tokens=final_spec.theme.style_tokens,
                render_error=final_render_error,
            )
            _persist_json(artifacts_dir / "export_report.json", export_report)
            if final_render_error is not None:
                return _failed_result(
                    presentation_spec=final_spec,
                    resolved_layout=final_bundle.resolved_layout,
                    layout_report=layout_report,
                    export_report=export_report,
                    output_path=output_path,
                    artifacts_dir=artifacts_dir,
                    asset_manifest=final_bundle.manifest,
                    brief=brief,
                    outline=outline,
                    retrieval_plan=retrieval_plan,
                    ingestion_result=ingestion_result,
                    message=str(final_render_error),
                    refinement_status=refinement_status,
                    refinement_applied=True,
                )
        else:
            shutil.copyfile(first_pass_path, output_path)
            export_report = validate_export(
                output_path,
                layout=first_bundle.resolved_layout,
                style_tokens=final_spec.theme.style_tokens,
            )
            _persist_json(artifacts_dir / "export_report.json", export_report)
    else:
        pass

    status = ExportStatus.SUCCESS if export_report.passed else ExportStatus.FAILED
    artifact_urls = [str(output_path)] if output_path.exists() and status is ExportStatus.SUCCESS else None
    return DeckGenerationResult(
        presentation_spec=final_spec,
        resolved_layout=final_bundle.resolved_layout,
        layout_report=layout_report,
        export_report=export_report,
        export_job=ExportJob(
            id=_job_id_from_path(output_path),
            kind=ExportKind.RENDER_PPTX,
            status=status,
            artifact_urls=artifact_urls,
            error=None if status is ExportStatus.SUCCESS else ExportError(code="qa_failed", message=export_report.design_summary),
        ),
        output_path=str(output_path),
        artifacts_dir=str(artifacts_dir),
        asset_manifest=final_bundle.manifest,
        refinement_applied=refinement_applied,
        refinement_status=refinement_status,
        brief=brief,
        outline=outline,
        retrieval_plan=retrieval_plan,
        ingestion_result=ingestion_result,
    )


def _resolve_and_validate_assets(spec: PresentationSpec, assets_dir: Path) -> ResolvedAssetBundle:
    layout = resolve_deck_layout(spec)
    return resolve_assets(layout, cache_dir=assets_dir)


def _failed_result(
    *,
    presentation_spec: PresentationSpec,
    resolved_layout: ResolvedDeckLayout,
    layout_report: QAReport,
    export_report: QAReport,
    output_path: Path,
    artifacts_dir: Path,
    asset_manifest: AssetManifest,
    brief: DeckBrief | None,
    outline: OutlineSpec | None,
    retrieval_plan: RetrievalPlan | None,
    ingestion_result: IngestionIndexResult | None,
    message: str,
    refinement_status: str,
    refinement_applied: bool,
) -> DeckGenerationResult:
    return DeckGenerationResult(
        presentation_spec=presentation_spec,
        resolved_layout=resolved_layout,
        layout_report=layout_report,
        export_report=export_report,
        export_job=ExportJob(
            id=_job_id_from_path(output_path),
            kind=ExportKind.RENDER_PPTX,
            status=ExportStatus.FAILED,
            error=ExportError(code="render_failed", message=message),
        ),
        output_path=str(output_path),
        artifacts_dir=str(artifacts_dir),
        asset_manifest=asset_manifest,
        refinement_applied=refinement_applied,
        refinement_status=refinement_status,
        brief=brief,
        outline=outline,
        retrieval_plan=retrieval_plan,
        ingestion_result=ingestion_result,
    )


def _persist_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


def _job_id_from_path(output_path: Path) -> str:
    return f"export-{output_path.stem}"
