"""FastAPI app for local web testing of Auto-PPT."""

from __future__ import annotations

import asyncio
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from pptx_gen.api_schemas import (
    ExportRequest,
    GenerateDeckRequest,
    HealthResponse,
    IngestResponse,
    PresentationSpecResponse,
    SlideSpecResponse,
    TemplateResponse,
    UpgradeRequiredResponse,
)
from pptx_gen.layout.schemas import StyleTokens
from pptx_gen.layout.templates import TEMPLATE_ALIASES, TEMPLATE_REGISTRY, list_template_keys
from pptx_gen.pipeline import DEFAULT_STYLE_TOKENS, ingest_and_index
from pptx_gen.planning.schemas import (
    DeckTheme,
    LayoutIntent,
    PresentationBlock,
    PresentationBlockKind,
    PresentationSpec,
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

_INGESTED_DOCS: dict[str, IngestResponse] = {}
_DECKS: dict[str, PresentationSpecResponse] = {}
_RAW_DECK_SPECS: dict[str, PresentationSpec] = {}
_STYLE_TOKENS = StyleTokens(**DEFAULT_STYLE_TOKENS)


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
        result = ingest_and_index(temp_path, title=Path(original_name).stem.replace("_", " "))

    element_counts = Counter(element.type.value for element in result.ingestion_request.document.elements)
    response = IngestResponse(
        doc_id=result.doc_id,
        chunk_count=result.n_chunks,
        title=result.ingestion_request.document.title,
        element_types=dict(sorted(element_counts.items())),
    )
    _INGESTED_DOCS[result.doc_id] = response
    return response


@app.post("/api/generate", response_model=PresentationSpecResponse)
async def generate_deck_mock(request: GenerateDeckRequest) -> PresentationSpecResponse:
    ingest_summary = _INGESTED_DOCS.get(request.doc_id)
    if ingest_summary is None:
        raise HTTPException(status_code=404, detail=f"Unknown doc_id: {request.doc_id}")

    await asyncio.sleep(2)

    planning_spec = _build_mock_planning_spec(
        doc_id=request.doc_id,
        title=ingest_summary.title,
        goal=request.goal,
        audience=request.audience,
        tone=request.tone,
    )
    deck_id = f"deck-{request.doc_id}-{len(_DECKS) + 1}"
    response = _to_api_presentation_spec(deck_id, request.doc_id, request.goal, planning_spec)
    _RAW_DECK_SPECS[deck_id] = planning_spec
    _DECKS[deck_id] = response
    return response


@app.get("/api/templates", response_model=list[TemplateResponse])
async def get_templates() -> list[TemplateResponse]:
    return [
        TemplateResponse(
            id=template_key,
            name=_humanize_template_name(template_key),
            alias=_ALIAS_BY_CANONICAL.get(template_key, template_key),
            columns=_template_column_count(template_key),
            description=TEMPLATE_REGISTRY[template_key].description,
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
async def export_deck(deck_id: str, request: ExportRequest) -> Response | JSONResponse:
    if deck_id not in _DECKS:
        raise HTTPException(status_code=404, detail=f"Unknown deck_id: {deck_id}")

    if request.format == "pptx":
        return JSONResponse(UpgradeRequiredResponse().model_dump())

    pdf_bytes = _build_stub_pdf(deck_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{deck_id}.pdf"'},
    )


def _build_mock_planning_spec(
    *,
    doc_id: str,
    title: str,
    goal: str,
    audience: str,
    tone: float,
) -> PresentationSpec:
    topic = _topic_phrase(doc_id, title)
    tone_label = "bold" if tone >= 66 else "balanced" if tone >= 33 else "analytical"
    citation = SourceCitation(source_id=f"src-{doc_id}", locator=f"{doc_id}:page1", quote=title, confidence=0.91)
    theme = DeckTheme(name="Auto PPT Mock", style_tokens=_STYLE_TOKENS)
    slides = [
        SlideSpec(
            slide_id="slide-1",
            purpose=SlidePurpose.TITLE,
            layout_intent=LayoutIntent(template_key="title.hero", strict_template=True),
            headline=f"{topic} deck",
            speaker_notes="Opening title slide for the generated deck.",
            blocks=[
                PresentationBlock(
                    block_id="title-meta",
                    kind=PresentationBlockKind.TEXT,
                    content={
                        "subtitle": f"{goal} for {audience}",
                        "presenter": "Auto-PPT",
                        "date": datetime.now().strftime("%b %d, %Y"),
                    },
                    source_citations=[],
                )
            ],
        ),
        SlideSpec(
            slide_id="slide-2",
            purpose=SlidePurpose.AGENDA,
            layout_intent=LayoutIntent(template_key="agenda.list", strict_template=True),
            headline="Agenda",
            speaker_notes="Agenda preview for the mock deck.",
            blocks=[
                PresentationBlock(
                    block_id="agenda-list",
                    kind=PresentationBlockKind.BULLETS,
                    content={"items": ["Context and framing", "Key insights", "Recommended actions"]},
                    source_citations=[],
                )
            ],
        ),
        SlideSpec(
            slide_id="slide-3",
            purpose=SlidePurpose.SECTION,
            layout_intent=LayoutIntent(template_key="section.header", strict_template=True),
            headline="What matters most",
            speaker_notes="Section divider.",
            blocks=[
                PresentationBlock(
                    block_id="section-context",
                    kind=PresentationBlockKind.CALLOUT,
                    content={
                        "tagline": f"Structured around a {tone_label} narrative for {audience}.",
                        "footer_info": f"Derived from {title}.",
                    },
                    source_citations=[],
                )
            ],
        ),
        SlideSpec(
            slide_id="slide-4",
            purpose=SlidePurpose.CONTENT,
            layout_intent=LayoutIntent(template_key="content.1col", strict_template=True),
            headline="Core narrative",
            speaker_notes="Single-column summary.",
            blocks=[
                PresentationBlock(
                    block_id="core-text",
                    kind=PresentationBlockKind.TEXT,
                    content={"text": f"{topic} is the central decision theme for this audience."},
                    source_citations=[citation],
                ),
                PresentationBlock(
                    block_id="core-callout",
                    kind=PresentationBlockKind.CALLOUT,
                    content={"text": "Keep the story concise, evidence-backed, and executive-readable."},
                    source_citations=[citation],
                ),
            ],
        ),
        SlideSpec(
            slide_id="slide-5",
            purpose=SlidePurpose.CONTENT,
            layout_intent=LayoutIntent(template_key="content.2col.text_image", strict_template=True),
            headline="Evidence and visual support",
            speaker_notes="Two-column text and image composition.",
            blocks=[
                PresentationBlock(
                    block_id="visual-bullets",
                    kind=PresentationBlockKind.BULLETS,
                    content={
                        "items": [
                            f"Lead with the {topic.lower()} takeaway.",
                            "Support claims with cited evidence.",
                            "Use visuals to shorten explanatory text.",
                        ]
                    },
                    source_citations=[citation],
                ),
                PresentationBlock(
                    block_id="visual-image",
                    kind=PresentationBlockKind.IMAGE,
                    content={"label": f"Placeholder visual for {topic}"},
                    source_citations=[],
                    asset_refs=[f"{doc_id}-hero-image"],
                ),
            ],
        ),
        SlideSpec(
            slide_id="slide-6",
            purpose=SlidePurpose.CONTENT,
            layout_intent=LayoutIntent(template_key="chart.full", strict_template=True),
            headline="Performance trend",
            speaker_notes="Chart-focused insight slide.",
            blocks=[
                PresentationBlock(
                    block_id="trend-chart",
                    kind=PresentationBlockKind.CHART,
                    content={
                        "series": [
                            {"label": "Baseline", "value": 42},
                            {"label": "Current", "value": 67},
                            {"label": "Target", "value": 81},
                        ]
                    },
                    source_citations=[citation],
                    asset_refs=[f"{doc_id}-trend-chart"],
                )
            ],
        ),
        SlideSpec(
            slide_id="slide-7",
            purpose=SlidePurpose.SUMMARY,
            layout_intent=LayoutIntent(template_key="kpi.3up", strict_template=True),
            headline="Executive readout",
            speaker_notes="KPI summary.",
            blocks=[
                PresentationBlock(
                    block_id="kpi-summary",
                    kind=PresentationBlockKind.KPI_CARDS,
                    content={
                        "items": [
                            {"value": "84%", "label": "Readiness"},
                            {"value": "3", "label": "Key actions"},
                            {"value": "Q2", "label": "Decision window"},
                        ]
                    },
                    source_citations=[citation],
                ),
                PresentationBlock(
                    block_id="summary-quote",
                    kind=PresentationBlockKind.QUOTE,
                    content={"text": f"{topic} should be framed as a next-step decision, not background detail."},
                    source_citations=[citation],
                ),
            ],
        ),
        SlideSpec(
            slide_id="slide-8",
            purpose=SlidePurpose.APPENDIX,
            layout_intent=LayoutIntent(template_key="table.full", strict_template=True),
            headline="Appendix details",
            speaker_notes="Reference table for supporting detail.",
            blocks=[
                PresentationBlock(
                    block_id="appendix-table",
                    kind=PresentationBlockKind.TABLE,
                    content={
                        "rows": [
                            ["Area", "Signal"],
                            ["Audience", audience],
                            ["Goal", goal],
                            ["Tone", tone_label],
                        ]
                    },
                    source_citations=[citation],
                )
            ],
        ),
    ]
    return PresentationSpec(
        title=f"{title} presentation",
        audience=audience,
        language="en-US",
        theme=theme,
        slides=slides,
    )


def _to_api_presentation_spec(
    deck_id: str,
    doc_id: str,
    goal: str,
    planning_spec: PresentationSpec,
) -> PresentationSpecResponse:
    slides = [
        SlideSpecResponse(
            id=slide.slide_id,
            index=index,
            purpose=slide.purpose.value,
            title=slide.headline,
            blocks=[
                {
                    "id": block.block_id,
                    "kind": block.kind.value,
                    "content": _stringify_block_content(block.kind, block.content),
                    "citation": block.source_citations[0].locator if block.source_citations else None,
                }
                for block in slide.blocks
            ],
            template_id=slide.layout_intent.template_key,
            speaker_notes=slide.speaker_notes or None,
        )
        for index, slide in enumerate(planning_spec.slides, start=1)
    ]
    return PresentationSpecResponse(
        id=deck_id,
        doc_id=doc_id,
        title=planning_spec.title,
        goal=goal,
        audience=planning_spec.audience,
        slides=slides,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )


def _stringify_block_content(kind: PresentationBlockKind, content: dict[str, Any]) -> str:
    if kind is PresentationBlockKind.BULLETS:
        return "\n".join(str(item) for item in content.get("items", []))
    if kind is PresentationBlockKind.KPI_CARDS:
        return "\n".join(f"{item.get('value', '')}|{item.get('label', '')}" for item in content.get("items", []))
    if kind is PresentationBlockKind.TABLE:
        return "\n".join(" | ".join(str(cell) for cell in row) for row in content.get("rows", []))
    if kind is PresentationBlockKind.CHART:
        return "\n".join(f"{item.get('label', '')}: {item.get('value', '')}" for item in content.get("series", []))
    for field in ("text", "label", "subtitle", "tagline", "footer_info"):
        if field in content and content[field]:
            return str(content[field])
    return "\n".join(f"{key}: {value}" for key, value in content.items())


def _topic_phrase(doc_id: str, title: str) -> str:
    seed = sum(ord(char) for char in doc_id) % 3
    variants = [
        f"{title} executive summary",
        f"{title} strategic review",
        f"{title} decision brief",
    ]
    return variants[seed]


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


_ALIAS_BY_CANONICAL = _build_alias_index()
