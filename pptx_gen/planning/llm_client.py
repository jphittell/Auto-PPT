"""Concrete structured LLM clients for planning-stage JSON generation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

from pptx_gen.layout.templates import canonical_template_key, list_template_keys
from pptx_gen.planning.schemas import (
    DeckBrief,
    DesignRefinement,
    OutlineSpec,
    PresentationSpec,
    RetrievalPlan,
)


SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "DeckBrief": DeckBrief,
    "OutlineSpec": OutlineSpec,
    "RetrievalPlan": RetrievalPlan,
    "PresentationSpec": PresentationSpec,
    "DesignRefinement": DesignRefinement,
}


class StructuredLLMClientError(RuntimeError):
    """Raised when a structured LLM response cannot be produced or validated."""


@dataclass(slots=True)
class AnthropicStructuredClient:
    """Anthropic Messages API client using strict client-tool output schemas."""

    model: str = "claude-opus-4-6"
    api_key: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.2
    anthropic_client: Any | None = None

    def __post_init__(self) -> None:
        _load_local_env()
        self.api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
        if self.anthropic_client is None:
            if not self.api_key:
                raise StructuredLLMClientError("ANTHROPIC_API_KEY is required for AnthropicStructuredClient")
            self.anthropic_client = _make_anthropic_client(self.api_key)

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
        schema_model = _schema_model_for_name(schema_name)
        tool_name = _tool_name_for_schema(schema_name)
        response = self.anthropic_client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[
                {
                    "name": tool_name,
                    "description": (
                        f"Return a fully populated {schema_name} object that matches the provided JSON schema exactly. "
                        "Do not omit required fields and do not add extra fields."
                    ),
                    "input_schema": schema_model.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
        )
        tool_input = _extract_tool_input(response, tool_name)
        tool_input = _normalize_openai_payload(schema_name, tool_input)
        validated = schema_model.model_validate(tool_input)
        return validated.model_dump(mode="json")


@dataclass(slots=True)
class OpenAIStructuredClient:
    model: str = "gpt-4o"
    api_key: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.2
    openai_client: Any | None = None

    def __post_init__(self) -> None:
        _load_local_env()
        self.api_key = self.api_key or os.getenv("OPENAI_API_KEY")
        if self.openai_client is None:
            if not self.api_key:
                raise StructuredLLMClientError("OPENAI_API_KEY is required for OpenAIStructuredClient")
            self.openai_client = _make_openai_client(self.api_key)

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
        schema_model = _schema_model_for_name(schema_name)
        response = self.openai_client.chat.completions.create(**_openai_request_payload(
            schema_name=schema_name,
            schema_model=schema_model,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        ))
        message_content = response.choices[0].message.content
        if not isinstance(message_content, str):
            raise StructuredLLMClientError(f"OpenAI response for {schema_name} did not contain JSON text")
        parsed = json.loads(message_content)
        parsed = _normalize_openai_payload(schema_name, parsed)
        validated = schema_model.model_validate(parsed)
        return validated.model_dump(mode="json")


def build_default_structured_llm_client() -> OpenAIStructuredClient | AnthropicStructuredClient | None:
    _load_local_env()
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        openai_model = os.getenv("PPTX_GEN_OPENAI_MODEL", "gpt-4o")
        return OpenAIStructuredClient(model=openai_model, api_key=openai_api_key)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = os.getenv("PPTX_GEN_ANTHROPIC_MODEL", "claude-opus-4-6")
    return AnthropicStructuredClient(model=model, api_key=api_key)


def _make_anthropic_client(api_key: str) -> Any:
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise StructuredLLMClientError(
            "anthropic package is required for AnthropicStructuredClient; install the repo dependencies again."
        ) from exc
    return Anthropic(api_key=api_key)


def _make_openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise StructuredLLMClientError(
            "openai package is required for OpenAIStructuredClient; install the repo dependencies again."
        ) from exc
    return OpenAI(api_key=api_key)


def _schema_model_for_name(schema_name: str) -> type[BaseModel]:
    try:
        return SCHEMA_MODELS[schema_name]
    except KeyError as exc:
        raise StructuredLLMClientError(f"unsupported schema_name: {schema_name}") from exc


def _tool_name_for_schema(schema_name: str) -> str:
    return f"return_{schema_name.lower()}"


def _extract_tool_input(response: Any, tool_name: str) -> dict[str, Any]:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            tool_input = getattr(block, "input", None)
            if not isinstance(tool_input, dict):
                raise StructuredLLMClientError(f"tool_use input for {tool_name} was not a JSON object")
            return tool_input
    raise StructuredLLMClientError(f"Anthropic response did not include required tool_use for {tool_name}")


def _load_local_env() -> None:
    dotenv_path = find_dotenv(filename=".env", usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)


def _openai_request_payload(
    *,
    schema_name: str,
    schema_model: type[BaseModel],
    model: str,
    max_tokens: int,
    temperature: float,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if schema_name in {"DeckBrief", "OutlineSpec", "RetrievalPlan"}:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": _sanitize_openai_json_schema(schema_model.model_json_schema()),
                "strict": True,
            },
        }
    else:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _sanitize_openai_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    def sanitize(node: Any) -> Any:
        if isinstance(node, dict):
            sanitized = {key: sanitize(value) for key, value in node.items()}
            if sanitized.get("type") == "object":
                sanitized["additionalProperties"] = False
                if "properties" not in sanitized:
                    sanitized["properties"] = {}
                sanitized["required"] = list(sanitized["properties"].keys())
            return sanitized
        if isinstance(node, list):
            return [sanitize(item) for item in node]
        return node

    return sanitize(schema)


def _normalize_openai_payload(schema_name: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if schema_name == "PresentationSpec":
        return _normalize_presentation_spec_payload(payload)
    if schema_name == "DesignRefinement" and isinstance(payload.get("presentation_spec"), dict):
        normalized = dict(payload)
        normalized["presentation_spec"] = _normalize_presentation_spec_payload(payload["presentation_spec"])
        normalized.setdefault("schema_version", "1.0.0")
        normalized.setdefault("applied", True)
        normalized.setdefault("rationale", [])
        return normalized
    return payload


def _normalize_presentation_spec_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("schema_version", "1.0.0")
    normalized.setdefault("title", _fallback_deck_title(payload))
    normalized.setdefault("audience", payload.get("target_audience") or "General audience")
    normalized.setdefault("language", "en-US")
    normalized.setdefault("questions_for_user", [])
    normalized["theme"] = _normalize_theme_payload(payload.get("theme"), payload.get("style_tokens"))
    slides = payload.get("slides", [])
    if isinstance(slides, list):
        normalized["slides"] = [_normalize_slide_payload(slide, index) for index, slide in enumerate(slides, start=1)]
        normalized["slides"] = _backfill_missing_citations(normalized["slides"])
    return normalized


def _normalize_theme_payload(theme: Any, style_tokens: Any) -> dict[str, Any]:
    if isinstance(theme, dict):
        normalized = dict(theme)
        normalized.setdefault("name", "Auto PPT")
        if "style_tokens" not in normalized and isinstance(style_tokens, dict):
            normalized["style_tokens"] = style_tokens
        return normalized
    if isinstance(style_tokens, dict):
        return {"name": "Auto PPT", "style_tokens": style_tokens}
    return {"name": "Auto PPT", "style_tokens": {}}


def _normalize_slide_payload(slide: Any, index: int) -> dict[str, Any]:
    if not isinstance(slide, dict):
        return {
            "slide_id": f"s{index}",
            "purpose": "content",
            "layout_intent": {"template_key": "content.1col", "strict_template": True},
            "headline": f"Slide {index}",
            "speaker_notes": "",
            "blocks": [
                {
                    "block_id": "b1",
                    "kind": "text",
                    "content": {"text": str(slide)},
                    "source_citations": [],
                    "asset_refs": [],
                }
            ],
        }

    template_key = _normalize_template_key(
        str(slide.get("template_key") or slide.get("layout_intent", {}).get("template_key") or "content.1col")
    )
    purpose = slide.get("purpose") or _infer_slide_purpose(index, template_key, slide)
    headline = slide.get("headline") or slide.get("title") or slide.get("message") or f"Slide {index}"
    blocks = slide.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        content_value = slide.get("content") or slide.get("bullets") or slide.get("summary") or headline
        blocks = [{"kind": "bullets" if isinstance(content_value, list) else "text", "content": content_value}]
    normalized_blocks = [_normalize_block_payload(block, block_index + 1) for block_index, block in enumerate(blocks)]
    template_key = _fit_template_to_blocks(template_key, normalized_blocks)

    return {
        "slide_id": slide.get("slide_id") or f"s{index}",
        "purpose": purpose,
        "layout_intent": {"template_key": template_key, "strict_template": True},
        "headline": headline,
        "speaker_notes": slide.get("speaker_notes") or slide.get("notes") or "",
        "blocks": normalized_blocks,
    }


def _normalize_block_payload(block: Any, index: int) -> dict[str, Any]:
    if not isinstance(block, dict):
        return {
            "block_id": f"b{index}",
            "kind": "text",
            "content": {"text": str(block)},
            "source_citations": [],
            "asset_refs": [],
        }

    kind = str(block.get("kind") or _infer_block_kind(block)).lower()
    content = block.get("content")
    if kind == "bullets":
        if isinstance(content, list):
            content = {"items": [str(item) for item in content]}
        elif isinstance(content, str):
            content = {"items": [content]}
        elif not isinstance(content, dict):
            content = {"items": [str(content or "")]}
    elif kind in {"text", "callout", "quote"}:
        if isinstance(content, str):
            content = {"text": content}
        elif not isinstance(content, dict):
            content = {"text": str(content or "")}
    elif kind == "table":
        if not isinstance(content, dict):
            content = {"columns": ["Column"], "rows": [[str(content or "")]]}
    elif kind == "chart":
        if not isinstance(content, dict) or not isinstance(content.get("data"), list) or not content.get("data"):
            kind = "text"
            content = {"text": _fallback_visual_text(block, default="Chart summary")}
    elif kind == "image":
        image_path = _extract_candidate_asset_path(content)
        if image_path is None or not image_path.exists() or not image_path.is_file():
            kind = "text"
            content = {"text": _fallback_visual_text(block, default="Visual summary")}
        else:
            content = {"path": str(image_path)}
    else:
        if not isinstance(content, dict):
            content = {"text": str(content or "")}
            kind = "text"

    return {
        "block_id": block.get("block_id") or f"b{index}",
        "kind": kind,
        "content": content,
        "source_citations": block.get("source_citations") or [],
        "asset_refs": block.get("asset_refs") or [],
    }


def _infer_slide_purpose(index: int, template_key: str, slide: dict[str, Any]) -> str:
    if index == 1 or template_key == "title.hero":
        return "title"
    if "agenda" in template_key:
        return "agenda"
    if "appendix" in template_key:
        return "appendix"
    if "summary" in template_key or str(slide.get("headline", "")).lower().startswith("key takeaway"):
        return "summary"
    return "content"


def _infer_block_kind(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, list):
        return "bullets"
    if isinstance(content, dict):
        if "items" in content:
            return "bullets"
        if {"columns", "rows"} <= set(content.keys()):
            return "table"
        if "data" in content and "chart_type" in content:
            return "chart"
        if any(key in content for key in ("path", "local_path", "file_path", "asset_path", "uri")):
            return "image"
    return "text"


def _fallback_deck_title(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("slides"), list) and payload["slides"]:
        first_slide = payload["slides"][0]
        if isinstance(first_slide, dict):
            return str(first_slide.get("headline") or first_slide.get("title") or "Generated Presentation")
    return "Generated Presentation"


def _fit_template_to_blocks(template_key: str, blocks: list[dict[str, Any]]) -> str:
    kinds = {str(block.get("kind")) for block in blocks}
    if template_key == "content.2col.text_image" and not {"image", "chart"} & kinds:
        return "content.1col"
    if template_key == "chart.full" and "chart" not in kinds:
        return "content.1col"
    if template_key == "table.full" and "table" not in kinds:
        return "content.1col"
    if template_key == "content.3col.cards" and "kpi_cards" not in kinds:
        return "content.1col"
    if template_key == "kpi.3up" and len(blocks) < 3:
        return "content.1col"
    return template_key


def _extract_candidate_asset_path(content: Any) -> Path | None:
    candidate: str | None = None
    if isinstance(content, str):
        candidate = content.strip()
    elif isinstance(content, dict):
        for key in ("path", "local_path", "file_path", "asset_path", "uri"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                candidate = value.strip()
                break
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return None
    return Path(candidate)


def _fallback_visual_text(block: dict[str, Any], *, default: str) -> str:
    for key in ("caption", "description", "alt_text", "text", "summary", "title"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    content = block.get("content")
    if isinstance(content, dict):
        for key in ("caption", "description", "alt_text", "text", "summary", "title"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return default


def _normalize_template_key(value: str) -> str:
    candidate = canonical_template_key(value)
    if candidate in set(list_template_keys()):
        return candidate

    lowered = value.strip().lower()
    if lowered.startswith("summary"):
        return "content.1col"
    if lowered.startswith("content") or lowered.startswith("body"):
        return "content.1col"
    if "comparison" in lowered or "matrix" in lowered:
        return "table.full"
    if lowered.startswith("title"):
        return "title.hero"
    if lowered.startswith("agenda"):
        return "agenda.list"
    return "content.1col"


def _backfill_missing_citations(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deck_citations: list[dict[str, Any]] = []
    for slide in slides:
        for block in slide.get("blocks", []):
            citations = block.get("source_citations")
            if isinstance(citations, list):
                for citation in citations:
                    if isinstance(citation, dict) and citation.get("source_id") and citation.get("locator"):
                        if citation not in deck_citations:
                            deck_citations.append(citation)

    citation_required_purposes = {"content", "summary", "appendix"}
    citation_required_kinds = {"text", "bullets", "table", "chart", "quote", "callout", "kpi_cards"}

    updated_slides: list[dict[str, Any]] = []
    for slide in slides:
        slide_copy = dict(slide)
        slide_citations: list[dict[str, Any]] = []
        for block in slide.get("blocks", []):
            citations = block.get("source_citations")
            if isinstance(citations, list):
                for citation in citations:
                    if isinstance(citation, dict) and citation.get("source_id") and citation.get("locator"):
                        if citation not in slide_citations:
                            slide_citations.append(citation)
        fallback = slide_citations[:1] or deck_citations[:1]

        updated_blocks: list[dict[str, Any]] = []
        for block in slide.get("blocks", []):
            block_copy = dict(block)
            citations = block_copy.get("source_citations")
            if (
                slide_copy.get("purpose") in citation_required_purposes
                and block_copy.get("kind") in citation_required_kinds
                and not citations
                and fallback
            ):
                block_copy["source_citations"] = list(fallback)
            updated_blocks.append(block_copy)
        slide_copy["blocks"] = updated_blocks
        updated_slides.append(slide_copy)

    return updated_slides
