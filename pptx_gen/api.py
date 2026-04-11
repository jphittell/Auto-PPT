"""FastAPI app for local web testing of Auto-PPT."""

from __future__ import annotations

import asyncio
import base64
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

import pptx_gen.pipeline as pipeline_module
from pptx_gen.api_schemas import (
    BrandKitRequest,
    ChatGenerateResponse,
    ChatMessageResponse,
    ExportBlockRequest,
    ExportRequest,
    ExportSlideRequest,
    GenerateDeckRequest,
    HealthResponse,
    IngestResponse,
    OutlineSlideRequest,
    PlanDeckRequest,
    PlanPromptRequest,
    PlanDeckResponse,
    PresentationSpecResponse,
    SlidePreviewRequest,
    SlideSpecResponse,
    TemplateResponse,
    ThemeSummaryResponse,
)
from pptx_gen.ingestion.schemas import ContentClassification
from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.layout.schemas import StyleTokens
from pptx_gen.layout.templates import TEMPLATE_ALIASES, TEMPLATE_REGISTRY, canonical_template_key, list_template_keys
from pptx_gen.planning.prompt_chain import (
    build_retrieval_plan,
    collect_deck_brief,
    execute_retrieval_plan,
    generate_outline,
    generate_presentation_spec,
)
from pptx_gen.planning.llm_client import build_default_structured_llm_client
from pptx_gen.planning.schemas import (
    DeckBrief,
    DeckTheme,
    LayoutIntent,
    OutlineItem,
    OutlineSpec,
    PresentationBlock,
    PresentationBlockKind,
    PresentationSpec,
    RetrievedChunk,
    SlideArchetype,
    SlidePurpose,
    SlideSpec,
    SourceCitation,
)
from pptx_gen.renderer.markdown_strip import strip_markdown


app = FastAPI(title="Auto-PPT API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass(slots=True)
class DraftState:
    draft_id: str
    doc_ids: list[str]
    source_ids: list[str]
    title: str
    goal: str
    audience: str
    tone_label: str
    slide_count: int
    brief: DeckBrief
    outline: OutlineSpec
    created_at: str


_INGESTED_DOCS: dict[str, IngestResponse] = {}
_INGESTED_RESULTS: dict[str, pipeline_module.IngestionIndexResult] = {}
_INGESTED_VECTOR_STORES: dict[str, InMemoryVectorStore] = {}
_DRAFTS: dict[str, DraftState] = {}
_DECKS: dict[str, PresentationSpecResponse] = {}
_RAW_DECK_SPECS: dict[str, PresentationSpec] = {}
_CHAT_SESSIONS: dict[str, list[ChatMessageResponse]] = {}
_EMBEDDER: Any | None = None
_STRUCTURED_LLM_CLIENT: Any | bool | None = None
REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
WEB_INDEX = WEB_DIR / "index.html"
RUNTIME_ASSET_DIR = REPO_ROOT / "out" / "runtime_assets"
ONAC_TEMPLATE_PATH = REPO_ROOT / "Input" / "Assets" / "PPTs" / "ONAC Presentation Template" / "ONAC Presentation Template.pptx"
DECK_DEFAULT_TEMPLATE_IDS = {"headline.evidence", "compare.2col", "kpi.big"}
SPECIALIST_TEMPLATE_IDS = {"exec.summary", "chart.takeaway", "closing.actions", "title.cover", "section.divider"}
FONT_PAIR_MAP = {
    "Georgia/Oracle Sans Tab": ("Georgia", "Oracle Sans Tab"),
    "Inter/Inter": ("Inter", "Inter"),
    "Lato/Merriweather": ("Merriweather", "Lato"),
    "DM Sans/DM Serif Display": ("DM Serif Display", "DM Sans"),
}
BRAND_THEMES = {
    "ONAC": {
        "style_tokens": StyleTokens(**pipeline_module.ONAC_STYLE_TOKENS),
        "template_path": ONAC_TEMPLATE_PATH,
    },
}
BRAND_THEME_ALIASES = {
    "Auto PPT": "ONAC",
    "Default": "ONAC",
}


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest_document(file: UploadFile = File(...)) -> IngestResponse:
    original_name = Path(file.filename or "upload.txt").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".pptx"}:
        raise HTTPException(status_code=400, detail="Only .pdf, .txt, .md, and .pptx uploads are supported.")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / original_name
        temp_path.write_bytes(await file.read())
        doc_vector_store = InMemoryVectorStore()
        result = pipeline_module.ingest_and_index(
            temp_path,
            title=Path(original_name).stem.replace("_", " "),
            embedder=_get_embedder(),
            vector_store=doc_vector_store,
        )

    element_counts = Counter(element.type.value for element in result.ingestion_request.document.elements)
    source_metadata = dict(result.ingestion_request.extensions or {})
    summary = await _generate_document_summary(result)
    response = IngestResponse(
        doc_id=result.doc_id,
        chunk_count=result.n_chunks,
        title=result.ingestion_request.document.title,
        element_types=dict(sorted(element_counts.items())),
        source_format=str(source_metadata.get("source_format") or suffix.removeprefix(".") or "document"),
        slide_count=(
            int(source_metadata["slide_count"])
            if source_metadata.get("slide_count") not in {None, ""}
            else None
        ),
        slide_types=(
            dict(source_metadata["slide_types"])
            if isinstance(source_metadata.get("slide_types"), dict)
            else {}
        ),
        summary=summary,
    )
    _INGESTED_DOCS[result.doc_id] = response
    _INGESTED_RESULTS[result.doc_id] = result
    _INGESTED_VECTOR_STORES[result.doc_id] = doc_vector_store
    return response


@app.post("/api/plan", response_model=PlanDeckResponse)
async def plan_deck(request: PlanDeckRequest) -> PlanDeckResponse:
    return _plan_deck_response(
        doc_ids=request.doc_ids,
        goal=request.goal,
        audience=request.audience,
        tone=request.tone,
        slide_count=request.slide_count,
    )


@app.post("/api/plan/prompt", response_model=PlanDeckResponse)
async def plan_deck_from_prompt(request: PlanPromptRequest) -> PlanDeckResponse:
    ingestion_results = _ingested_results_for(request.doc_ids)
    combined_title = " + ".join(result.ingestion_request.document.title for result in ingestion_results)
    content_chunk_count = sum(
        1 for result in ingestion_results
        for chunk in result.chunks
        if chunk.classification is ContentClassification.AUDIENCE_CONTENT
    )
    inferred = _infer_chat_brief(
        request.prompt,
        combined_title,
        content_chunk_count=content_chunk_count,
        source_context=_source_metadata_for_results(ingestion_results),
    )
    return _plan_deck_response(
        doc_ids=request.doc_ids,
        goal=inferred["goal"],
        audience=inferred["audience"],
        tone=inferred["tone"],
        slide_count=inferred["slide_count"],
    )


def _plan_deck_response(
    *,
    doc_ids: list[str],
    goal: str,
    audience: str,
    tone: float,
    slide_count: int,
) -> PlanDeckResponse:
    ingestion_results = _ingested_results_for(doc_ids)
    combined_title = " + ".join(result.ingestion_request.document.title for result in ingestion_results)
    tone_label = _tone_label_from_score(tone)
    source_ids = [result.source_id for result in ingestion_results]
    source_texts = [
        chunk.text
        for result in ingestion_results
        for chunk in result.chunks
        if chunk.classification is ContentClassification.AUDIENCE_CONTENT
    ]
    source_metadata = _source_metadata_for_results(ingestion_results)

    brief = collect_deck_brief(
        user_request=goal,
        audience=audience,
        goal=goal,
        tone=tone_label,
        slide_count_target=slide_count,
        source_corpus_ids=source_ids,
        document_title=combined_title,
        source_texts=source_texts,
        source_metadata=source_metadata,
        llm_client=_get_optional_structured_llm_client(),
    )
    outline = _normalize_outline_exact_count(
        generate_outline(brief, llm_client=_get_optional_structured_llm_client()),
        slide_count,
        goal,
    )

    created_at = datetime.now().isoformat(timespec="seconds")
    draft_id = f"draft-{uuid4().hex[:10]}"
    _DRAFTS[draft_id] = DraftState(
        draft_id=draft_id,
        doc_ids=list(doc_ids),
        source_ids=source_ids,
        title=combined_title,
        goal=goal,
        audience=audience,
        tone_label=tone_label,
        slide_count=slide_count,
        brief=brief.model_copy(update={"slide_count_target": slide_count}),
        outline=outline,
        created_at=created_at,
    )

    return PlanDeckResponse(
        draft_id=draft_id,
        doc_id=doc_ids[0],
        doc_ids=list(doc_ids),
        title=combined_title,
        goal=goal,
        audience=audience,
        slides=_outline_to_response_slides(
            outline,
            goal=goal,
            audience=audience,
            title=combined_title,
            created_at=created_at,
        ),
        created_at=created_at,
    )


@app.post("/api/generate", response_model=PresentationSpecResponse)
async def generate_deck_from_draft(request: GenerateDeckRequest) -> PresentationSpecResponse:
    import logging
    logger = logging.getLogger("pptx_gen.api")

    draft = _DRAFTS.get(request.draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Unknown draft_id: {request.draft_id}")
    if len(request.outline) != draft.slide_count:
        draft.slide_count = len(request.outline)
        draft.brief = draft.brief.model_copy(update={"slide_count_target": len(request.outline)})

    selected_template_id = canonical_template_key(request.selected_template_id)
    if selected_template_id not in DECK_DEFAULT_TEMPLATE_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported deck-level template: {request.selected_template_id}")

    try:
        outline = _apply_outline_edits(draft, request.outline)
        vector_store = _build_vector_store(draft.doc_ids)
        retrieved_chunks = execute_retrieval_plan(
            build_retrieval_plan(draft.brief, outline, llm_client=_get_optional_structured_llm_client()),
            vector_store=vector_store,
            embedder=_get_embedder(),
        )
        theme_name = request.theme_name or "ONAC"
        _theme_config(theme_name)
        style_tokens = _style_tokens_from_brand_kit(request.brand_kit, theme_name)
        deck_id = f"deck-{draft.doc_ids[0]}-{len(_DECKS) + 1}"
        logo_path = _persist_logo_asset(deck_id, request.brand_kit.logo_data_url)

        spec = generate_presentation_spec(
            draft.brief.model_copy(update={"tone": draft.tone_label, "slide_count_target": draft.slide_count}),
            outline,
            retrieved_chunks,
            deck_title=f"{draft.title} presentation",
            style_tokens=style_tokens,
            theme_name=theme_name,
            language="en-US",
            llm_client=_get_optional_structured_llm_client(),
        )
        spec = _enforce_outline_authority(spec, outline, draft.source_ids)
        spec = _apply_global_template_default(spec, selected_template_id)
        spec = _inject_brand_logo(spec, logo_path)

        response = _to_api_presentation_spec(deck_id, draft.doc_ids, draft.goal, spec)
        _RAW_DECK_SPECS[deck_id] = spec
        _DECKS[deck_id] = response
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("generate_deck_from_draft failed")
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}") from exc


@app.post("/api/slide/preview", response_model=SlideSpecResponse)
async def generate_slide_preview(request: SlidePreviewRequest) -> SlideSpecResponse:
    import logging
    logger = logging.getLogger("pptx_gen.api")

    try:
        purpose = SlidePurpose(request.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported slide purpose: {request.purpose}") from exc

    content_text = request.content.strip()
    chosen_template = canonical_template_key(request.template_id)

    try:
        structured = await _llm_structure_slide_content(
            content=content_text,
            title=request.title,
            audience=request.audience,
            goal=request.goal,
            purpose=purpose,
            selected_template=chosen_template,
        )
        slide = _build_preview_slide(
            slide_id=request.slide_id,
            purpose=purpose,
            headline=structured.get("headline", request.title),
            template_key=chosen_template,
            blocks_data=structured.get("blocks", []),
            speaker_notes=structured.get("speaker_notes", ""),
        )
        return _to_api_slide_spec(slide, index=1)
    except Exception as exc:
        logger.exception("slide preview generation failed")
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {exc}") from exc


@app.post("/api/chat/generate", response_model=ChatGenerateResponse)
async def chat_generate_deck(
    prompt: str = Form(...),
    file: UploadFile = File(...),
) -> ChatGenerateResponse:
    ingest = await ingest_document(file)
    ingestion_result = _INGESTED_RESULTS[ingest.doc_id]
    content_chunk_count = sum(
        1 for chunk in ingestion_result.chunks
        if chunk.classification is ContentClassification.AUDIENCE_CONTENT
    )
    inferred = _infer_chat_brief(
        prompt,
        ingest.title,
        content_chunk_count=content_chunk_count,
        source_context=_source_metadata_for_results([ingestion_result]),
    )
    planned = await plan_deck(
        PlanDeckRequest(
            doc_ids=[ingest.doc_id],
            goal=inferred["goal"],
            audience=inferred["audience"],
            tone=inferred["tone"],
            slide_count=inferred["slide_count"],
        )
    )
    deck = await generate_deck_from_draft(
        GenerateDeckRequest(
            draft_id=planned.draft_id,
            outline=[
                OutlineSlideRequest(
                    id=slide.id,
                    index=slide.index,
                    purpose=slide.purpose,
                    title=slide.title,
                    template_id=slide.template_id,
                )
                for slide in planned.slides
            ],
            theme_name="ONAC",
            selected_template_id=inferred["selected_template_id"],
            brand_kit=BrandKitRequest(
                logo_data_url=None,
                primary_color="#C74634",
                accent_color="#2A2F2F",
                font_pair="Georgia/Oracle Sans Tab",
            ),
        )
    )
    session_id = f"chat-{uuid4().hex[:10]}"
    messages = [
        ChatMessageResponse(role="user", content=prompt),
        ChatMessageResponse(
            role="assistant",
            content=(
                f"Understood. I used {ingest.title} to create a {inferred['slide_count']}-slide deck for "
                f"{inferred['audience']} with a {inferred['goal'].lower()} focus."
            ),
        ),
        ChatMessageResponse(
            role="assistant",
            content=f"The deck is ready with {len(deck.slides)} slides and opens in the editor for refinement.",
        ),
    ]
    _CHAT_SESSIONS[session_id] = messages
    return ChatGenerateResponse(
        session_id=session_id,
        prompt=prompt,
        inferred_goal=inferred["goal"],
        inferred_audience=inferred["audience"],
        inferred_slide_count=inferred["slide_count"],
        messages=messages,
        deck=deck,
    )


@app.get("/api/templates", response_model=list[TemplateResponse])
async def get_templates() -> list[TemplateResponse]:
    return [
        TemplateResponse(
            id=template_key,
            name=_humanize_template_name(template_key),
            alias=_ALIAS_BY_CANONICAL.get(template_key, template_key),
            columns=_template_column_count(template_key),
            description=TEMPLATE_REGISTRY[template_key].description,
            deck_default_allowed=template_key in DECK_DEFAULT_TEMPLATE_IDS,
        )
        for template_key in list_template_keys()
    ]


@app.get("/api/themes", response_model=list[str])
async def get_themes() -> list[str]:
    return sorted(BRAND_THEMES.keys())


@app.get("/api/deck/{deck_id}", response_model=PresentationSpecResponse)
async def get_deck(deck_id: str) -> PresentationSpecResponse:
    deck = _DECKS.get(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail=f"Unknown deck_id: {deck_id}")
    return deck


@app.post("/api/export/{deck_id}", response_model=None)
async def export_deck(deck_id: str, request: ExportRequest) -> Response:
    if deck_id not in _DECKS:
        raise HTTPException(status_code=404, detail=f"Unknown deck_id: {deck_id}")

    api_deck = _DECKS[deck_id]

    if request.format == "pptx":
        planning_spec = _RAW_DECK_SPECS.get(deck_id)
        if planning_spec is None:
            raise HTTPException(status_code=404, detail=f"Missing planning spec for deck_id: {deck_id}")
        export_spec = _merge_export_slides(planning_spec, request.slides)

        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / f"{deck_id}.pptx"
            template_path = _theme_template_path(export_spec.theme.name)
            pipeline_module.generate_deck(
                presentation_spec=export_spec,
                output_path=export_path,
                enable_refinement=False,
                template_path=template_path,
                theme_name=export_spec.theme.name,
            )
            if not export_path.exists():
                raise HTTPException(status_code=500, detail="PPTX export failed.")

            return Response(
                content=export_path.read_bytes(),
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                headers={"Content-Disposition": f'attachment; filename="{deck_id}.pptx"'},
            )

    from pptx_gen.renderer.pdf_exporter import export_deck_to_pdf

    planning_spec = _RAW_DECK_SPECS.get(deck_id)
    if planning_spec is None:
        raise HTTPException(status_code=404, detail=f"Missing planning spec for deck_id: {deck_id}")
    export_spec = _merge_export_slides(planning_spec, request.slides)
    deck_data = _to_api_presentation_spec(deck_id, api_deck.doc_ids, api_deck.goal, export_spec).model_dump()
    pdf_bytes = export_deck_to_pdf(deck_data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{deck_id}.pdf"'},
    )


@app.get("/", include_in_schema=False)
async def serve_frontend_index() -> Response:
    return _serve_frontend_path("")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend_path(full_path: str) -> Response:
    return _serve_frontend_path(full_path)


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = pipeline_module.SentenceTransformerEmbedder()
    return _EMBEDDER


def _get_optional_structured_llm_client():
    global _STRUCTURED_LLM_CLIENT
    if _STRUCTURED_LLM_CLIENT is False:
        return None
    if _STRUCTURED_LLM_CLIENT is None:
        _STRUCTURED_LLM_CLIENT = build_default_structured_llm_client()
    return _STRUCTURED_LLM_CLIENT


def _require_structured_llm_client():
    client = _get_optional_structured_llm_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="No structured LLM client is configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY.",
        )
    return client


async def _generate_document_summary(result: pipeline_module.IngestionIndexResult) -> str:
    """Generate a natural-language summary of an ingested document using the LLM."""
    from pptx_gen.ingestion.schemas import ContentElementType

    elements = result.ingestion_request.document.elements
    title = result.ingestion_request.document.title

    # Collect headings and leading content to form a representative excerpt
    headings = [el.text for el in elements if el.type in (ContentElementType.TITLE, ContentElementType.HEADING)]
    paragraphs = [el.text for el in elements if el.type == ContentElementType.PARAGRAPH and len(el.text.split()) > 8]

    # Build a concise excerpt (first ~2000 chars) for the LLM
    excerpt_parts: list[str] = []
    char_budget = 2000
    for heading in headings[:15]:
        excerpt_parts.append(f"## {heading}")
        char_budget -= len(heading) + 3
        if char_budget <= 0:
            break
    for para in paragraphs[:20]:
        if char_budget <= 0:
            break
        excerpt_parts.append(para)
        char_budget -= len(para)

    excerpt = "\n\n".join(excerpt_parts)

    # Try LLM summary
    try:
        llm_client = _get_optional_structured_llm_client()
        if llm_client is None:
            raise ValueError("No LLM client")

        system = (
            "You summarize documents for presentation authors. Write a clear, informative 3-5 sentence overview "
            "describing what the document covers, its key topics, and the kind of content it contains. "
            "Be specific about the subject matter — mention actual topics, findings, and themes, not just "
            "structural details like page counts. Write in third person."
        )
        user_prompt = f"Document title: {title}\n\nExcerpt:\n{excerpt}"

        if hasattr(llm_client, "anthropic_client"):
            response = llm_client.anthropic_client.messages.create(
                model=llm_client.model,
                max_tokens=300,
                temperature=0.3,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text.strip()
        elif hasattr(llm_client, "openai_client"):
            response = llm_client.openai_client.chat.completions.create(
                model=llm_client.model,
                max_tokens=300,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content.strip()
    except Exception:
        pass

    # Fallback: extractive summary from headings
    if headings:
        topic_list = ", ".join(headings[:6])
        return (
            f'"{title}" covers the following topics: {topic_list}. '
            f"The document contains {len(paragraphs)} substantive sections "
            f"across {result.n_chunks} content segments."
        )
    return f'"{title}" was processed into {result.n_chunks} content segments.'


def _ingested_results_for(doc_ids: list[str]) -> list[pipeline_module.IngestionIndexResult]:
    missing = [doc_id for doc_id in doc_ids if doc_id not in _INGESTED_RESULTS]
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown doc_id(s): {', '.join(missing)}")
    return [_INGESTED_RESULTS[doc_id] for doc_id in doc_ids]


def _source_metadata_for_results(
    ingestion_results: list[pipeline_module.IngestionIndexResult],
) -> dict[str, Any]:
    if len(ingestion_results) != 1:
        return {}
    extensions = dict(ingestion_results[0].ingestion_request.extensions or {})
    if str(extensions.get("source_format", "")).lower() != "pptx":
        return {}
    return extensions


def _build_vector_store(doc_ids: list[str]) -> InMemoryVectorStore:
    # If there's only one doc and we already have its vector store cached, reuse it
    if len(doc_ids) == 1 and doc_ids[0] in _INGESTED_VECTOR_STORES:
        return _INGESTED_VECTOR_STORES[doc_ids[0]]

    # For multi-doc decks, merge cached stores when available, only re-embed misses
    vector_store = InMemoryVectorStore()
    embedder = _get_embedder()
    for doc_id in doc_ids:
        cached = _INGESTED_VECTOR_STORES.get(doc_id)
        if cached is not None:
            vector_store.merge(cached)
        else:
            result = _INGESTED_RESULTS[doc_id]
            embeddings = embedder.encode([chunk.text for chunk in result.chunks])
            vector_store.upsert_chunks(result.chunks, embeddings)
    return vector_store


def _outline_to_response_slides(
    outline: OutlineSpec,
    *,
    goal: str,
    audience: str,
    title: str,
    created_at: str,
) -> list[SlideSpecResponse]:
    return [
        SlideSpecResponse(
            id=item.slide_id,
            index=index,
            purpose=item.purpose.value,
            archetype=item.archetype.value if item.archetype else None,
            title=item.headline,
            blocks=_outline_preview_blocks(
                item,
                outline=outline,
                goal=goal,
                audience=audience,
                title=title,
                created_at=created_at,
            ),
            template_id=_recommended_outline_template(item),
            speaker_notes=None,
        )
        for index, item in enumerate(outline.outline, start=1)
    ]


def _apply_outline_edits(draft: DraftState, outline_updates: list[OutlineSlideRequest]) -> OutlineSpec:
    base_by_id = {item.slide_id: item for item in draft.outline.outline}
    requested_ids = [item.id for item in sorted(outline_updates, key=lambda item: item.index)]
    if set(requested_ids) != set(base_by_id):
        raise HTTPException(status_code=400, detail="Outline slides must match the planned draft.")

    outline_items: list[OutlineItem] = []
    explicit_template_by_slide_id: dict[str, str] = {}
    for update in sorted(outline_updates, key=lambda item: item.index):
        base = base_by_id[update.id]
        chosen_template = canonical_template_key(update.template_id or base.template_key or "headline.evidence")
        if chosen_template != canonical_template_key(base.template_key or "headline.evidence"):
            explicit_template_by_slide_id[base.slide_id] = chosen_template
        outline_items.append(
            OutlineItem(
                slide_id=base.slide_id,
                purpose=base.purpose,
                archetype=base.archetype,
                headline=update.title,
                message=base.message,
                evidence_queries=list(base.evidence_queries),
                template_key=chosen_template,
            )
        )
    extensions = dict(draft.outline.extensions or {})
    if explicit_template_by_slide_id:
        extensions["explicit_template_by_slide_id"] = explicit_template_by_slide_id
    return OutlineSpec(
        outline=outline_items,
        questions_for_user=list(draft.outline.questions_for_user),
        extensions=extensions or None,
    )


def _normalize_outline_exact_count(outline: OutlineSpec, target_count: int, goal: str) -> OutlineSpec:
    items = list(outline.outline)
    while len(items) > target_count:
        removable_index = next(
            (index for index in range(len(items) - 1, -1, -1) if items[index].purpose is SlidePurpose.CONTENT),
            len(items) - 1,
        )
        items.pop(removable_index)

    insert_at = next((index for index, item in enumerate(items) if item.purpose in {SlidePurpose.SUMMARY, SlidePurpose.CLOSING}), len(items))
    while len(items) < target_count:
        detail_number = 1 + sum(1 for item in items if item.purpose is SlidePurpose.CONTENT)
        message = f"{goal} supporting detail {detail_number}"
        items.insert(
            insert_at,
            OutlineItem(
                slide_id=f"s{len(items) + 1}",
                purpose=SlidePurpose.CONTENT,
                headline=f"Supporting Detail {detail_number}",
                message=message,
                evidence_queries=[message, f"{message} evidence"],
                template_key="headline.evidence",
            ),
        )
        insert_at += 1

    normalized = [
        item.model_copy(update={"slide_id": f"s{index}"})
        for index, item in enumerate(items, start=1)
    ]
    return OutlineSpec(
        outline=normalized,
        questions_for_user=list(outline.questions_for_user),
        extensions=outline.extensions,
    )


def _style_tokens_from_brand_kit(brand_kit: BrandKitRequest, theme_name: str = "ONAC") -> StyleTokens:
    theme = _theme_config(theme_name)
    base_tokens: StyleTokens = theme["style_tokens"]
    font_pair = brand_kit.font_pair or f"{base_tokens.fonts.heading}/{base_tokens.fonts.body}"
    heading_font, body_font = FONT_PAIR_MAP.get(font_pair, (base_tokens.fonts.heading, base_tokens.fonts.body))
    return StyleTokens(
        fonts={
            "heading": heading_font,
            "body": body_font,
            "mono": base_tokens.fonts.mono,
        },
        colors={
            "bg": base_tokens.colors.bg,
            "text": base_tokens.colors.text,
            "accent": brand_kit.primary_color or base_tokens.colors.accent,
            "muted": brand_kit.accent_color or base_tokens.colors.muted,
        },
        spacing=base_tokens.spacing.model_dump(),
        images=base_tokens.images.model_dump(),
    )


def _theme_config(theme_name: str) -> dict[str, Any]:
    canonical_theme_name = BRAND_THEME_ALIASES.get(theme_name, theme_name)
    try:
        return BRAND_THEMES[canonical_theme_name]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported theme_name: {theme_name}") from exc


def _theme_template_path(theme_name: str) -> str | None:
    template_path = _theme_config(theme_name).get("template_path")
    return str(template_path) if template_path else None


def _persist_logo_asset(deck_id: str, logo_data_url: str | None) -> str | None:
    if not logo_data_url:
        return None
    try:
        header, payload = logo_data_url.split(",", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid logo data URL.") from exc
    if ";base64" not in header:
        raise HTTPException(status_code=400, detail="Logo data URL must be base64 encoded.")

    extension = ".png"
    if "image/jpeg" in header:
        extension = ".jpg"
    elif "image/webp" in header:
        extension = ".webp"

    RUNTIME_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    logo_path = RUNTIME_ASSET_DIR / f"{deck_id}-logo{extension}"
    logo_path.write_bytes(base64.b64decode(payload))
    return str(logo_path)


def _inject_brand_logo(spec: PresentationSpec, logo_path: str | None) -> PresentationSpec:
    if not logo_path:
        return spec
    slides: list[SlideSpec] = []
    injected = False
    for slide in spec.slides:
        if not injected and slide.purpose is SlidePurpose.TITLE and slide.blocks:
            first = slide.blocks[0]
            slides.append(
                slide.model_copy(
                    update={
                        "blocks": [
                            first.model_copy(update={"content": {**first.content, "logo": logo_path}}),
                            *slide.blocks[1:],
                        ]
                    }
                )
            )
            injected = True
        else:
            slides.append(slide)
    return spec.model_copy(update={"slides": slides})


def _enforce_outline_authority(
    spec: PresentationSpec,
    outline: OutlineSpec,
    source_ids: list[str],
) -> PresentationSpec:
    existing_by_id = {slide.slide_id: slide for slide in spec.slides}
    # Build a positional index so we can match LLM slides that used different IDs
    existing_by_index = {index: slide for index, slide in enumerate(spec.slides)}
    used_positions: set[int] = set()

    slides: list[SlideSpec] = []
    for outline_index, item in enumerate(outline.outline):
        slide = existing_by_id.get(item.slide_id)
        # If no ID match, try matching by position — the LLM often generates
        # correct content but with different slide_id values
        if slide is None and outline_index in existing_by_index:
            positional = existing_by_index[outline_index]
            if positional.slide_id not in {i.slide_id for i in outline.outline}:
                slide = positional
                used_positions.add(outline_index)
        if slide is None:
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
                    archetype=item.archetype,
                    layout_intent=LayoutIntent(template_key=item.template_key or "headline.evidence", strict_template=True),
                    headline=item.headline,
                    speaker_notes=item.message,
                    blocks=[
                        PresentationBlock(
                            block_id="b1",
                            kind=PresentationBlockKind.TEXT,
                            content={"text": item.message},
                            source_citations=_fallback_citation(source_ids) if item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY, SlidePurpose.CLOSING} else [],
                        )
                    ],
                )
            )
            continue
        slides.append(
            slide.model_copy(
                update={
                    "slide_id": item.slide_id,
                    "purpose": item.purpose,
                    "archetype": item.archetype or slide.archetype,
                    "headline": item.headline,
                }
            )
        )
    return spec.model_copy(update={"slides": slides, "extensions": outline.extensions})


def _apply_global_template_default(spec: PresentationSpec, selected_template_id: str) -> PresentationSpec:
    slides: list[SlideSpec] = []
    explicit_template_by_slide_id = {
        slide_id: canonical_template_key(template_key)
        for slide_id, template_key in (spec.extensions or {}).get("explicit_template_by_slide_id", {}).items()
    }
    for slide in spec.slides:
        if slide.purpose not in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}:
            slides.append(slide)
            continue
        current_template = canonical_template_key(slide.layout_intent.template_key)
        if slide.slide_id in explicit_template_by_slide_id:
            # User explicitly changed the template in the outline editor.
            chosen_template = explicit_template_by_slide_id[slide.slide_id]
        elif current_template in SPECIALIST_TEMPLATE_IDS:
            # Specialist templates (exec.summary, chart.takeaway, etc.) are
            # assigned by the outline heuristic — always keep them.
            chosen_template = current_template
        elif current_template in DECK_DEFAULT_TEMPLATE_IDS and current_template != "headline.evidence":
            # The outline heuristic chose a specific deck-level template
            # (e.g., compare.2col, kpi.big) — preserve the variety.
            chosen_template = current_template
        else:
            # Generic fallback — apply the user's deck-level selection.
            chosen_template = selected_template_id
        slides.append(_coerce_slide_for_template(slide, chosen_template))
    return spec.model_copy(update={"slides": slides})


def _coerce_slide_for_template(slide: SlideSpec, template_key: str) -> SlideSpec:
    canonical = canonical_template_key(template_key or "headline.evidence")

    text_items: list[str] = []
    cards: list[dict[str, str]] = []
    chart_data: dict[str, Any] | None = None
    table_data: dict[str, Any] | None = None
    takeaway: str | None = None
    citations: list[SourceCitation] = []

    for block in slide.blocks:
        citations.extend(block.source_citations)
        if block.kind is PresentationBlockKind.CALLOUT:
            if isinstance(block.content.get("cards"), list):
                for card in block.content.get("cards", []):
                    if isinstance(card, dict):
                        cards.append(
                            {
                                "title": str(card.get("title", "")).strip(),
                                "text": str(card.get("text", "")).strip(),
                            }
                        )
            elif block.content.get("text"):
                takeaway = str(block.content.get("text", "")).strip()
        elif block.kind is PresentationBlockKind.BULLETS:
            text_items.extend(str(item).strip() for item in block.content.get("items", []) if str(item).strip())
        elif block.kind is PresentationBlockKind.TEXT:
            text = str(block.content.get("text", "")).strip()
            if text:
                text_items.append(text)
        elif block.kind is PresentationBlockKind.CHART:
            chart_data = dict(block.content)
        elif block.kind is PresentationBlockKind.TABLE:
            table_data = dict(block.content)
        elif block.kind is PresentationBlockKind.KPI_CARDS:
            for item in block.content.get("items", []):
                if isinstance(item, dict):
                    label = str(item.get("label", "")).strip()
                    value = str(item.get("value", "")).strip()
                    cards.append({"title": label or value, "text": value or label})

    if table_data and not text_items:
        rows = table_data.get("rows", [])
        for row in rows[:4]:
            if isinstance(row, list):
                text_items.append(" | ".join(str(cell) for cell in row if str(cell).strip()))
    if not text_items and slide.headline:
        text_items.append(slide.headline)

    def _fallback_callout() -> str:
        return takeaway or (text_items[-1] if text_items else slide.headline)

    if canonical == "title.cover":
        blocks = [
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.TEXT,
                content={"subtitle": text_items[0] if text_items else "", "presenter": "", "date": datetime.now().strftime("%B %d, %Y")},
                source_citations=[],
            )
        ]
    elif canonical == "section.divider":
        blocks = [
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.TEXT,
                content={"tagline": text_items[0] if text_items else "", "footer_info": ""},
                source_citations=[],
            )
        ]
    elif canonical == "exec.summary":
        summary_cards = cards[:3]
        if len(summary_cards) < 3:
            for item in text_items[:3 - len(summary_cards)]:
                summary_cards.append({"title": " ".join(item.split()[:4]) or "Point", "text": item})
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items[:5]}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
            PresentationBlock(block_id="b3", kind=PresentationBlockKind.CALLOUT, content={"cards": summary_cards[:3]}, source_citations=citations),
        ]
    elif canonical == "headline.evidence":
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
        ]
    elif canonical == "kpi.big":
        metric_texts = text_items[:3]
        while len(metric_texts) < 3:
            metric_texts.append(slide.headline)
        blocks = [
            PresentationBlock(block_id=f"b{index + 1}", kind=PresentationBlockKind.TEXT, content={"text": metric_texts[index]}, source_citations=citations[:1] if citations else [])
            for index in range(3)
        ]
    elif canonical == "compare.2col":
        midpoint = max(1, (len(text_items) + 1) // 2)
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items[:midpoint]}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.BULLETS, content={"items": text_items[midpoint:] or text_items[:1]}, source_citations=citations),
        ]
    elif canonical == "chart.takeaway":
        blocks = [
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.CHART,
                content=chart_data or {"chart_type": "bar", "data": [{"label": f"Point {index + 1}", "value": index + 1} for index in range(min(max(len(text_items), 1), 3))]},
                source_citations=citations,
            ),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
        ]
    else:
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
        ]
        canonical = "closing.actions" if canonical == "closing.actions" else "headline.evidence"

    return slide.model_copy(update={"layout_intent": LayoutIntent(template_key=canonical, strict_template=True), "blocks": blocks})


def _slide_summary_items(slide: SlideSpec) -> list[str]:
    items: list[str] = []
    for block in slide.blocks:
        text = _block_summary_text(block)
        if text and text not in items:
            items.append(text)
        if len(items) == 3:
            break
    if not items:
        items.append(slide.headline)
    return items


def _block_summary_text(block: PresentationBlock) -> str:
    content = block.content
    if block.kind is PresentationBlockKind.BULLETS:
        values = [str(item) for item in content.get("items", []) if item]
        return "; ".join(values[:2])
    if block.kind is PresentationBlockKind.KPI_CARDS:
        values = [f"{item.get('label', '')}: {item.get('value', '')}" for item in content.get("items", [])]
        return "; ".join(values[:2])
    if block.kind is PresentationBlockKind.TABLE:
        rows = [" | ".join(str(cell) for cell in row) for row in content.get("rows", [])]
        return "; ".join(rows[:2])
    if block.kind is PresentationBlockKind.CHART:
        series = [f"{item.get('label', '')}: {item.get('value', '')}" for item in content.get("series", [])]
        return "; ".join(series[:2])
    for field in ("text", "label", "subtitle", "tagline", "footer_info"):
        value = content.get(field)
        if value:
            return str(value)
    return ""


def _theme_name(template_key: str) -> str:
    return "ONAC"


def _outline_preview_blocks(
    item: OutlineItem,
    *,
    outline: OutlineSpec,
    goal: str,
    audience: str,
    title: str,
    created_at: str,
) -> list[dict[str, str | None]]:
    if item.purpose is SlidePurpose.TITLE:
        title_lines = [
            f"Subtitle: {goal}",
            f"Audience: {audience}",
            f"Deck: {title}",
            f"Date: {created_at[:10]}",
        ]
        return [
            {
                "id": f"{item.slide_id}-title-meta",
                "kind": "text",
                "content": "\n".join(title_lines),
                "citation": None,
            }
        ]

    if item.purpose is SlidePurpose.CLOSING:
        agenda_lines = [
            outline_item.headline
            for outline_item in outline.outline
            if outline_item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}
        ][:5]
        return [
            {
                "id": f"{item.slide_id}-agenda",
                "kind": "bullets",
                "content": "\n".join(f"\u2022 {line}" for line in agenda_lines),
                "citation": None,
            }
        ]

    bullets = [item.message, *item.evidence_queries[:2]]
    return [
        {
            "id": f"{item.slide_id}-outline",
            "kind": "bullets",
            "content": "\n".join(f"\u2022 {_trim_outline_line(line)}" for line in bullets if line),
            "citation": None,
        }
    ]


def _recommended_outline_template(item: OutlineItem) -> str:
    if item.purpose is SlidePurpose.TITLE:
        return "title.cover"
    if item.purpose is SlidePurpose.CLOSING:
        return "closing.actions"
    if item.archetype is SlideArchetype.EXECUTIVE_SUMMARY:
        return "exec.summary"
    if item.archetype is SlideArchetype.COMPARISON:
        return "compare.2col"
    if item.archetype is SlideArchetype.METRICS:
        return "kpi.big"
    if item.archetype is SlideArchetype.CHART:
        return "chart.takeaway"
    if item.purpose is SlidePurpose.SUMMARY:
        return "closing.actions"

    headline = f"{item.headline} {item.message}".lower()
    if any(term in headline for term in ("metric", "kpi", "score", "rate", "roi", "growth")):
        return "kpi.big"
    if any(term in headline for term in ("chart", "trend", "graph", "plot")):
        return "chart.takeaway"
    if any(term in headline for term in ("compare", "comparison", "option", "tradeoff", "landscape", "tools")):
        return "compare.2col"
    if any(term in headline for term in ("overview", "summary", "executive", "capability")):
        return "exec.summary"
    return canonical_template_key(item.template_key or "headline.evidence")


def _trim_outline_line(value: str) -> str:
    words = [word for word in str(value).replace("\n", " ").split() if word]
    return " ".join(words[:12])


def _fallback_citation(source_ids: list[str]) -> list[SourceCitation]:
    source_id = source_ids[0] if source_ids else "source"
    return [SourceCitation(source_id=source_id, locator=f"{source_id}:page1")]


async def _llm_structure_slide_content(
    *,
    content: str,
    title: str,
    audience: str,
    goal: str,
    purpose: SlidePurpose,
    selected_template: str,
) -> dict[str, Any]:
    """Use the structured client to turn editor notes into one well-formed preview slide."""
    llm_client = _get_optional_structured_llm_client()
    if llm_client is None:
        return _fallback_structure_content(content, title, selected_template)

    system = (
        "You are a professional presentation writer. "
        "Given raw editor notes, produce a polished slide with a clear headline, speaker notes, and structured blocks. "
        "CRITICAL: Do NOT copy-paste the raw notes. Synthesize, summarize, and rewrite them into concise, "
        "audience-facing language with an executive tone. Each bullet should be 10-20 words of original phrasing. "
        "Respect the selected template key and format blocks to fit that layout."
    )
    user_prompt = (
        f"Goal: {goal}\n"
        f"Audience: {audience}\n"
        f"Slide purpose: {purpose.value}\n"
        f"Selected template key: {selected_template}\n"
        f"Title seed: {title}\n\n"
        f"Template guidance:\n{_preview_template_guidance(selected_template)}\n\n"
        "Return a JSON object with: headline (str), speaker_notes (str), blocks (list of block objects). "
        "Do NOT wrap in a PresentationSpec. The response IS the slide object directly.\n\n"
        f"Raw editor notes to synthesize (do NOT echo verbatim):\n{content}"
    )

    try:
        result = llm_client.generate_json(
            system_prompt=system,
            user_prompt=user_prompt,
            schema_name="SlidePreviewLLMResponse",
        )
        if not isinstance(result, dict):
            raise ValueError("Structured preview returned a non-object payload")

        blocks_payload = result.get("blocks", [])
        if not isinstance(blocks_payload, list):
            raise ValueError("Structured preview blocks must be a list")

        normalized_blocks: list[dict[str, Any]] = []
        for block in blocks_payload:
            if not isinstance(block, dict):
                raise ValueError("Structured preview blocks must contain objects")
            kind = block.get("kind", "text")
            if kind == "callout":
                if isinstance(block.get("cards"), list):
                    normalized_blocks.append({"kind": kind, "cards": block.get("cards", [])})
                else:
                    normalized_blocks.append({"kind": kind, "text": block.get("text", "")})
            elif kind in {"bullets", "kpi_cards"}:
                normalized_blocks.append({"kind": kind, "items": block.get("items", [])})
            elif kind == "table":
                normalized_blocks.append({"kind": kind, "columns": block.get("columns", []), "rows": block.get("rows", [])})
            elif kind == "chart":
                normalized_blocks.append({"kind": kind, "chart_type": block.get("chart_type", "bar"), "series": block.get("series", [])})
            elif kind == "quote":
                normalized_blocks.append({"kind": kind, "text": block.get("text", ""), "attribution": block.get("attribution", "")})
            else:
                normalized_blocks.append({"kind": kind, "text": block.get("text", "")})
        return {
            "headline": result.get("headline", title),
            "template_id": selected_template,
            "speaker_notes": result.get("speaker_notes", ""),
            "blocks": normalized_blocks,
        }
    except Exception as llm_exc:
        import logging
        logging.getLogger("pptx_gen.api").warning("LLM slide preview failed, using fallback: %s", llm_exc)
        return _fallback_structure_content(content, title, selected_template)


def _preview_template_guidance(template_key: str) -> str:
    guidance = {
        "title.cover": "Use one high-level subtitle-style text block.",
        "section.divider": "Use one short transition statement or subhead.",
        "headline.evidence": "Use a bullets block plus a short takeaway callout.",
        "exec.summary": "Use three summary cards plus one brief takeaway callout.",
        "compare.2col": "Split the content into two clear sides or perspectives.",
        "chart.takeaway": "Use a chart block if numeric evidence exists plus a short takeaway callout.",
        "kpi.big": "Use kpi_cards with three metrics and short labels.",
        "closing.actions": "Use bullets for concrete next steps or recommendations.",
        "quote.photo": "Use one quote block and optionally a short supporting text or image placeholder.",
        "quote.texture": "Use one strong quote block with attribution if available.",
        "impact.statement": "Use one bold statement block only.",
        "content.3col": "Use three cards or three short text blocks, one per column.",
        "content.4col": "Use four cards or four short text blocks, one per column.",
        "icons.3": "Use three short cards with a heading and brief body text.",
        "icons.4": "Use four short cards with a heading and brief body text.",
        "content.photo": "Use text or bullets for the main message and one image placeholder block.",
        "bold.photo": "Use one bold statement block and one image placeholder block.",
        "split.content": "Use two contrasting text blocks, one for each side.",
        "agenda.table": "Use a concise table with row labels and descriptions.",
        "screenshot": "Use one brief intro text block and one image placeholder block.",
    }
    return guidance.get(template_key, "Format the content to fit the selected layout cleanly and concisely.")


def _fallback_structure_content(content: str, title: str, template: str) -> dict[str, Any]:
    """Structure content into slide blocks without LLM."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    bullet_lines = [line.lstrip("-•* ").strip() for line in lines if line.startswith(("-", "•", "*"))]
    plain_lines = [line for line in lines if not line.startswith(("-", "•", "*"))]

    sentences: list[str] = []
    for line in lines:
        sentences.extend(re.split(r"(?<=[.!?])\s+", line))
    sentences = [s.strip() for s in sentences if len(s.split()) >= 5]
    points = bullet_lines or plain_lines or sentences or [content.strip() or title]

    def cards_from_points(count: int) -> list[dict[str, str]]:
        cards: list[dict[str, str]] = []
        for point in points[:count]:
            words = point.split()
            cards.append({
                "title": " ".join(words[:4]) or "Point",
                "text": " ".join(words[:18]) or point,
            })
        while len(cards) < count:
            cards.append({"title": f"Point {len(cards)+1}", "text": "Add supporting detail."})
        return cards

    def bullets_from_points(count: int = 5) -> list[str]:
        values = [" ".join(point.split()[:16]) for point in points[:count] if point.strip()]
        return values or [title]

    if template == "kpi.big":
        items = []
        for sentence in points[:3]:
            numbers = re.findall(r"\b[\d,.]+[%$]?\b", sentence)
            value = numbers[0] if numbers else str(len(items) + 1)
            label = " ".join(sentence.split()[:6])
            items.append({"value": value, "label": label})
        while len(items) < 3:
            items.append({"value": "N/A", "label": f"Metric {len(items)+1}"})
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "kpi_cards", "items": items}],
        }

    if template == "compare.2col":
        midpoint = max(1, (len(points) + 1) // 2)
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [
                {"kind": "bullets", "items": [" ".join(point.split()[:16]) for point in points[:midpoint]]},
                {"kind": "bullets", "items": [" ".join(point.split()[:16]) for point in points[midpoint:]] or ["Add right-side comparison"]},
            ],
        }

    if template == "exec.summary":
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [
                {"kind": "bullets", "items": bullets_from_points(4)},
                {"kind": "callout", "text": " ".join((sentences[:1] or points[:1]))[:160]},
                {"kind": "callout", "cards": cards_from_points(3)},
            ],
        }

    if template in {"content.3col", "icons.3"}:
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "callout", "cards": cards_from_points(3)}]}

    if template in {"content.4col", "icons.4"}:
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "callout", "cards": cards_from_points(4)}]}

    if template == "agenda.table":
        rows = [[f"Item {index + 1}", " ".join(point.split()[:14])] for index, point in enumerate(points[:5])]
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "table", "columns": ["Section", "Focus"], "rows": rows}],
        }

    if template == "chart.takeaway":
        series = []
        for index, point in enumerate(points[:4], start=1):
            numbers = re.findall(r"\b[\d,.]+[%$]?\b", point)
            value_token = (numbers[0] if numbers else str(index)).replace("$", "").replace("%", "")
            try:
                value = float(value_token.replace(",", ""))
            except ValueError:
                value = float(index)
            series.append({"label": f"Point {index}", "value": value})
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [
                {"kind": "chart", "chart_type": "bar", "series": series or [{"label": "Point 1", "value": 1.0}]},
                {"kind": "callout", "text": " ".join((sentences[:1] or points[:1]))[:160]},
            ],
        }

    if template in {"quote.photo", "quote.texture"}:
        quote_text = " ".join((sentences[:1] or points[:1]))[:180]
        blocks = [{"kind": "quote", "text": quote_text, "attribution": title}]
        if template == "quote.photo":
            blocks.append({"kind": "image", "text": "Photo"})
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": blocks}

    if template == "impact.statement":
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "text", "text": " ".join((sentences[:1] or points[:1]))[:160]}]}

    if template in {"content.photo", "bold.photo", "screenshot"}:
        primary_block = (
            {"kind": "bullets", "items": bullets_from_points(4)}
            if template == "content.photo"
            else {"kind": "text", "text": " ".join((sentences[:1] or points[:1]))[:180]}
        )
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [primary_block, {"kind": "image", "text": "Image"}],
        }

    if template == "split.content":
        midpoint = max(1, (len(points) + 1) // 2)
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [
                {"kind": "text", "text": " ".join(points[:midpoint])[:180]},
                {"kind": "text", "text": " ".join(points[midpoint:])[:180] or "Add contrasting point"},
            ],
        }

    if template in {"title.cover", "section.divider"}:
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "text", "text": " ".join((sentences[:1] or points[:1]))[:160]}],
        }

    if template == "closing.actions":
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "bullets", "items": bullets_from_points(5)}],
        }

    return {
        "headline": title,
        "template_id": template,
        "speaker_notes": "",
        "blocks": [
            {"kind": "bullets", "items": bullets_from_points(5)},
            {"kind": "callout", "text": " ".join((sentences[:1] or points[:1]))[:160]},
        ],
    }


def _build_preview_slide(
    *,
    slide_id: str,
    purpose: SlidePurpose,
    headline: str,
    template_key: str,
    blocks_data: list[dict[str, Any]],
    speaker_notes: str,
) -> SlideSpec:
    """Build a SlideSpec from structured block data."""
    blocks: list[PresentationBlock] = []
    for i, block_data in enumerate(blocks_data):
        kind_str = block_data.get("kind", "text")
        try:
            kind = PresentationBlockKind(kind_str)
        except ValueError:
            kind = PresentationBlockKind.TEXT

        if kind == PresentationBlockKind.CALLOUT:
            if isinstance(block_data.get("cards"), list):
                content = {"cards": block_data.get("cards", [])}
            else:
                content = {"text": block_data.get("text", "")}
            if block_data.get("tone_hint"):
                content["tone_hint"] = block_data["tone_hint"]
        elif kind == PresentationBlockKind.BULLETS:
            content = {"items": block_data.get("items", [])}
        elif kind == PresentationBlockKind.KPI_CARDS:
            content = {"items": block_data.get("items", [])}
        elif kind == PresentationBlockKind.TABLE:
            content = {"columns": block_data.get("columns", []), "rows": block_data.get("rows", [])}
        elif kind == PresentationBlockKind.CHART:
            content = {"chart_type": block_data.get("chart_type", "bar"), "series": block_data.get("series", [])}
        elif kind == PresentationBlockKind.QUOTE:
            content = {"text": block_data.get("text", ""), "attribution": block_data.get("attribution", "")}
        elif kind == PresentationBlockKind.IMAGE:
            content = {"text": block_data.get("text", "Image")}
        else:
            content = {"text": block_data.get("text", "")}

        blocks.append(PresentationBlock(
            block_id=f"b{i+1}",
            kind=kind,
            content=content,
        ))

    if not blocks:
        blocks.append(PresentationBlock(
            block_id="b1",
            kind=PresentationBlockKind.TEXT,
            content={"text": headline},
        ))

    return SlideSpec(
        slide_id=slide_id,
        purpose=purpose,
        layout_intent=LayoutIntent(template_key=template_key, strict_template=True),
        headline=headline,
        speaker_notes=speaker_notes,
        blocks=blocks,
    )


def _infer_best_template_for_content(content: str) -> str:
    """Analyze content to choose the best slide template."""
    lowered = content.lower()
    word_count = len(content.split())

    # Detect comparison / multi-option content → cards
    if any(term in lowered for term in ("option", "vs.", "versus", "compare", "comparison", "alternative")):
        return "compare.2col"

    # Detect architecture / component descriptions → grid
    if any(term in lowered for term in ("component", "architecture", "pipeline", "module", "layer", "system")):
        return "exec.summary"

    # Detect metrics / numbers → KPI
    import re
    numbers = re.findall(r"\b\d+[%$]?\b", content)
    if len(numbers) >= 3:
        return "kpi.big"

    # Detect lists of 3+ distinct points → cards
    bullet_lines = [line for line in content.splitlines() if line.strip().startswith(("-", "•", "*", "1", "2", "3"))]
    if len(bullet_lines) >= 3:
        return "compare.2col"

    # Detect multiple paragraphs with distinct topics → executive overview
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if len(paragraphs) >= 2 and word_count > 60:
        return "exec.summary"

    # Dense text → executive overview for summarization
    if word_count > 80:
        return "exec.summary"

    return "headline.evidence"


def _preview_archetype_for_template(template_key: str) -> SlideArchetype | None:
    if template_key == "exec.summary":
        return SlideArchetype.EXECUTIVE_SUMMARY
    if template_key == "compare.2col":
        return SlideArchetype.COMPARISON
    if template_key == "kpi.big":
        return SlideArchetype.METRICS
    if template_key == "chart.takeaway":
        return SlideArchetype.CHART
    return None


def _to_api_presentation_spec(
    deck_id: str,
    doc_ids: list[str],
    goal: str,
    planning_spec: PresentationSpec,
) -> PresentationSpecResponse:
    slides = [
        SlideSpecResponse(
            id=slide.slide_id,
            index=index,
            purpose=slide.purpose.value,
            archetype=slide.archetype.value if slide.archetype else None,
            title=slide.headline,
            blocks=[
                {
                    "id": block.block_id,
                    "kind": block.kind.value,
                    "content": _stringify_block_content(block.kind, block.content),
                    "data": block.content,
                    "citation": block.source_citations[0].locator if block.source_citations else None,
                }
                for block in slide.blocks
            ],
            template_id=slide.layout_intent.template_key,
            speaker_notes=slide.speaker_notes or None,
        )
        for index, slide in enumerate(planning_spec.slides, start=1)
    ]
    logo_present = any(
        slide.purpose is SlidePurpose.TITLE
        and any(block.content.get("logo") for block in slide.blocks)
        for slide in planning_spec.slides
    )
    return PresentationSpecResponse(
        id=deck_id,
        doc_id=doc_ids[0],
        doc_ids=doc_ids,
        title=planning_spec.title,
        goal=goal,
        audience=planning_spec.audience,
        slides=slides,
        created_at=datetime.now().isoformat(timespec="seconds"),
        theme=ThemeSummaryResponse(
            name=planning_spec.theme.name,
            primary_color=planning_spec.theme.style_tokens.colors.accent,
            accent_color=planning_spec.theme.style_tokens.colors.muted,
            heading_font=planning_spec.theme.style_tokens.fonts.heading,
            body_font=planning_spec.theme.style_tokens.fonts.body,
            logo_present=logo_present,
        ),
    )


def _to_api_slide_spec(slide: SlideSpec, *, index: int) -> SlideSpecResponse:
    return SlideSpecResponse(
        id=slide.slide_id,
        index=index,
        purpose=slide.purpose.value,
        archetype=slide.archetype.value if slide.archetype else None,
        title=slide.headline,
        blocks=[
            {
                "id": block.block_id,
                "kind": block.kind.value,
                "content": _stringify_block_content(block.kind, block.content),
                "data": block.content,
                "citation": block.source_citations[0].locator if block.source_citations else None,
            }
            for block in slide.blocks
        ],
        template_id=slide.layout_intent.template_key,
        speaker_notes=slide.speaker_notes or None,
    )


def _stringify_block_content(kind: PresentationBlockKind, content: dict[str, Any]) -> str:
    text: str
    if kind is PresentationBlockKind.BULLETS:
        text = "\n".join(f"\u2022 {item}" for item in content.get("items", []))
    elif kind is PresentationBlockKind.KPI_CARDS:
        text = "\n".join(f"{item.get('value', '')}|{item.get('label', '')}" for item in content.get("items", []))
    elif kind is PresentationBlockKind.TABLE:
        text = "\n".join(" | ".join(str(cell) for cell in row) for row in content.get("rows", []))
    elif kind is PresentationBlockKind.CHART:
        text = "\n".join(f"{item.get('label', '')}: {item.get('value', '')}" for item in content.get("series", []))
    elif kind is PresentationBlockKind.CALLOUT and isinstance(content.get("cards"), list):
        text = "\n".join(f"{card.get('title', '')}: {card.get('text', '')}" for card in content["cards"])
    else:
        text = ""
        for field in ("text", "label", "subtitle", "tagline", "footer_info", "logo"):
            if field in content and content[field]:
                text = str(content[field])
                break
        if not text:
            text = "\n".join(f"{key}: {value}" for key, value in content.items())
    return strip_markdown(text)


def _merge_export_slides(planning_spec: PresentationSpec, ui_slides: list[ExportSlideRequest] | None) -> PresentationSpec:
    if not ui_slides:
        return planning_spec

    existing_slides = {slide.slide_id: slide for slide in planning_spec.slides}
    source_ids = [citation.source_id for slide in planning_spec.slides for block in slide.blocks for citation in block.source_citations]
    fallback_source_id = source_ids[0] if source_ids else "ui-export"
    merged_slides = [
        _ui_slide_to_planning_slide(ui_slide, existing_slides.get(ui_slide.id), fallback_source_id)
        for ui_slide in sorted(ui_slides, key=lambda slide: slide.index)
    ]
    return planning_spec.model_copy(update={"slides": merged_slides})


def _ui_slide_to_planning_slide(
    ui_slide: ExportSlideRequest,
    existing_slide: SlideSpec | None,
    fallback_source_id: str,
) -> SlideSpec:
    template_key = canonical_template_key(ui_slide.template_id)
    try:
        purpose = SlidePurpose(ui_slide.purpose)
    except ValueError:
        purpose = existing_slide.purpose if existing_slide else SlidePurpose.CONTENT

    archetype = existing_slide.archetype if existing_slide else None
    if ui_slide.archetype:
        try:
            archetype = SlideArchetype(ui_slide.archetype)
        except ValueError:
            pass

    existing_blocks = {block.block_id: block for block in existing_slide.blocks} if existing_slide else {}
    blocks = [
        _ui_block_to_planning_block(block, existing_blocks.get(block.id), fallback_source_id)
        for block in ui_slide.blocks
    ]
    if not blocks:
        blocks = [
            PresentationBlock(
                block_id=f"{ui_slide.id}-b1",
                kind=PresentationBlockKind.TEXT,
                content={"text": ui_slide.title},
            )
        ]

    headline, blocks = _canonicalize_export_slide(template_key, ui_slide.title, blocks)

    return SlideSpec(
        slide_id=ui_slide.id,
        purpose=purpose,
        archetype=archetype,
        layout_intent=LayoutIntent(template_key=template_key, strict_template=True),
        headline=headline,
        speaker_notes=ui_slide.speaker_notes or "",
        blocks=blocks,
    )


def _ui_block_to_planning_block(
    ui_block: ExportBlockRequest,
    existing_block: PresentationBlock | None,
    fallback_source_id: str,
) -> PresentationBlock:
    try:
        kind = PresentationBlockKind(ui_block.kind)
    except ValueError:
        kind = PresentationBlockKind.TEXT

    citations = existing_block.source_citations[:] if existing_block else []
    if ui_block.citation and not citations:
        source_id = ui_block.citation.split(":", 1)[0] if ":" in ui_block.citation else fallback_source_id
        citations = [SourceCitation(source_id=source_id or fallback_source_id, locator=ui_block.citation)]

    return PresentationBlock(
        block_id=ui_block.id,
        kind=kind,
        content=_ui_block_content(kind, ui_block),
        source_citations=citations,
        style_overrides=existing_block.style_overrides if existing_block else None,
        asset_refs=existing_block.asset_refs[:] if existing_block else [],
        x_security=existing_block.x_security if existing_block else None,
        extensions=existing_block.extensions if existing_block else None,
    )


def _ui_block_content(kind: PresentationBlockKind, ui_block: ExportBlockRequest) -> dict[str, Any]:
    text = ui_block.content or ""
    data = dict(ui_block.data) if isinstance(ui_block.data, dict) else {}

    if data and _should_preserve_ui_block_data(kind, data):
        return data

    # For text-native blocks, prefer the visible content when present so editor
    # edits cannot silently diverge from the exported slide.
    if not text.strip() and data:
        return data

    if not text.strip():
        return {"text": ""}
    if kind is PresentationBlockKind.BULLETS:
        items = [line.lstrip("-•* ").strip() for line in text.splitlines() if line.strip()]
        return {"items": items or [text.strip() or "Add content"]}
    if kind is PresentationBlockKind.KPI_CARDS:
        items = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            if "|" in raw:
                value, label = raw.split("|", 1)
            else:
                value, label = raw, ""
            items.append({"value": value.strip(), "label": label.strip()})
        return {"items": items or [{"value": "N/A", "label": text.strip() or "Metric"}]}
    if kind is PresentationBlockKind.TABLE:
        rows = [[cell.strip() for cell in line.split("|")] for line in text.splitlines() if line.strip()]
        if not rows:
            rows = [["Item", text.strip() or "Add detail"]]
        column_count = max(len(row) for row in rows)
        columns = [f"Column {index + 1}" for index in range(column_count)]
        normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
        return {"columns": columns, "rows": normalized_rows}
    if kind is PresentationBlockKind.CHART:
        series = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            if ":" in raw:
                label, value = raw.split(":", 1)
            else:
                label, value = raw, "1"
            try:
                parsed_value = float(value.strip().replace(",", "").replace("%", "").replace("$", ""))
            except ValueError:
                parsed_value = 1.0
            series.append({"label": label.strip(), "value": parsed_value})
        return {"chart_type": "bar", "series": series or [{"label": "Point 1", "value": 1.0}]}
    if kind is PresentationBlockKind.CALLOUT:
        cards = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            if ":" in raw:
                title, body = raw.split(":", 1)
                cards.append({"title": title.strip(), "text": body.strip()})
        if cards:
            return {"cards": cards}
        return {"text": text.strip()}
    if kind is PresentationBlockKind.QUOTE:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return {"text": lines[0] if lines else text.strip(), "attribution": lines[1] if len(lines) > 1 else ""}
    if kind is PresentationBlockKind.IMAGE:
        return {"text": text.strip() or "Image"}
    return {"text": text.strip()}


def _should_preserve_ui_block_data(kind: PresentationBlockKind, data: dict[str, Any]) -> bool:
    asset_keys = {"local_path", "path", "file_path", "asset_path", "uri"}
    if any(isinstance(data.get(key), str) and data.get(key) for key in asset_keys):
        return True
    if kind in {PresentationBlockKind.TABLE, PresentationBlockKind.CHART, PresentationBlockKind.QUOTE}:
        return True
    if kind is PresentationBlockKind.CALLOUT and isinstance(data.get("cards"), list):
        return True
    return False


def _canonicalize_export_slide(
    template_key: str,
    headline: str,
    blocks: list[PresentationBlock],
) -> tuple[str, list[PresentationBlock]]:
    canonical_blocks = blocks
    canonical_headline = headline

    if template_key in {"content.3col", "content.4col"}:
        target_count = 3 if template_key == "content.3col" else 4
        canonical_blocks = _expand_card_blocks(blocks, target_count)
    elif template_key == "bold.photo":
        statement = next((_extract_block_text(block) for block in blocks if block.kind is not PresentationBlockKind.IMAGE), "")
        if statement:
            canonical_headline = statement

    if template_key == "chart.takeaway" and len(canonical_blocks) >= 2:
        takeaway = canonical_blocks[1]
        if takeaway.kind is PresentationBlockKind.CALLOUT and isinstance(takeaway.content.get("cards"), list):
            canonical_blocks = [
                *canonical_blocks[:1],
                takeaway.model_copy(
                    update={
                        "content": {
                            "text": "\n".join(
                                f"{card.get('title', '').strip()}: {card.get('text', '').strip()}".strip(": ")
                                for card in takeaway.content["cards"]
                                if card.get("title") or card.get("text")
                            ).strip()
                        }
                    }
                ),
                *canonical_blocks[2:],
            ]

    return canonical_headline, canonical_blocks


def _expand_card_blocks(blocks: list[PresentationBlock], target_count: int) -> list[PresentationBlock]:
    if len(blocks) >= target_count:
        return blocks
    if not blocks:
        return blocks

    first_block = blocks[0]
    cards = first_block.content.get("cards")
    if first_block.kind is not PresentationBlockKind.CALLOUT or not isinstance(cards, list):
        return blocks

    expanded_blocks: list[PresentationBlock] = []
    for index in range(target_count):
        card = cards[index] if index < len(cards) and isinstance(cards[index], dict) else {}
        title = str(card.get("title", "")).strip()
        body = str(card.get("text", "")).strip()
        text = "\n".join(part for part in (title, body) if part).strip() or "Add supporting detail."
        expanded_blocks.append(
            first_block.model_copy(
                update={
                    "block_id": f"{first_block.block_id}-card-{index + 1}",
                    "kind": PresentationBlockKind.TEXT,
                    "content": {"text": text},
                }
            )
        )
    return expanded_blocks


def _extract_block_text(block: PresentationBlock) -> str:
    return _stringify_block_content(block.kind, block.content).strip()


def _tone_label_from_score(score: float) -> str:
    if score >= 67:
        return "bold"
    if score <= 33:
        return "analytical"
    return "balanced"


def _build_alias_index() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for alias, canonical in TEMPLATE_ALIASES.items():
        aliases.setdefault(canonical, alias)
    return aliases


def _humanize_template_name(template_key: str) -> str:
    return " ".join(part.capitalize() for part in template_key.replace(".", " ").replace("_", " ").split())


def _template_column_count(template_key: str) -> int:
    if ".3" in template_key or "3col" in template_key:
        return 3
    if ".2" in template_key or "2col" in template_key:
        return 2
    return 1


def _build_stub_pdf(deck_id: str) -> bytes:
    text = f"Auto-PPT export preview for {deck_id}"
    stream = f"BT /F1 18 Tf 40 120 Td ({_escape_pdf_text(text)}) Tj ET".encode("ascii")
    objects = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj",
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 180] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj",
        b"4 0 obj<< /Length " + str(len(stream)).encode("ascii") + b" >>stream\n" + stream + b"\nendstream endobj",
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj",
    ]
    parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for obj in objects:
        offsets.append(sum(len(part) for part in parts))
        parts.append(obj + b"\n")
    xref_offset = sum(len(part) for part in parts)
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = b"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF"
    return b"".join(parts + xref + [trailer])


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _serve_frontend_path(full_path: str) -> Response:
    if not WEB_INDEX.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found. Run `npm run build` in ui/.")

    requested = (WEB_DIR / full_path).resolve()
    try:
        requested.relative_to(WEB_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Invalid frontend path.") from exc

    if full_path and requested.exists() and requested.is_file():
        response = FileResponse(requested)
        response.headers["Cache-Control"] = "no-store"
        return response
    response = FileResponse(WEB_INDEX)
    response.headers["Cache-Control"] = "no-store"
    return response


_ALIAS_BY_CANONICAL = _build_alias_index()


def _infer_chat_brief(
    prompt: str,
    default_title: str,
    *,
    content_chunk_count: int = 0,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lowered = prompt.lower()
    source_context = source_context or {}

    # Dynamic default based on document size — more content means more slides.
    # Each content slide typically covers ~8-12 chunks of source material.
    if str(source_context.get("source_format", "")).lower() == "pptx" and source_context.get("slide_count"):
        slide_count = max(1, min(40, int(source_context["slide_count"])))
    elif content_chunk_count > 0:
        slide_count = max(6, min(20, 4 + content_chunk_count // 10))
    else:
        slide_count = 6

    # Explicit user request ("12 slides") overrides the dynamic default.
    count_match = next((match for match in re.finditer(r"(\d+)\s+slides?", lowered)), None)
    if count_match is not None:
        slide_count = max(1, min(40, int(count_match.group(1))))

    audience = "Executive audience"
    for marker in ("for ", "to "):
        if marker in lowered:
            fragment = prompt[lowered.index(marker) + len(marker):].split(".")[0].split(",")[0]
            if fragment.strip():
                audience = fragment.strip().rstrip()
                break
    if "oracle" in lowered and "consult" in lowered:
        audience = "Oracle consultants"

    tone = 50.0
    if any(term in lowered for term in ("board", "analytical", "technical", "consultants")):
        tone = 25.0
    if any(term in lowered for term in ("bold", "sales", "investor", "pitch")):
        tone = 80.0

    goal = prompt.strip()
    if len(goal.split()) > 12:
        goal = " ".join(goal.split()[:12])
    if not goal:
        goal = f"Present {default_title}"

    selected_template_id = "compare.2col" if any(term in lowered for term in ("architecture", "pipeline", "overview", "components")) else "headline.evidence"
    return {
        "goal": goal,
        "audience": audience,
        "tone": tone,
        "slide_count": slide_count,
        "selected_template_id": selected_template_id,
    }
