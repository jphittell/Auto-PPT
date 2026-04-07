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
    ExportRequest,
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
DECK_DEFAULT_TEMPLATE_IDS = {"headline.evidence", "compare.2col", "kpi.big"}
SPECIALIST_TEMPLATE_IDS = {"exec.summary", "chart.takeaway", "closing.actions", "title.cover", "section.divider"}
FONT_PAIR_MAP = {
    "Inter/Inter": ("Inter", "Inter"),
    "Lato/Merriweather": ("Merriweather", "Lato"),
    "DM Sans/DM Serif Display": ("DM Serif Display", "DM Sans"),
}


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest_document(file: UploadFile = File(...)) -> IngestResponse:
    original_name = Path(file.filename or "upload.txt").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise HTTPException(status_code=400, detail="Only .pdf, .txt, and .md uploads are supported.")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / original_name
        temp_path.write_bytes(await file.read())
        result = pipeline_module.ingest_and_index(
            temp_path,
            title=Path(original_name).stem.replace("_", " "),
            embedder=_get_embedder(),
            vector_store=InMemoryVectorStore(),
        )

    element_counts = Counter(element.type.value for element in result.ingestion_request.document.elements)
    summary = await _generate_document_summary(result)
    response = IngestResponse(
        doc_id=result.doc_id,
        chunk_count=result.n_chunks,
        title=result.ingestion_request.document.title,
        element_types=dict(sorted(element_counts.items())),
        summary=summary,
    )
    _INGESTED_DOCS[result.doc_id] = response
    _INGESTED_RESULTS[result.doc_id] = result
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
    inferred = _infer_chat_brief(request.prompt, combined_title)
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

    brief = collect_deck_brief(
        user_request=goal,
        audience=audience,
        goal=goal,
        tone=tone_label,
        slide_count_target=slide_count,
        source_corpus_ids=source_ids,
        document_title=combined_title,
        source_texts=source_texts,
        llm_client=None,
    )
    outline = _normalize_outline_exact_count(generate_outline(brief, llm_client=None), slide_count, goal)

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
        raise HTTPException(status_code=400, detail="Outline length must match the planned slide count.")

    selected_template_id = canonical_template_key(request.selected_template_id)
    if selected_template_id not in DECK_DEFAULT_TEMPLATE_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported deck-level template: {request.selected_template_id}")

    try:
        outline = _apply_outline_edits(draft, request.outline)
        vector_store = _build_vector_store(draft.doc_ids)
        retrieved_chunks = execute_retrieval_plan(
            build_retrieval_plan(draft.brief, outline, llm_client=None),
            vector_store=vector_store,
            embedder=_get_embedder(),
        )
        style_tokens = _style_tokens_from_brand_kit(request.brand_kit)
        deck_id = f"deck-{draft.doc_ids[0]}-{len(_DECKS) + 1}"
        logo_path = _persist_logo_asset(deck_id, request.brand_kit.logo_data_url)

        spec = generate_presentation_spec(
            draft.brief.model_copy(update={"tone": draft.tone_label, "slide_count_target": draft.slide_count}),
            outline,
            retrieved_chunks,
            deck_title=f"{draft.title} presentation",
            style_tokens=style_tokens,
            theme_name=_theme_name(selected_template_id),
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
    chosen_template = canonical_template_key(request.template_id or _infer_best_template_for_content(content_text))

    try:
        # Route all preview generation through the same normalization path.
        structured = await _llm_structure_slide_content(
            content_text, request.title, request.audience, chosen_template,
        )
        slide = _build_preview_slide(
            slide_id=request.slide_id,
            purpose=purpose,
            headline=structured.get("headline", request.title),
            template_key=structured.get("template_id", chosen_template),
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
    inferred = _infer_chat_brief(prompt, ingest.title)
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
            selected_template_id=inferred["selected_template_id"],
            brand_kit=BrandKitRequest(
                logo_data_url=None,
                primary_color="#C74634" if "oracle" in prompt.lower() else "#4F46E5",
                accent_color="#1F2937",
                font_pair="Inter/Inter",
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

    if request.format == "pptx":
        planning_spec = _RAW_DECK_SPECS.get(deck_id)
        if planning_spec is None:
            raise HTTPException(status_code=404, detail=f"Missing planning spec for deck_id: {deck_id}")

        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / f"{deck_id}.pptx"
            pipeline_module.generate_deck(
                presentation_spec=planning_spec,
                output_path=export_path,
                enable_refinement=False,
            )
            if not export_path.exists():
                raise HTTPException(status_code=500, detail="PPTX export failed.")

            return Response(
                content=export_path.read_bytes(),
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                headers={"Content-Disposition": f'attachment; filename="{deck_id}.pptx"'},
            )

    from pptx_gen.renderer.pdf_exporter import export_deck_to_pdf

    deck_data = _DECKS[deck_id].model_dump()
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


def _build_vector_store(doc_ids: list[str]) -> InMemoryVectorStore:
    vector_store = InMemoryVectorStore()
    embedder = _get_embedder()
    for result in _ingested_results_for(doc_ids):
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


def _style_tokens_from_brand_kit(brand_kit: BrandKitRequest) -> StyleTokens:
    heading_font, body_font = FONT_PAIR_MAP.get(brand_kit.font_pair, (brand_kit.font_pair, brand_kit.font_pair))
    return StyleTokens(
        fonts={
            "heading": heading_font,
            "body": body_font,
            "mono": pipeline_module.DEFAULT_STYLE_TOKENS["fonts"]["mono"],
        },
        colors={
            "bg": "#FFFFFF",
            "text": brand_kit.accent_color,
            "accent": brand_kit.primary_color,
            "muted": brand_kit.accent_color,
        },
        spacing=pipeline_module.DEFAULT_STYLE_TOKENS["spacing"],
        images=pipeline_module.DEFAULT_STYLE_TOKENS["images"],
    )


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
    existing = {slide.slide_id: slide for slide in spec.slides}
    slides: list[SlideSpec] = []
    for item in outline.outline:
        slide = existing.get(item.slide_id)
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
        chosen_template = (
            explicit_template_by_slide_id[slide.slide_id]
            if slide.slide_id in explicit_template_by_slide_id
            else current_template
            if current_template in SPECIALIST_TEMPLATE_IDS
            else selected_template_id
        )
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
                content={"subtitle": text_items[0] if text_items else "", "presenter": "", "date": ""},
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

    if canonical == "closing.actions":
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
        ]

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
    return f"{_humanize_template_name(template_key)} Brand"


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
    content: str,
    title: str,
    audience: str,
    suggested_template: str,
) -> dict[str, Any]:
    """Use LLM to summarize raw text into structured slide content."""
    import json as _json

    system = f"""You are a presentation designer. Given raw text, produce a structured JSON slide.

Choose the best template_id from: headline.evidence, compare.2col, exec.summary, chart.takeaway, kpi.big, closing.actions
The suggested template is "{suggested_template}" but override if a better one fits.

Return JSON with:
- "headline": concise slide title (max 8 words)
- "template_id": chosen template
- "speaker_notes": 1-2 sentence presenter note
- "blocks": array of content blocks, each with "kind" and fields:
  - For callout/cards: {{"kind":"callout","cards":[{{"title":"...","text":"..."}}]}} (one card per distinct point, each text 15-25 words)
  - For bullets: {{"kind":"bullets","items":["...",...]}} (one bullet per distinct point, each 10-20 words)
  - For text: {{"kind":"text","text":"..."}} (40-80 words, summarized)
  - For kpi_cards: {{"kind":"kpi_cards","items":[{{"value":"...","label":"..."}}]}} (3 items)

CRITICAL RULES:
- Every distinct point or idea from the input MUST appear in the output. Do not drop any user content.
- Summarize and rephrase for clarity — do NOT just copy the raw text verbatim.
- If there are 4+ distinct points, use cards (one per point) or bullets (one per point). Do not cap at 3 if there are more.
- Each card/bullet should be a distinct insight derived from the input.
Audience: {audience}"""

    user_prompt = (
        f"Title: {title}\n"
        f"Audience: {audience}\n"
        f"Preferred template: {suggested_template}\n\n"
        "Produce consulting-style slide content.\n\n"
        f"Raw content:\n{content}"
    )

    try:
        llm_client = _get_optional_structured_llm_client()
        if llm_client is None:
            raise ValueError("No LLM client")

        if hasattr(llm_client, "generate_json"):
            result = llm_client.generate_json(
                system_prompt=system,
                user_prompt=(
                    f"{user_prompt}\n\n"
                    "Return a PresentationSpec with exactly one slide that follows the requested structure."
                ),
                schema_name="PresentationSpec",
            )
            slide_payloads = result.get("slides", []) if isinstance(result, dict) else []
            if not slide_payloads:
                raise ValueError("Structured preview returned no slides")
            slide_payload = slide_payloads[0]
            if not isinstance(slide_payload, dict):
                raise ValueError("Structured preview slide payload must be an object")

            layout_intent = slide_payload.get("layout_intent", {})
            if layout_intent is not None and not isinstance(layout_intent, dict):
                raise ValueError("Structured preview layout_intent must be an object")

            blocks_payload = slide_payload.get("blocks", [])
            if not isinstance(blocks_payload, list):
                raise ValueError("Structured preview blocks must be a list")

            normalized_blocks: list[dict[str, Any]] = []
            for block in blocks_payload:
                if not isinstance(block, dict):
                    raise ValueError("Structured preview blocks must contain objects")
                kind = block.get("kind", "text")
                block_content = block.get("content", {})
                if block_content is not None and not isinstance(block_content, dict):
                    raise ValueError("Structured preview block content must be an object")
                block_content = block_content or {}
                if kind == "callout":
                    normalized_blocks.append({"kind": kind, "cards": block_content.get("cards", [])})
                elif kind in {"bullets", "kpi_cards"}:
                    normalized_blocks.append({"kind": kind, "items": block_content.get("items", [])})
                else:
                    normalized_blocks.append({"kind": kind, "text": block_content.get("text", "")})
            return {
                "headline": slide_payload.get("headline", title),
                "template_id": layout_intent.get("template_key", suggested_template),
                "speaker_notes": slide_payload.get("speaker_notes", ""),
                "blocks": normalized_blocks,
            }
        elif hasattr(llm_client, "anthropic_client"):
            response = llm_client.anthropic_client.messages.create(
                model=llm_client.model,
                max_tokens=800,
                temperature=0.3,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = response.content[0].text.strip()
        elif hasattr(llm_client, "openai_client"):
            response = llm_client.openai_client.chat.completions.create(
                model=llm_client.model,
                max_tokens=800,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = response.choices[0].message.content.strip()
        else:
            raise ValueError("Unknown LLM client type")

        # Extract JSON from response (may be wrapped in markdown fences)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return _json.loads(raw)
    except Exception:
        # Fallback: structure content without LLM
        return _fallback_structure_content(content, title, suggested_template)


def _fallback_structure_content(content: str, title: str, template: str) -> dict[str, Any]:
    """Structure content into slide blocks without LLM."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    bullet_lines = [line.lstrip("-•* ").strip() for line in lines if line.startswith(("-", "•", "*"))]
    plain_lines = [line for line in lines if not line.startswith(("-", "•", "*"))]

    # Extract sentences for card content
    sentences = []
    for line in lines:
        sentences.extend(re.split(r"(?<=[.!?])\s+", line))
    sentences = [s.strip() for s in sentences if len(s.split()) >= 5]

    if template in ("compare.2col", "exec.summary"):
        cards = []
        for i, sentence in enumerate(sentences[:6]):
            words = sentence.split()
            card_title = " ".join(words[:5])
            card_text = " ".join(words[:25])
            cards.append({"title": card_title, "text": card_text})
        while len(cards) < 3:
            cards.append({"title": f"Key point {len(cards)+1}", "text": "Add detail here."})
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "callout", "cards": cards[:3]}],
        }

    if template == "kpi.big":
        items = []
        for sentence in sentences[:3]:
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

    if bullet_lines:
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "bullets", "items": bullet_lines[:6]}],
        }

    # Default: summarize as text
    summary = " ".join(sentences[:5]) if sentences else content[:300]
    return {
        "headline": title,
        "template_id": template,
        "speaker_notes": "",
        "blocks": [{"kind": "text", "text": summary}],
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
            accent_color=planning_spec.theme.style_tokens.colors.text,
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
        return FileResponse(requested)
    return FileResponse(WEB_INDEX)


_ALIAS_BY_CANONICAL = _build_alias_index()


def _infer_chat_brief(prompt: str, default_title: str) -> dict[str, Any]:
    lowered = prompt.lower()
    slide_count = 6
    count_match = next((match for match in re.finditer(r"(\d+)\s+slides?", lowered)), None)
    if count_match is not None:
        slide_count = max(4, min(12, int(count_match.group(1))))

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
