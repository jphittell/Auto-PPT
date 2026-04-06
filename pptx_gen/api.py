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
    PlanDeckResponse,
    PresentationSpecResponse,
    SlideSpecResponse,
    TemplateResponse,
    ThemeSummaryResponse,
)
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
from pptx_gen.planning.schemas import (
    DeckBrief,
    DeckTheme,
    LayoutIntent,
    OutlineItem,
    OutlineSpec,
    PresentationBlock,
    PresentationBlockKind,
    PresentationSpec,
    SlideArchetype,
    SlidePurpose,
    SlideSpec,
    SourceCitation,
)


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
REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
WEB_INDEX = WEB_DIR / "index.html"
RUNTIME_ASSET_DIR = REPO_ROOT / "out" / "runtime_assets"
DECK_DEFAULT_TEMPLATE_IDS = {"content.1col", "content.3col.cards", "kpi.3up"}
SPECIALIST_TEMPLATE_IDS = {"executive.overview", "architecture.grid", "content.2col.text_image", "table.full", "chart.full"}
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
    response = IngestResponse(
        doc_id=result.doc_id,
        chunk_count=result.n_chunks,
        title=result.ingestion_request.document.title,
        element_types=dict(sorted(element_counts.items())),
    )
    _INGESTED_DOCS[result.doc_id] = response
    _INGESTED_RESULTS[result.doc_id] = result
    return response


@app.post("/api/plan", response_model=PlanDeckResponse)
async def plan_deck(request: PlanDeckRequest) -> PlanDeckResponse:
    ingestion_results = _ingested_results_for(request.doc_ids)
    combined_title = " + ".join(result.ingestion_request.document.title for result in ingestion_results)
    tone_label = _tone_label_from_score(request.tone)
    source_ids = [result.source_id for result in ingestion_results]
    source_texts = [chunk.text for result in ingestion_results for chunk in result.chunks]

    brief = collect_deck_brief(
        user_request=request.goal,
        audience=request.audience,
        goal=request.goal,
        tone=tone_label,
        slide_count_target=request.slide_count,
        source_corpus_ids=source_ids,
        document_title=combined_title,
        source_texts=source_texts,
        llm_client=None,
    )
    outline = _normalize_outline_exact_count(generate_outline(brief, llm_client=None), request.slide_count, request.goal)

    created_at = datetime.now().isoformat(timespec="seconds")
    draft_id = f"draft-{uuid4().hex[:10]}"
    _DRAFTS[draft_id] = DraftState(
        draft_id=draft_id,
        doc_ids=list(request.doc_ids),
        source_ids=source_ids,
        title=combined_title,
        goal=request.goal,
        audience=request.audience,
        tone_label=tone_label,
        slide_count=request.slide_count,
        brief=brief.model_copy(update={"slide_count_target": request.slide_count}),
        outline=outline,
        created_at=created_at,
    )

    return PlanDeckResponse(
        draft_id=draft_id,
        doc_id=request.doc_ids[0],
        doc_ids=list(request.doc_ids),
        title=combined_title,
        goal=request.goal,
        audience=request.audience,
        slides=_outline_to_response_slides(
            outline,
            goal=request.goal,
            audience=request.audience,
            title=combined_title,
            created_at=created_at,
        ),
        created_at=created_at,
    )


@app.post("/api/generate", response_model=PresentationSpecResponse)
async def generate_deck_from_draft(request: GenerateDeckRequest) -> PresentationSpecResponse:
    draft = _DRAFTS.get(request.draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Unknown draft_id: {request.draft_id}")
    if len(request.outline) != draft.slide_count:
        raise HTTPException(status_code=400, detail="Outline length must match the planned slide count.")

    selected_template_id = canonical_template_key(request.selected_template_id)
    if selected_template_id not in DECK_DEFAULT_TEMPLATE_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported deck-level template: {request.selected_template_id}")

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
        llm_client=None,
    )
    spec = _enforce_outline_authority(spec, outline, draft.source_ids)
    spec = _apply_global_template_default(spec, selected_template_id)
    spec = _inject_brand_logo(spec, logo_path)

    response = _to_api_presentation_spec(deck_id, draft.doc_ids, draft.goal, spec)
    _RAW_DECK_SPECS[deck_id] = spec
    _DECKS[deck_id] = response
    return response


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

    pdf_bytes = _build_stub_pdf(deck_id)
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
        chosen_template = canonical_template_key(update.template_id or base.template_key or "content.1col")
        if chosen_template != canonical_template_key(base.template_key or "content.1col"):
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

    insert_at = next((index for index, item in enumerate(items) if item.purpose in {SlidePurpose.SUMMARY, SlidePurpose.APPENDIX}), len(items))
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
                template_key="content.1col",
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
                    layout_intent=LayoutIntent(template_key=item.template_key or "content.1col", strict_template=True),
                    headline=item.headline,
                    speaker_notes=item.message,
                    blocks=[
                        PresentationBlock(
                            block_id="b1",
                            kind=PresentationBlockKind.TEXT,
                            content={"text": item.message},
                            source_citations=_fallback_citation(source_ids) if item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY, SlidePurpose.APPENDIX} else [],
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
    if template_key == "content.1col":
        return slide.model_copy(update={"layout_intent": LayoutIntent(template_key=template_key, strict_template=True)})
    if template_key == "executive.overview":
        return slide.model_copy(update={"layout_intent": LayoutIntent(template_key=template_key, strict_template=True)})
    if template_key == "architecture.grid":
        return slide.model_copy(update={"layout_intent": LayoutIntent(template_key=template_key, strict_template=True)})

    citations = [citation for block in slide.blocks for citation in block.source_citations]
    summary_items = _slide_summary_items(slide)

    if template_key == "kpi.3up":
        blocks = [
            PresentationBlock(
                block_id=f"{slide.slide_id}-kpi-{index + 1}",
                kind=PresentationBlockKind.TEXT,
                content={"text": summary_items[index] if index < len(summary_items) else f"Insight {index + 1}"},
                source_citations=citations[:1] if citations else [],
            )
            for index in range(3)
        ]
        return slide.model_copy(
            update={
                "layout_intent": LayoutIntent(template_key=template_key, strict_template=True),
                "blocks": blocks,
            }
        )

    if template_key == "content.3col.cards":
        cards = [
            {"title": f"Point {index + 1}", "text": summary_items[index] if index < len(summary_items) else f"Detail {index + 1}"}
            for index in range(3)
        ]
        return slide.model_copy(
            update={
                "layout_intent": LayoutIntent(template_key=template_key, strict_template=True),
                "blocks": [
                    PresentationBlock(
                        block_id=f"{slide.slide_id}-cards",
                        kind=PresentationBlockKind.CALLOUT,
                        content={"cards": cards},
                        source_citations=citations[:2] if citations else [],
                    )
                ],
            }
        )

    return slide.model_copy(update={"layout_intent": LayoutIntent(template_key="content.1col", strict_template=True)})


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

    if item.purpose is SlidePurpose.AGENDA:
        agenda_lines = [
            outline_item.headline
            for outline_item in outline.outline
            if outline_item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}
        ][:5]
        return [
            {
                "id": f"{item.slide_id}-agenda",
                "kind": "bullets",
                "content": "\n".join(f"• {line}" for line in agenda_lines),
                "citation": None,
            }
        ]

    bullets = [item.message, *item.evidence_queries[:2]]
    return [
        {
            "id": f"{item.slide_id}-outline",
            "kind": "bullets",
            "content": "\n".join(f"• {_trim_outline_line(line)}" for line in bullets if line),
            "citation": None,
        }
    ]


def _recommended_outline_template(item: OutlineItem) -> str:
    if item.purpose is SlidePurpose.TITLE:
        return "title.hero"
    if item.purpose is SlidePurpose.AGENDA:
        return "agenda.list"
    if item.archetype is SlideArchetype.EXECUTIVE_OVERVIEW:
        return "executive.overview"
    if item.archetype is SlideArchetype.ARCHITECTURE_GRID:
        return "architecture.grid"
    if item.purpose is SlidePurpose.SUMMARY:
        return "content.3col.cards"

    headline = f"{item.headline} {item.message}".lower()
    if any(term in headline for term in ("metric", "kpi", "score", "rate", "roi", "growth")):
        return "kpi.3up"
    if any(
        term in headline
        for term in (
            "architecture",
            "pipeline",
            "component",
            "capability",
            "workstream",
            "overview",
            "ingestion",
            "retrieval",
            "layout",
            "asset",
            "export",
            "renderer",
        )
    ):
        return "architecture.grid"
    if any(term in headline for term in ("compare", "comparison", "option", "tradeoff", "landscape", "tools")):
        return "content.3col.cards"
    return canonical_template_key(item.template_key or "content.1col")


def _trim_outline_line(value: str) -> str:
    words = [word for word in str(value).replace("\n", " ").split() if word]
    return " ".join(words[:12])


def _fallback_citation(source_ids: list[str]) -> list[SourceCitation]:
    source_id = source_ids[0] if source_ids else "source"
    return [SourceCitation(source_id=source_id, locator=f"{source_id}:page1")]


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


def _stringify_block_content(kind: PresentationBlockKind, content: dict[str, Any]) -> str:
    if kind is PresentationBlockKind.BULLETS:
        return "\n".join(f"• {item}" for item in content.get("items", []))
    if kind is PresentationBlockKind.KPI_CARDS:
        return "\n".join(f"{item.get('value', '')}|{item.get('label', '')}" for item in content.get("items", []))
    if kind is PresentationBlockKind.TABLE:
        return "\n".join(" | ".join(str(cell) for cell in row) for row in content.get("rows", []))
    if kind is PresentationBlockKind.CHART:
        return "\n".join(f"{item.get('label', '')}: {item.get('value', '')}" for item in content.get("series", []))
    if kind is PresentationBlockKind.CALLOUT and isinstance(content.get("cards"), list):
        return "\n".join(f"{card.get('title', '')}: {card.get('text', '')}" for card in content["cards"])
    for field in ("text", "label", "subtitle", "tagline", "footer_info", "logo"):
        if field in content and content[field]:
            return str(content[field])
    return "\n".join(f"{key}: {value}" for key, value in content.items())


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

    selected_template_id = "content.3col.cards" if any(term in lowered for term in ("architecture", "pipeline", "overview", "components")) else "content.1col"
    return {
        "goal": goal,
        "audience": audience,
        "tone": tone,
        "slide_count": slide_count,
        "selected_template_id": selected_template_id,
    }
