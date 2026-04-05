from __future__ import annotations

from collections.abc import Callable
import base64
from pathlib import Path

import pytest

from pptx_gen.ingestion.schemas import (
    ContentElementType,
    ContentObject,
    DocumentInfo,
    IngestionOptions,
    IngestionRequest,
    SourceInfo,
    SourceType,
)


class DeterministicEmbedder:
    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            encoded = text.encode("utf-8")
            total = sum(encoded)
            length = len(encoded) or 1
            vectors.append(
                [
                    float(length),
                    float(total % 101),
                    float(sum(encoded[::2]) % 103),
                    float(sum(encoded[1::2]) % 107),
                    float(text.count(" ") + 1),
                    float(sum(1 for char in text if char.isdigit())),
                    float(sum(1 for char in text.lower() if char in "aeiou")),
                    float(ord(text[0]) if text else 0),
                ]
            )
        return vectors


@pytest.fixture()
def sample_pdf_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_ingestion.pdf"


@pytest.fixture()
def deterministic_embedder() -> DeterministicEmbedder:
    return DeterministicEmbedder()


@pytest.fixture()
def sample_ingestion_request() -> IngestionRequest:
    return IngestionRequest(
        source=SourceInfo(type=SourceType.UPLOAD, id="src-sample", uri="/tmp/sample.txt"),
        document=DocumentInfo(
            title="Sample",
            mime_type="text/plain",
            language="en",
            elements=[
                ContentObject(
                    doc_id="sample-doc",
                    element_id="e0001",
                    page=1,
                    type=ContentElementType.TITLE,
                    text="Sample Deck",
                ),
                ContentObject(
                    doc_id="sample-doc",
                    element_id="e0002",
                    page=1,
                    type=ContentElementType.PARAGRAPH,
                    text="Contact me at sample@example.com for the weekly report.",
                ),
                ContentObject(
                    doc_id="sample-doc",
                    element_id="e0003",
                    page=1,
                    type=ContentElementType.PARAGRAPH,
                    text="Contact me at sample@example.com for the weekly report.",
                ),
            ],
        ),
        options=IngestionOptions(max_chunk_chars=1200),
    )


@pytest.fixture()
def style_tokens_payload() -> dict:
    return {
        "fonts": {
            "heading": "Aptos Display",
            "body": "Aptos",
            "mono": "Cascadia Code",
        },
        "colors": {
            "bg": "#FFFFFF",
            "text": "#111111",
            "accent": "#0A84FF",
            "muted": "#6B7280",
        },
        "spacing": {
            "margin_in": 0.5,
            "gutter_in": 0.25,
        },
        "images": {
            "source_policy": "provided_only",
            "style_prompt": "clean, editorial, brand-consistent",
        },
    }


@pytest.fixture()
def make_citation() -> Callable[[], dict]:
    def factory() -> dict:
        return {
            "source_id": "doc-finance",
            "locator": "doc-finance:page2",
            "quote": "Revenue reached $29.3M.",
            "confidence": 0.93,
        }

    return factory


@pytest.fixture()
def make_block(make_citation: Callable[[], dict]) -> Callable[..., dict]:
    def factory(
        *,
        block_id: str = "b1",
        kind: str = "text",
        content: dict | None = None,
        with_citation: bool = True,
    ) -> dict:
        payload = content or {"text": "Revenue increased six percent quarter over quarter."}
        return {
            "block_id": block_id,
            "kind": kind,
            "content": payload,
            "source_citations": [make_citation()] if with_citation else [],
            "asset_refs": [],
        }

    return factory


@pytest.fixture()
def make_slide(make_block: Callable[..., dict]) -> Callable[..., dict]:
    def factory(
        *,
        slide_id: str = "s1",
        purpose: str = "content",
        blocks: list[dict] | None = None,
        template_key: str = "content.1col",
    ) -> dict:
        return {
            "slide_id": slide_id,
            "purpose": purpose,
            "layout_intent": {
                "template_key": template_key,
                "strict_template": True,
            },
            "headline": "Performance highlight",
            "speaker_notes": "",
            "blocks": blocks or [make_block()],
        }

    return factory


@pytest.fixture()
def make_presentation_spec(style_tokens_payload: dict, make_slide: Callable[..., dict]) -> Callable[..., dict]:
    def factory(*, slides: list[dict] | None = None, questions_for_user: list[str] | None = None) -> dict:
        return {
            "title": "Quarterly Business Review",
            "audience": "Executive leadership",
            "language": "en-US",
            "theme": {
                "name": "Executive Blue",
                "style_tokens": style_tokens_payload,
            },
            "slides": slides or [make_slide()],
            "questions_for_user": questions_for_user if questions_for_user is not None else [],
        }

    return factory


@pytest.fixture()
def tiny_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn0N0sAAAAASUVORK5CYII="
    )
