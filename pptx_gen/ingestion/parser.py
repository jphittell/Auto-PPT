"""Structure-first parsing for local files."""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pptx_gen.ingestion.schemas import (
    ContentElementType,
    ContentObject,
    DocumentInfo,
    IngestionOptions,
    IngestionRequest,
    SourceInfo,
    SourceType,
)


class PDFDependencyError(RuntimeError):
    """Raised when PDF parsing dependencies are unavailable."""


@dataclass(slots=True)
class _FallbackMetadata:
    page_number: int


@dataclass(slots=True)
class _FallbackElement:
    text: str
    metadata: _FallbackMetadata
    category: str = ""


class Title(_FallbackElement):
    pass


class ListItem(_FallbackElement):
    pass


class NarrativeText(_FallbackElement):
    pass


def parse_source(
    source_path: str | Path,
    *,
    title: str | None = None,
    language: str = "en",
    options: IngestionOptions | None = None,
) -> IngestionRequest:
    path = Path(source_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"source file not found: {path}")

    options = options or IngestionOptions()
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    doc_id = _make_doc_id(path)
    source_id = _make_source_id(path)
    raw_elements = _partition_file(path)

    normalized_elements: list[ContentObject] = []
    title_claimed = False
    for index, raw_element in enumerate(raw_elements, start=1):
        text = _extract_text(raw_element)
        if not text:
            continue

        page_number = _extract_page_number(raw_element)
        element_type = _map_element_type(raw_element, page_number, title_claimed)
        if element_type is ContentElementType.TITLE:
            title_claimed = True

        normalized_elements.append(
            ContentObject(
                doc_id=doc_id,
                element_id=f"e{index:04d}",
                page=page_number,
                type=element_type,
                text=text,
            )
        )

    if not normalized_elements:
        raise ValueError(f"no parseable content found in {path}")

    document_title = title or _infer_title(path, normalized_elements)
    return IngestionRequest(
        source=SourceInfo(type=SourceType.UPLOAD, id=source_id, uri=str(path)),
        document=DocumentInfo(
            title=document_title,
            mime_type=mime_type,
            language=language,
            elements=normalized_elements,
        ),
        options=options,
    )


def _partition_file(path: Path) -> list[Any]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _partition_pdf(path)
    if suffix in {".txt", ".md"}:
        return _partition_text(path)
    raise ValueError(f"unsupported source type: {path.suffix}")


def _partition_pdf(path: Path) -> list[Any]:
    try:
        from unstructured.partition.pdf import partition_pdf
    except Exception:
        return _partition_pdf_fallback(path)

    try:
        return partition_pdf(filename=str(path), strategy="fast")
    except Exception:
        return _partition_pdf_fallback(path)


def _partition_text(path: Path) -> list[Any]:
    from unstructured.partition.text import partition_text

    return partition_text(filename=str(path))


def _extract_text(raw_element: Any) -> str:
    value = getattr(raw_element, "text", None)
    if value is None:
        value = str(raw_element)
    normalized = re.sub(r"\s+", " ", value or "").strip()
    return normalized


def _partition_pdf_fallback(path: Path) -> list[Any]:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - environment specific
        raise PDFDependencyError(
            "PDF parsing requires either the Unstructured PDF stack or the lightweight pypdf fallback."
        ) from exc

    reader = PdfReader(str(path))
    elements: list[Any] = []
    title_claimed = False

    for page_number, page in enumerate(reader.pages, start=1):
        page_text = re.sub(r"\r\n?", "\n", page.extract_text() or "")
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        if not lines:
            continue

        paragraph_buffer: list[str] = []

        def flush_paragraph() -> None:
            if not paragraph_buffer:
                return
            elements.append(
                NarrativeText(
                    text=" ".join(paragraph_buffer).strip(),
                    metadata=_FallbackMetadata(page_number=page_number),
                )
            )
            paragraph_buffer.clear()

        for line in lines:
            if not title_claimed:
                elements.append(
                    Title(
                        text=line,
                        metadata=_FallbackMetadata(page_number=page_number),
                    )
                )
                title_claimed = True
                continue

            if re.match(r"^[-*•]\s+", line):
                flush_paragraph()
                elements.append(
                    ListItem(
                        text=re.sub(r"^[-*•]\s+", "", line).strip(),
                        metadata=_FallbackMetadata(page_number=page_number),
                    )
                )
                continue

            if len(line.split()) <= 10 and line == line.title():
                flush_paragraph()
                elements.append(
                    Title(
                        text=line,
                        metadata=_FallbackMetadata(page_number=page_number),
                    )
                )
                continue

            paragraph_buffer.append(line)

        flush_paragraph()

    if not elements:
        raise PDFDependencyError("PDF fallback could not extract text from the file.")
    return elements


def _extract_page_number(raw_element: Any) -> int | None:
    metadata = getattr(raw_element, "metadata", None)
    page_number = getattr(metadata, "page_number", None)
    if page_number is None:
        return None
    try:
        return int(page_number)
    except (TypeError, ValueError):
        return None


def _map_element_type(raw_element: Any, page_number: int | None, title_claimed: bool) -> ContentElementType:
    name = type(raw_element).__name__.lower()
    category = str(getattr(raw_element, "category", "")).lower()
    signature = f"{name} {category}"

    if "figurecaption" in signature or "caption" in signature:
        return ContentElementType.CAPTION
    if "image" in signature or "figure" in signature:
        return ContentElementType.FIGURE
    if "table" in signature:
        return ContentElementType.TABLE
    if "listitem" in signature or "list_item" in signature:
        return ContentElementType.LIST_ITEM
    if "title" in signature:
        if not title_claimed and (page_number in {None, 1}):
            return ContentElementType.TITLE
        return ContentElementType.HEADING
    if "header" in signature or "heading" in signature:
        return ContentElementType.HEADING
    return ContentElementType.PARAGRAPH


def _infer_title(path: Path, elements: list[ContentObject]) -> str:
    for element in elements:
        if element.type is ContentElementType.TITLE:
            return element.text
    return path.stem.replace("_", " ").strip() or path.name


def _make_doc_id(path: Path) -> str:
    slug = _slugify(path.stem)
    return slug or "document"


def _make_source_id(path: Path) -> str:
    slug = _slugify(path.stem)
    return f"src-{slug or 'document'}"


def _slugify(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-_.").lower()
