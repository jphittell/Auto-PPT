"""Element-aware chunking with deduplication and PII redaction."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from pptx_gen.ingestion.schemas import (
    ChunkRecord,
    ContentClassification,
    ContentElementType,
    ContentObject,
    IngestionRequest,
)


PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
)

META_PLANNING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:codex|claude|llm|model)\s+should\b", re.IGNORECASE),
    re.compile(r"\b(?:should implement|must ensure|needs to|todo|fixme|hack|note:)\b", re.IGNORECASE),
    re.compile(r"\b(?:upsert|idempotent|sha-256|faiss|qdrant|endpoint|api call|function signature)\b", re.IGNORECASE),
)
HEADING_META_VERB_PATTERN = re.compile(r"^#*\s*(?:implement|wire|add|fix|update|refactor|prevent|plan|ensure)\b", re.IGNORECASE)
BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^page\s+\d+(?:\s+of\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^draft$", re.IGNORECASE),
    re.compile(r"^confidential$", re.IGNORECASE),
    re.compile(r"^copyright\b", re.IGNORECASE),
)
SECTION_LABEL_PATTERN = re.compile(
    r"^(?:business content|planning notes|executive overview|implementation notes|technical details|"
    r"key findings|background|introduction|appendix)$",
    re.IGNORECASE,
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
            classification = _classify_chunk(part, element.type)
            if element.page is not None:
                locator = f"{element.doc_id}:page{element.page}"
            else:
                locator = f"{element.doc_id}:chunk{len(chunks)}"
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    chunk_index=index,
                    doc_id=element.doc_id,
                    source_id=request.source.id,
                    element_id=element.element_id,
                    element_type=element.type,
                    classification=classification,
                    page=element.page,
                    locator=locator,
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


def _classify_chunk(text: str, element_type: ContentElementType) -> ContentClassification:
    normalized = _normalize_text(text)
    if not normalized:
        return ContentClassification.BOILERPLATE

    lowered = normalized.lower()
    if any(pattern.search(normalized) for pattern in META_PLANNING_PATTERNS):
        return ContentClassification.META_PLANNING

    if element_type is ContentElementType.HEADING and HEADING_META_VERB_PATTERN.match(normalized):
        return ContentClassification.META_PLANNING

    if len(normalized) < 20 and any(pattern.match(normalized) for pattern in BOILERPLATE_PATTERNS):
        return ContentClassification.BOILERPLATE

    if element_type is ContentElementType.HEADING and _is_section_label(normalized):
        return ContentClassification.BOILERPLATE

    if element_type in {ContentElementType.CAPTION, ContentElementType.FIGURE} and len(normalized.split()) < 4:
        return ContentClassification.BOILERPLATE

    return ContentClassification.AUDIENCE_CONTENT


def _is_section_label(text: str) -> bool:
    return bool(SECTION_LABEL_PATTERN.match(_normalize_text(text)))


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
