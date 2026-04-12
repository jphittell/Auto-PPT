"""Unit tests for the Store abstraction (MemoryStore and SQLiteStore)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pptx_gen.api_schemas import (
    ChatMessageResponse,
    IngestResponse,
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
    SlidePurpose,
    SlideSpec,
)
from pptx_gen.pipeline import IngestionIndexResult
from pptx_gen.ingestion.schemas import (
    ChunkRecord,
    ContentClassification,
    ContentElementType,
    ContentObject,
    DocumentInfo,
    IngestionOptions,
    IngestionRequest,
    SourceInfo,
    SourceType,
)
from pptx_gen.store import (
    DraftState,
    MemoryStore,
    SQLiteStore,
    StoredDeck,
    create_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_ingest_response() -> IngestResponse:
    return IngestResponse(
        doc_id="doc-1",
        chunk_count=5,
        title="Test Doc",
        element_types={"paragraph": 5},
    )


def _sample_ingestion_result() -> IngestionIndexResult:
    return IngestionIndexResult(
        doc_id="doc-1",
        source_id="src-1",
        ingestion_request=IngestionRequest(
            source=SourceInfo(type=SourceType.UPLOAD, id="src-1", uri="/tmp/test.txt"),
            document=DocumentInfo(
                title="Test Doc",
                mime_type="text/plain",
                language="en",
                elements=[
                    ContentObject(
                        doc_id="doc-1",
                        element_id="e0001",
                        page=1,
                        type=ContentElementType.PARAGRAPH,
                        text="Sample paragraph text.",
                    ),
                ],
            ),
            options=IngestionOptions(max_chunk_chars=1200),
        ),
        n_elements=1,
        n_chunks=1,
        chunk_ids=["doc-1:e0001:0"],
        chunks=[
            ChunkRecord(
                chunk_id="doc-1:e0001:0",
                chunk_index=0,
                doc_id="doc-1",
                source_id="src-1",
                element_id="e0001",
                element_type=ContentElementType.PARAGRAPH,
                classification=ContentClassification.AUDIENCE_CONTENT,
                page=1,
                locator="src-1:page1",
                text="Sample paragraph text.",
            ),
        ],
    )


def _sample_draft() -> DraftState:
    return DraftState(
        draft_id="draft-abc",
        doc_ids=["doc-1"],
        source_ids=["src-1"],
        title="Test Deck",
        goal="Explain testing",
        audience="Engineers",
        tone_label="executive",
        slide_count=3,
        brief=DeckBrief(
            audience="Engineers",
            goal="Explain testing",
            tone="executive",
            slide_count_target=3,
            source_corpus_ids=["src-1"],
        ),
        outline=OutlineSpec(
            outline=[
                OutlineItem(
                    slide_id="s1",
                    purpose=SlidePurpose.TITLE,
                    headline="Test Deck",
                    message="Overview",
                    evidence_queries=[],
                    template_key="title.cover",
                ),
            ],
            questions_for_user=[],
        ),
        created_at="2026-04-11T12:00:00",
    )


def _sample_stored_deck() -> StoredDeck:
    from pptx_gen.layout.schemas import StyleTokens
    from pptx_gen.pipeline import ONAC_STYLE_TOKENS

    return StoredDeck(
        deck_id="deck-1",
        doc_ids=["doc-1"],
        goal="Explain testing",
        created_at="2026-04-11T12:00:00",
        spec=PresentationSpec(
            title="Test Deck",
            audience="Engineers",
            theme=DeckTheme(name="ONAC", style_tokens=StyleTokens(**ONAC_STYLE_TOKENS)),
            slides=[
                SlideSpec(
                    slide_id="s1",
                    purpose=SlidePurpose.TITLE,
                    layout_intent=LayoutIntent(template_key="title.cover"),
                    headline="Test Deck",
                    blocks=[
                        PresentationBlock(
                            block_id="b1",
                            kind=PresentationBlockKind.TEXT,
                            content={"text": "Overview"},
                        ),
                    ],
                ),
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Parametrized tests: run the same suite against both backends
# ---------------------------------------------------------------------------


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return MemoryStore()
    db_path = tmp_path / "test.db"
    return SQLiteStore(db_path=db_path)


def test_ingested_doc_round_trip(store):
    doc = _sample_ingest_response()
    assert store.get_ingested_doc("doc-1") is None
    assert not store.has_ingested_doc("doc-1")

    store.put_ingested_doc("doc-1", doc)
    assert store.has_ingested_doc("doc-1")

    retrieved = store.get_ingested_doc("doc-1")
    assert retrieved is not None
    assert retrieved.doc_id == "doc-1"
    assert retrieved.chunk_count == 5
    assert retrieved.title == "Test Doc"


def test_ingestion_result_round_trip(store):
    result = _sample_ingestion_result()
    assert not store.has_ingestion_result("doc-1")

    store.put_ingestion_result("doc-1", result)
    assert store.has_ingestion_result("doc-1")

    retrieved = store.get_ingestion_result("doc-1")
    assert retrieved is not None
    assert retrieved.doc_id == "doc-1"
    assert len(retrieved.chunks) == 1
    assert retrieved.chunks[0].text == "Sample paragraph text."


def test_draft_round_trip(store):
    draft = _sample_draft()
    assert store.get_draft("draft-abc") is None

    store.put_draft("draft-abc", draft)

    retrieved = store.get_draft("draft-abc")
    assert retrieved is not None
    assert retrieved.draft_id == "draft-abc"
    assert retrieved.goal == "Explain testing"
    assert len(retrieved.outline.outline) == 1


def test_deck_spec_round_trip(store):
    stored = _sample_stored_deck()
    assert store.get_deck_spec("deck-1") is None
    assert not store.has_deck("deck-1")
    assert store.count_decks() == 0

    store.put_deck_spec("deck-1", stored)
    assert store.has_deck("deck-1")
    assert store.count_decks() == 1

    retrieved = store.get_deck_spec("deck-1")
    assert retrieved is not None
    assert retrieved.deck_id == "deck-1"
    assert retrieved.doc_ids == ["doc-1"]
    assert retrieved.goal == "Explain testing"
    assert retrieved.created_at == "2026-04-11T12:00:00"
    assert retrieved.spec.title == "Test Deck"
    assert len(retrieved.spec.slides) == 1


def test_chat_session_round_trip(store):
    messages = [
        ChatMessageResponse(role="user", content="Make a deck"),
        ChatMessageResponse(role="assistant", content="Done."),
    ]
    assert store.get_chat_session("chat-1") is None

    store.put_chat_session("chat-1", messages)

    retrieved = store.get_chat_session("chat-1")
    assert retrieved is not None
    assert len(retrieved) == 2
    assert retrieved[0].role == "user"
    assert retrieved[1].content == "Done."


def test_clear_removes_all(store):
    store.put_ingested_doc("doc-1", _sample_ingest_response())
    store.put_ingestion_result("doc-1", _sample_ingestion_result())
    store.put_draft("draft-abc", _sample_draft())
    store.put_deck_spec("deck-1", _sample_stored_deck())
    store.put_chat_session("chat-1", [ChatMessageResponse(role="user", content="hi")])

    store.clear()

    assert store.get_ingested_doc("doc-1") is None
    assert not store.has_ingestion_result("doc-1")
    assert store.get_draft("draft-abc") is None
    assert store.count_decks() == 0
    assert store.get_deck_spec("deck-1") is None
    assert store.get_chat_session("chat-1") is None


def test_upsert_overwrites(store):
    doc1 = _sample_ingest_response()
    store.put_ingested_doc("doc-1", doc1)

    doc2 = IngestResponse(doc_id="doc-1", chunk_count=10, title="Updated Doc", element_types={})
    store.put_ingested_doc("doc-1", doc2)

    retrieved = store.get_ingested_doc("doc-1")
    assert retrieved is not None
    assert retrieved.chunk_count == 10
    assert retrieved.title == "Updated Doc"


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def test_create_store_memory():
    s = create_store("memory")
    assert isinstance(s, MemoryStore)


def test_create_store_sqlite(tmp_path):
    db = tmp_path / "test.db"
    s = create_store("sqlite", db_path=str(db))
    assert isinstance(s, SQLiteStore)
    assert db.exists()


def test_create_store_unknown():
    with pytest.raises(ValueError, match="Unknown store backend"):
        create_store("redis")


def test_create_store_sqlite_missing_path():
    with pytest.raises(ValueError, match="db_path"):
        create_store("sqlite")
