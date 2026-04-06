"""Element-aware chunking with deduplication and PII redaction."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from pptx_gen.ingestion.schemas import ChunkRecord, ContentObject, IngestionRequest


PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
)


def chunk_document(request: IngestionRequest) -> list[ChunkRecord]:
    """Chunk ids are deterministic: ``{doc_id}:{element_id}:{chunk_index}``."""

    elements = _deduplicate_elements(
        request.document.elements,
        redact_pii=request.options.redact_pii,
    )
    chunks: list[ChunkRecord] = []
    max_chars = request.options.max_chunk_chars
    for element in elements:
        parts = _split_text(element.text, max_chars=max_chars)
        for index, part in enumerate(parts):
            chunk_id = f"{element.doc_id}:{element.element_id}:{index}"
            page_value = element.page or 1
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    chunk_index=index,
                    doc_id=element.doc_id,
                    source_id=request.source.id,
                    element_id=element.element_id,
                    element_type=element.type,
                    page=element.page,
                    locator=f"{element.doc_id}:page{page_value}",
                    text=part,
                )
            )
    return chunks


def _deduplicate_elements(elements: Iterable[ContentObject], *, redact_pii: bool) -> list[ContentObject]:
    deduped: list[ContentObject] = []
    seen_hashes: set[str] = set()
    for element in elements:
        text = _redact_pii(element.text) if redact_pii else _normalize_text(element.text)
        if not text:
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        deduped.append(element.model_copy(update={"text": text}))
    return deduped


def _redact_pii(text: str) -> str:
    redacted = text
    for label, pattern in PII_PATTERNS:
        redacted = pattern.sub(f"[REDACTED_{label.upper()}]", redacted)
    return _normalize_text(redacted)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_text(text: str, *, max_chars: int) -> list[str]:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return [normalized]

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(sentence) <= max_chars:
            current = sentence
            continue
        chunks.extend(_split_long_sentence(sentence, max_chars=max_chars))
        current = ""
    if current:
        chunks.append(current)
    return chunks


def _split_long_sentence(text: str, *, max_chars: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        proposed_length = current_length + len(word) + (1 if current else 0)
        if proposed_length <= max_chars:
            current.append(word)
            current_length = proposed_length
            continue
        if current:
            chunks.append(" ".join(current))
        current = [word]
        current_length = len(word)
    if current:
        chunks.append(" ".join(current))
    return chunks

