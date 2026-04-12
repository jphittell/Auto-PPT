"""Pluggable persistence for Auto-PPT API state.

Two backends:
  - MemoryStore   — in-process dicts (default, zero-dep, current behavior)
  - SQLiteStore   — single-file persistence surviving restarts

Select via AUTOPPT_STORE_BACKEND env var ("memory" | "sqlite").

Vector stores and the embedder are *compute caches*, not durable state.
They live outside the store and are rebuilt from stored chunks on demand.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

import pptx_gen.pipeline as pipeline_module
from pptx_gen.api_schemas import (
    ChatMessageResponse,
    IngestResponse,
)
from pptx_gen.planning.schemas import (
    DeckBrief,
    OutlineSpec,
    PresentationSpec,
)


# ---------------------------------------------------------------------------
# DraftState as a Pydantic model (was a dataclass) for JSON round-tripping
# ---------------------------------------------------------------------------


class DraftState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1)
    doc_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    tone_label: str = Field(min_length=1)
    slide_count: int = Field(ge=1)
    brief: DeckBrief
    outline: OutlineSpec
    created_at: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# StoredDeck — single canonical store for a generated deck
# ---------------------------------------------------------------------------


class StoredDeck(BaseModel):
    """Single canonical representation of a generated deck.

    Replaces the former dual-store pattern where ``decks`` held the API
    response shape (``PresentationSpecResponse``) and ``raw_specs`` held the
    planning shape (``PresentationSpec``).  Those two representations could
    drift silently.

    Now only ``PresentationSpec`` is persisted here together with the
    API-layer metadata (``deck_id``, ``doc_ids``, ``goal``, ``created_at``).
    ``PresentationSpecResponse`` is derived on-read in ``api.py`` via
    ``_to_api_presentation_spec``, so there is exactly one source of truth.
    """

    model_config = ConfigDict(extra="forbid")

    deck_id: str = Field(min_length=1)
    doc_ids: list[str] = Field(min_length=1)
    goal: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    spec: PresentationSpec


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Store(Protocol):
    """Minimal contract for Auto-PPT state persistence."""

    # -- ingested docs --
    def get_ingested_doc(self, doc_id: str) -> IngestResponse | None: ...
    def put_ingested_doc(self, doc_id: str, doc: IngestResponse) -> None: ...
    def has_ingested_doc(self, doc_id: str) -> bool: ...

    # -- ingestion results (chunks + metadata) --
    def get_ingestion_result(self, doc_id: str) -> pipeline_module.IngestionIndexResult | None: ...
    def put_ingestion_result(self, doc_id: str, result: pipeline_module.IngestionIndexResult) -> None: ...
    def has_ingestion_result(self, doc_id: str) -> bool: ...

    # -- drafts --
    def get_draft(self, draft_id: str) -> DraftState | None: ...
    def put_draft(self, draft_id: str, draft: DraftState) -> None: ...

    # -- deck specs (single canonical store) --
    def get_deck_spec(self, deck_id: str) -> StoredDeck | None: ...
    def put_deck_spec(self, deck_id: str, stored: StoredDeck) -> None: ...
    def has_deck(self, deck_id: str) -> bool: ...
    def count_decks(self) -> int: ...

    # -- chat sessions --
    def get_chat_session(self, session_id: str) -> list[ChatMessageResponse] | None: ...
    def put_chat_session(self, session_id: str, messages: list[ChatMessageResponse]) -> None: ...

    # -- lifecycle --
    def clear(self) -> None: ...


# ---------------------------------------------------------------------------
# MemoryStore — drop-in for current dict-based behavior
# ---------------------------------------------------------------------------


class MemoryStore:
    """In-process dict store. Zero overhead, no persistence."""

    def __init__(self) -> None:
        self._ingested_docs: dict[str, IngestResponse] = {}
        self._ingestion_results: dict[str, pipeline_module.IngestionIndexResult] = {}
        self._drafts: dict[str, DraftState] = {}
        self._deck_specs: dict[str, StoredDeck] = {}
        self._chat_sessions: dict[str, list[ChatMessageResponse]] = {}

    # -- ingested docs --
    def get_ingested_doc(self, doc_id: str) -> IngestResponse | None:
        return self._ingested_docs.get(doc_id)

    def put_ingested_doc(self, doc_id: str, doc: IngestResponse) -> None:
        self._ingested_docs[doc_id] = doc

    def has_ingested_doc(self, doc_id: str) -> bool:
        return doc_id in self._ingested_docs

    # -- ingestion results --
    def get_ingestion_result(self, doc_id: str) -> pipeline_module.IngestionIndexResult | None:
        return self._ingestion_results.get(doc_id)

    def put_ingestion_result(self, doc_id: str, result: pipeline_module.IngestionIndexResult) -> None:
        self._ingestion_results[doc_id] = result

    def has_ingestion_result(self, doc_id: str) -> bool:
        return doc_id in self._ingestion_results

    # -- drafts --
    def get_draft(self, draft_id: str) -> DraftState | None:
        return self._drafts.get(draft_id)

    def put_draft(self, draft_id: str, draft: DraftState) -> None:
        self._drafts[draft_id] = draft

    # -- deck specs --
    def get_deck_spec(self, deck_id: str) -> StoredDeck | None:
        return self._deck_specs.get(deck_id)

    def put_deck_spec(self, deck_id: str, stored: StoredDeck) -> None:
        self._deck_specs[deck_id] = stored

    def has_deck(self, deck_id: str) -> bool:
        return deck_id in self._deck_specs

    def count_decks(self) -> int:
        return len(self._deck_specs)

    # -- chat sessions --
    def get_chat_session(self, session_id: str) -> list[ChatMessageResponse] | None:
        return self._chat_sessions.get(session_id)

    def put_chat_session(self, session_id: str, messages: list[ChatMessageResponse]) -> None:
        self._chat_sessions[session_id] = messages

    # -- lifecycle --
    def clear(self) -> None:
        self._ingested_docs.clear()
        self._ingestion_results.clear()
        self._drafts.clear()
        self._deck_specs.clear()
        self._chat_sessions.clear()


# ---------------------------------------------------------------------------
# SQLiteStore — file-backed persistence
# ---------------------------------------------------------------------------

# Allowlists for SQL identifier interpolation.
# All (table, key_column) pairs must be registered here before use.
# This prevents SQL injection if a future caller ever passes a non-literal value.
_VALID_TABLE_KEY_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("ingested_docs",    "doc_id"),
    ("ingestion_results","doc_id"),
    ("drafts",           "draft_id"),
    ("deck_specs",       "deck_id"),
    ("chat_sessions",    "session_id"),
})
_VALID_TABLES: frozenset[str] = frozenset(t for t, _ in _VALID_TABLE_KEY_PAIRS)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingested_docs (
    doc_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestion_results (
    doc_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deck_specs (
    deck_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""


class SQLiteStore:
    """Single-file SQLite store. Thread-safe via a per-instance lock.

    All Pydantic models are stored as JSON text in the ``payload`` column
    and deserialized on read. This avoids schema migrations when model
    fields change — the JSON round-trip handles optional/default fields
    naturally.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA_SQL)
                conn.commit()
            finally:
                conn.close()

    # -- generic helpers --

    @staticmethod
    def _check_table_key(table: str, key_col: str) -> None:
        if (table, key_col) not in _VALID_TABLE_KEY_PAIRS:
            raise ValueError(
                f"Disallowed table/column combination: {table!r}/{key_col!r}. "
                "Add it to _VALID_TABLE_KEY_PAIRS to permit it."
            )

    @staticmethod
    def _check_table(table: str) -> None:
        if table not in _VALID_TABLES:
            raise ValueError(
                f"Disallowed table name: {table!r}. "
                "Add it to _VALID_TABLES to permit it."
            )

    def _get(self, table: str, key_col: str, key: str) -> str | None:
        self._check_table_key(table, key_col)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    f"SELECT payload FROM {table} WHERE {key_col} = ?", (key,)
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()

    def _put(self, table: str, key_col: str, key: str, payload: str) -> None:
        self._check_table_key(table, key_col)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({key_col}, payload) VALUES (?, ?)",
                    (key, payload),
                )
                conn.commit()
            finally:
                conn.close()

    def _has(self, table: str, key_col: str, key: str) -> bool:
        self._check_table_key(table, key_col)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    f"SELECT 1 FROM {table} WHERE {key_col} = ?", (key,)
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def _count(self, table: str) -> int:
        self._check_table(table)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                return row[0] if row else 0
            finally:
                conn.close()

    # -- ingested docs --
    def get_ingested_doc(self, doc_id: str) -> IngestResponse | None:
        raw = self._get("ingested_docs", "doc_id", doc_id)
        return IngestResponse.model_validate_json(raw) if raw else None

    def put_ingested_doc(self, doc_id: str, doc: IngestResponse) -> None:
        self._put("ingested_docs", "doc_id", doc_id, doc.model_dump_json())

    def has_ingested_doc(self, doc_id: str) -> bool:
        return self._has("ingested_docs", "doc_id", doc_id)

    # -- ingestion results --
    def get_ingestion_result(self, doc_id: str) -> pipeline_module.IngestionIndexResult | None:
        raw = self._get("ingestion_results", "doc_id", doc_id)
        return pipeline_module.IngestionIndexResult.model_validate_json(raw) if raw else None

    def put_ingestion_result(self, doc_id: str, result: pipeline_module.IngestionIndexResult) -> None:
        self._put("ingestion_results", "doc_id", doc_id, result.model_dump_json())

    def has_ingestion_result(self, doc_id: str) -> bool:
        return self._has("ingestion_results", "doc_id", doc_id)

    # -- drafts --
    def get_draft(self, draft_id: str) -> DraftState | None:
        raw = self._get("drafts", "draft_id", draft_id)
        return DraftState.model_validate_json(raw) if raw else None

    def put_draft(self, draft_id: str, draft: DraftState) -> None:
        self._put("drafts", "draft_id", draft_id, draft.model_dump_json())

    # -- deck specs --
    def get_deck_spec(self, deck_id: str) -> StoredDeck | None:
        raw = self._get("deck_specs", "deck_id", deck_id)
        return StoredDeck.model_validate_json(raw) if raw else None

    def put_deck_spec(self, deck_id: str, stored: StoredDeck) -> None:
        self._put("deck_specs", "deck_id", deck_id, stored.model_dump_json())

    def has_deck(self, deck_id: str) -> bool:
        return self._has("deck_specs", "deck_id", deck_id)

    def count_decks(self) -> int:
        return self._count("deck_specs")

    # -- chat sessions --
    def get_chat_session(self, session_id: str) -> list[ChatMessageResponse] | None:
        raw = self._get("chat_sessions", "session_id", session_id)
        if raw is None:
            return None
        items = json.loads(raw)
        return [ChatMessageResponse.model_validate(item) for item in items]

    def put_chat_session(self, session_id: str, messages: list[ChatMessageResponse]) -> None:
        payload = json.dumps([msg.model_dump() for msg in messages])
        self._put("chat_sessions", "session_id", session_id, payload)

    # -- lifecycle --
    def clear(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                for table in _VALID_TABLES:
                    self._check_table(table)  # belt-and-suspenders: validates before interpolation
                    conn.execute(f"DELETE FROM {table}")
                conn.commit()
            finally:
                conn.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_store(backend: str = "memory", **kwargs: Any) -> Store:
    """Instantiate a store from the backend name.

    Args:
        backend: "memory" or "sqlite".
        **kwargs: Passed to the backend constructor.
            For "sqlite": db_path (str|Path, required).
    """
    if backend == "memory":
        return MemoryStore()
    if backend == "sqlite":
        db_path = kwargs.get("db_path")
        if not db_path:
            raise ValueError("SQLiteStore requires a 'db_path' argument")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return SQLiteStore(db_path=db_path)
    raise ValueError(f"Unknown store backend: {backend!r}. Use 'memory' or 'sqlite'.")
