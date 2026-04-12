"""Regression tests for the three bugs identified in the
2026-04-11 exec-summary prompt-leakage investigation.

These guard against:
  Bug 1: ordinal "Supporting Detail N" outline padding
  Bug 2: /api/slide/preview regenerate ignoring source documents
  Bug 3: literal "Add supporting detail" filler in the deterministic fallback

See Input/Assets/plan-exec-summary-prompt-leakage-2026-04-11.md for context.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

import pptx_gen.api as api_module
from pptx_gen.api import (
    _derive_source_topics,
    _fallback_structure_content,
    _normalize_outline_exact_count,
    _retrieve_grounding_for_preview,
)
from pptx_gen.ingestion.schemas import (
    ChunkRecord,
    ContentClassification,
    ContentElementType,
    IngestionRequest,
    SourceInfo,
    SourceType,
    DocumentInfo,
    ContentObject,
    IngestionOptions,
)
from pptx_gen.pipeline import IngestionIndexResult
from pptx_gen.planning.schemas import (
    OutlineItem,
    OutlineSpec,
    SlidePurpose,
)


PLACEHOLDER_HEADLINE_RE = re.compile(r"^Supporting Detail \d+$", re.IGNORECASE)
PLACEHOLDER_CARD_TEXT = "Add supporting detail."


def _reset_api_state() -> None:
    api_module._store.clear()
    api_module._INGESTED_VECTOR_STORES.clear()
    api_module._EMBEDDER = None
    api_module._STRUCTURED_LLM_CLIENT = False
    api_module._clear_preview_structure_cache()
    api_module._GENERATION_JOBS.clear()
    api_module._GENERATION_QUEUE = None
    api_module._GENERATION_QUEUE_LOOP = None
    api_module._GENERATION_WORKER_TASK = None


def _make_chunk(
    *,
    chunk_index: int,
    text: str,
    element_type: ContentElementType = ContentElementType.PARAGRAPH,
    classification: ContentClassification = ContentClassification.AUDIENCE_CONTENT,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"doc-bugs:e{chunk_index:04d}:{chunk_index}",
        chunk_index=chunk_index,
        doc_id="doc-bugs",
        source_id="src-bugs",
        element_id=f"e{chunk_index:04d}",
        element_type=element_type,
        classification=classification,
        page=1,
        locator="src-bugs:page1",
        text=text,
    )


def _minimal_ingestion_request() -> IngestionRequest:
    return IngestionRequest(
        source=SourceInfo(type=SourceType.UPLOAD, id="src-bugs", uri="/tmp/bugs.txt"),
        document=DocumentInfo(
            title="Bug Regression Doc",
            mime_type="text/plain",
            language="en",
            elements=[
                ContentObject(
                    doc_id="doc-bugs",
                    element_id="e0001",
                    page=1,
                    type=ContentElementType.HEADING,
                    text="Signal Heading One",
                ),
            ],
        ),
        options=IngestionOptions(max_chunk_chars=1200),
    )


def _make_ingestion_result(chunks: list[ChunkRecord]) -> IngestionIndexResult:
    return IngestionIndexResult(
        doc_id="doc-bugs",
        source_id="src-bugs",
        chunks=chunks,
        chunk_ids=[chunk.chunk_id for chunk in chunks],
        ingestion_request=_minimal_ingestion_request(),
        n_chunks=len(chunks),
        n_elements=len(chunks),
    )


def _baseline_outline(n: int) -> OutlineSpec:
    items = [
        OutlineItem(
            slide_id=f"s{i}",
            purpose=SlidePurpose.CONTENT,
            headline=f"Planned topic {i}",
            message=f"Message for topic {i}",
            evidence_queries=[f"topic {i}"],
            template_key="headline.evidence",
        )
        for i in range(1, n + 1)
    ]
    return OutlineSpec(outline=items, questions_for_user=[])


# --------------------------------------------------------------------------
# Bug 1: outline padder must not emit ordinal "Supporting Detail N" items
# --------------------------------------------------------------------------


def test_outline_normalize_never_emits_supporting_detail_placeholder() -> None:
    """Padding with doc-derived topics replaces the old ordinal placeholders."""
    base = _baseline_outline(3)
    headings = [
        _make_chunk(
            chunk_index=i,
            text=f"Architecture Pillar {i}",
            element_type=ContentElementType.HEADING,
        )
        for i in range(1, 8)
    ]
    ingestion = _make_ingestion_result(headings)

    normalized = _normalize_outline_exact_count(
        base,
        target_count=8,
        goal="Explain architecture",
        ingestion_results=[ingestion],
    )

    assert len(normalized.outline) == 8
    for item in normalized.outline:
        assert not PLACEHOLDER_HEADLINE_RE.match(item.headline or ""), (
            f"Unexpected ordinal placeholder headline: {item.headline!r}"
        )


def test_outline_normalize_truncates_when_no_source_topics_available() -> None:
    """Without doc-derived topics we truncate instead of emitting placeholders."""
    base = _baseline_outline(3)

    normalized = _normalize_outline_exact_count(
        base,
        target_count=10,
        goal="Explain architecture",
        ingestion_results=None,
    )

    # We cannot reach target_count, so we stay at the real-content count
    # rather than inventing "Supporting Detail N" filler.
    assert len(normalized.outline) == 3
    for item in normalized.outline:
        assert not PLACEHOLDER_HEADLINE_RE.match(item.headline or "")


def test_outline_normalize_is_stable_when_source_matches_existing() -> None:
    """Source topics that duplicate existing headlines are deduped."""
    base = _baseline_outline(2)
    # Chunk whose trimmed headline matches an existing outline item.
    duplicate = _make_chunk(
        chunk_index=1,
        text="Planned topic 1",
        element_type=ContentElementType.HEADING,
    )
    novel = _make_chunk(
        chunk_index=2,
        text="Novel Topic Alpha",
        element_type=ContentElementType.HEADING,
    )
    ingestion = _make_ingestion_result([duplicate, novel])

    normalized = _normalize_outline_exact_count(
        base,
        target_count=3,
        goal="Explain something",
        ingestion_results=[ingestion],
    )

    assert len(normalized.outline) == 3
    headlines = [item.headline for item in normalized.outline]
    # The duplicate was skipped; the novel topic became the new slide.
    assert any("Novel Topic Alpha" in h for h in headlines)
    assert headlines.count("Planned topic 1") == 1


def test_derive_source_topics_falls_back_to_paragraph_when_no_headings() -> None:
    """When the doc has no HEADING chunks, the first sentence of a paragraph
    becomes a reasonable topic candidate rather than "Supporting Detail N"."""
    paragraph = _make_chunk(
        chunk_index=1,
        text="The retrieval system indexes chunks by semantic similarity. "
        "It supports multi-doc merging and stable deduplication.",
        element_type=ContentElementType.PARAGRAPH,
    )
    ingestion = _make_ingestion_result([paragraph])

    topics = _derive_source_topics(existing_items=[], ingestion_results=[ingestion])

    assert topics
    headline, _message = topics[0]
    assert "retrieval" in headline.lower()
    assert not PLACEHOLDER_HEADLINE_RE.match(headline)


# --------------------------------------------------------------------------
# Bug 3: fallback structurer must not emit "Add supporting detail" filler
# --------------------------------------------------------------------------


def test_fallback_exec_summary_omits_placeholder_card_text() -> None:
    """Even when fewer real points are available than the template wants,
    the fallback must never emit the literal "Add supporting detail." string.
    """
    content = "Only one real point worth saying here."
    structured = _fallback_structure_content(content, "Title", "exec.summary")

    # Crawl every string in the resulting blocks and assert no filler.
    def iter_strings(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from iter_strings(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from iter_strings(v)

    all_strings = list(iter_strings(structured))
    assert all_strings
    assert PLACEHOLDER_CARD_TEXT not in all_strings
    # Also reject the variant with whitespace/capitalization wobble.
    assert not any(s.strip().lower() == PLACEHOLDER_CARD_TEXT.lower() for s in all_strings)


def test_fallback_prefers_grounding_text_over_raw_content() -> None:
    """When grounding_text is passed, it must drive the structured output,
    not the raw editor `content` (which may carry residual prompt leakage).
    """
    raw_notes = "Create a consulting-style deck that explains this document clearly."
    grounding = (
        "The Q4 pipeline coverage reached 3.2x, exceeding the 2.5x target. "
        "Enterprise win rate climbed to 38%, led by the platform segment."
    )

    structured = _fallback_structure_content(
        raw_notes,
        "Pipeline Review",
        "exec.summary",
        grounding_text=grounding,
    )

    # Flatten and check: the structured output draws from `grounding`,
    # not from the raw prompt-like notes.
    flat = []

    def walk(obj):
        if isinstance(obj, str):
            flat.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(structured)
    body = " ".join(flat).lower()
    assert "pipeline coverage" in body or "win rate" in body
    assert "consulting-style deck" not in body


# --------------------------------------------------------------------------
# Bug 2: /api/slide/preview honours deck_id and pulls from ingested doc
# --------------------------------------------------------------------------


def test_slide_preview_request_accepts_deck_id() -> None:
    """The wire schema must accept the optional deck_id field."""
    from pptx_gen.api_schemas import SlidePreviewRequest

    req = SlidePreviewRequest(
        slide_id="s1",
        title="Pipeline",
        purpose="content",
        template_id="exec.summary",
        content="seed",
        audience="execs",
        goal="review",
        deck_id="deck-abc",
    )
    assert req.deck_id == "deck-abc"

    # Older clients that don't send deck_id must still parse.
    req2 = SlidePreviewRequest(
        slide_id="s1",
        title="Pipeline",
        purpose="content",
        template_id="exec.summary",
        content="seed",
        audience="execs",
        goal="review",
    )
    assert req2.deck_id is None


def test_retrieve_grounding_returns_empty_for_unknown_deck() -> None:
    _reset_api_state()
    assert _retrieve_grounding_for_preview(deck_id=None, title="t", content="c") == ""
    assert _retrieve_grounding_for_preview(deck_id="deck-missing", title="t", content="c") == ""


def test_retrieve_grounding_pulls_from_ingested_deck(
    monkeypatch, sample_pdf_path, deterministic_embedder
) -> None:
    """After ingest + generate, grounding retrieval returns real doc text."""
    _reset_api_state()
    monkeypatch.setattr(api_module, "_get_embedder", lambda: deterministic_embedder)
    client = TestClient(api_module.app)

    ingest = client.post(
        "/api/ingest",
        files={"file": ("sample.pdf", sample_pdf_path.read_bytes(), "application/pdf")},
    )
    assert ingest.status_code == 200
    doc_id = ingest.json()["doc_id"]

    planned = client.post(
        "/api/plan",
        json={
            "doc_ids": [doc_id],
            "goal": "Board update",
            "audience": "Executive Steering Committee",
            "tone": 15,
            "slide_count": 6,
        },
    )
    assert planned.status_code == 200
    draft = planned.json()

    generated = client.post(
        "/api/generate",
        json={
            "draft_id": draft["draft_id"],
            "outline": [
                {
                    "id": slide["id"],
                    "index": slide["index"],
                    "purpose": slide["purpose"],
                    "title": slide["title"],
                    "template_id": slide["template_id"],
                }
                for slide in draft["slides"]
            ],
            "selected_template_id": "headline.evidence",
            "brand_kit": {
                "logo_data_url": None,
                "primary_color": "#112233",
                "accent_color": "#445566",
                "font_pair": "DM Sans/DM Serif Display",
            },
        },
    )
    assert generated.status_code == 200
    deck_id = generated.json()["id"]

    grounding = _retrieve_grounding_for_preview(
        deck_id=deck_id,
        title=draft["slides"][1]["title"],
        content="placeholder notes",
    )
    assert grounding, "expected non-empty grounding text from ingested deck"
    # Should be real source text, not the user's prompt leakage.
    assert "consulting-style deck" not in grounding.lower()
