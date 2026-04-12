"""Concrete structured LLM clients for planning-stage JSON generation."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_log = logging.getLogger("pptx_gen.llm_client")


def _fallback(reason: str, context: str, recovery: str) -> None:
    """Emit a structured WARNING whenever a normalization fallback fires.

    These warnings are intentional degradations — the LLM returned something
    unexpected and we recovered rather than crashing. Run a log search on
    'llm_fallback' to see how often each fallback fires and whether prompt
    fixes are working.
    """
    _log.warning(
        "llm_fallback",
        extra={"event": "llm_fallback", "reason": reason, "context": context, "recovery": recovery},
    )

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

from pptx_gen.layout.templates import canonical_template_key, list_template_keys
from pptx_gen.api_schemas import SlidePreviewLLMResponse
from pptx_gen.planning.schemas import (
    DeckBrief,
    DesignRefinement,
    OutlineSpec,
    PresentationSpec,
    RetrievalPlan,
    SlideRemediationSpec,
)


SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "DeckBrief": DeckBrief,
    "OutlineSpec": OutlineSpec,
    "RetrievalPlan": RetrievalPlan,
    "PresentationSpec": PresentationSpec,
    "DesignRefinement": DesignRefinement,
    "SlidePreviewLLMResponse": SlidePreviewLLMResponse,
    "SlideRemediationSpec": SlideRemediationSpec,
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
    max_tokens: int = 16384  # gpt-4o max output; 4096 was too small for large PresentationSpec responses
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
        choice = response.choices[0]
        message_content = choice.message.content
        if not isinstance(message_content, str):
            raise StructuredLLMClientError(f"OpenAI response for {schema_name} did not contain JSON text")
        try:
            parsed = json.loads(message_content)
        except json.JSONDecodeError as exc:
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason == "length":
                raise StructuredLLMClientError(
                    f"OpenAI response for {schema_name} was truncated (hit max_tokens={self.max_tokens}). "
                    "Reduce slide count or chunk context."
                ) from exc
            raise StructuredLLMClientError(
                f"OpenAI response for {schema_name} was not valid JSON: {exc}"
            ) from exc
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
        return normalized
    if schema_name == "SlidePreviewLLMResponse":
        return _normalize_slide_preview_payload(payload)
    if schema_name == "SlideRemediationSpec":
        return _normalize_slide_remediation_payload(payload)
    return payload


def _normalize_slide_preview_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM output that uses 'type' instead of 'kind' and 'content' instead of 'items'/'text'."""
    normalized = dict(payload)
    blocks = normalized.get("blocks")
    if not isinstance(blocks, list):
        return normalized
    fixed_blocks: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            fixed_blocks.append(block)
            continue
        fixed = dict(block)
        # LLM often returns "type" instead of "kind"
        if "kind" not in fixed and "type" in fixed:
            fixed["kind"] = fixed.pop("type")
        kind = fixed.get("kind", "text")
        # LLM often returns "content" as a list (for bullets) or string (for text/callout)
        if "content" in fixed and kind == "bullets" and "items" not in fixed:
            content = fixed.pop("content")
            if isinstance(content, list):
                fixed["items"] = [str(item) for item in content]
            elif isinstance(content, str):
                fixed["items"] = [content]
        elif "content" in fixed and kind in {"text", "callout"} and "text" not in fixed:
            fixed["text"] = str(fixed.pop("content"))
        fixed_blocks.append(fixed)
    normalized["blocks"] = fixed_blocks
    return normalized


def _normalize_slide_remediation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM output for SlideRemediationSpec — fix blocks inside each remediated slide."""
    normalized = dict(payload)
    if not isinstance(normalized.get("schema_version"), str):
        normalized["schema_version"] = "1.0.0"
    remediations = normalized.get("remediations")
    if not isinstance(remediations, list):
        normalized["remediations"] = []
        return normalized
    fixed_remediations = []
    for item in remediations:
        if not isinstance(item, dict):
            continue
        fixed_item = dict(item)
        blocks = fixed_item.get("blocks")
        if not isinstance(blocks, list):
            fixed_item["blocks"] = []
        else:
            fixed_item["blocks"] = [_normalize_block_payload(b, idx) for idx, b in enumerate(blocks, 1)]
        fixed_remediations.append(fixed_item)
    normalized["remediations"] = fixed_remediations
    return normalized


def _normalize_presentation_spec_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if not normalized.get("title"):
        _fallback("missing_field", "PresentationSpec.title", "set to 'Untitled Presentation'")
        normalized["title"] = "Untitled Presentation"
    if not normalized.get("audience"):
        _fallback("missing_field", "PresentationSpec.audience", "set to 'General'")
        normalized["audience"] = "General"
    if not normalized.get("language"):
        _fallback("missing_field", "PresentationSpec.language", "set to 'en-US'")
        normalized["language"] = "en-US"
    if not isinstance(normalized.get("questions_for_user"), list):
        _fallback("missing_field", "PresentationSpec.questions_for_user", "set to []")
        normalized["questions_for_user"] = []
    normalized["theme"] = _normalize_theme_payload(payload.get("theme"), payload.get("style_tokens"))
    slides = payload.get("slides", [])
    if isinstance(slides, list):
        normalized["slides"] = [_normalize_slide_payload(slide, index) for index, slide in enumerate(slides, start=1)]
        normalized["slides"] = _backfill_missing_citations(normalized["slides"])
    else:
        raise StructuredLLMClientError("PresentationSpec payload must contain a slides list")
    return normalized


def _normalize_theme_payload(theme: Any, style_tokens: Any) -> dict[str, Any]:
    if isinstance(theme, dict):
        normalized = dict(theme)
        if not normalized.get("name"):
            _fallback("missing_field", "theme.name", "set to 'ONAC'")
            normalized["name"] = "ONAC"
        if "style_tokens" not in normalized:
            _fallback("missing_field", "theme.style_tokens", "carried from outer payload")
            normalized["style_tokens"] = style_tokens
        return normalized
    _fallback("missing_field", "theme (entire object)", "reconstructed from style_tokens")
    return {"name": "ONAC", "style_tokens": style_tokens}


def _normalize_slide_payload(slide: Any, index: int) -> dict[str, Any]:
    if not isinstance(slide, dict):
        _fallback("non_object_slide", f"slide index {index}", "replaced with empty dict")
        slide = {}

    raw_layout_intent = slide.get("layout_intent")
    raw_template_key = slide.get("template_key")
    if isinstance(raw_layout_intent, dict):
        raw_template_key = raw_template_key or raw_layout_intent.get("template_key")
    if not isinstance(raw_template_key, str) or not raw_template_key.strip():
        _fallback("missing_template_key", f"slide index {index}", "defaulted to headline.evidence")
        raw_template_key = "headline.evidence"
    template_key = _normalize_template_key(raw_template_key)
    purpose = slide.get("purpose") or _infer_slide_purpose(index, template_key, slide)
    headline = slide.get("headline") or slide.get("title") or slide.get("message") or f"Slide {index}"
    blocks = slide.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        _fallback("missing_blocks", f"slide index {index} ({headline!r})", "created minimal bullets block")
        blocks = [{"block_id": "b1", "kind": "bullets", "content": {"items": [headline]}}]
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
        _fallback("non_object_block", f"block index {index}", "coerced to text block")
        block = {"kind": "text", "content": str(block or "")}

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
            _fallback("chart_missing_data", f"block index {index}", "degraded to text block")
            kind = "text"
            content = {"text": str(content) if content else ""}
    elif kind == "image":
        image_path = _extract_candidate_asset_path(content)
        if image_path is None or not image_path.exists() or not image_path.is_file():
            _fallback("image_invalid_path", f"block index {index} path={content!r}", "degraded to text block")
            kind = "text"
            content = {"text": str(content) if content else ""}
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
    if index == 1 or template_key == "title.cover":
        return "title"
    if "closing" in template_key:
        return "closing"
    if "section" in template_key:
        return "section"
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


def _fit_template_to_blocks(template_key: str, blocks: list[dict[str, Any]]) -> str:
    kinds = {str(block.get("kind")) for block in blocks}
    if template_key == "compare.2col" and len(blocks) < 2:
        _fallback("template_block_mismatch", f"compare.2col got {len(blocks)} block(s)", "downgraded to headline.evidence")
        return "headline.evidence"
    if template_key == "chart.takeaway" and "chart" not in kinds:
        _fallback("template_block_mismatch", "chart.takeaway got no chart block", "downgraded to headline.evidence")
        return "headline.evidence"
    if template_key == "kpi.big" and len(blocks) < 3:
        _fallback("template_block_mismatch", f"kpi.big got {len(blocks)} block(s)", "downgraded to headline.evidence")
        return "headline.evidence"
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


def _normalize_template_key(value: str) -> str:
    candidate = canonical_template_key(value)
    if candidate in set(list_template_keys()):
        return candidate
    _fallback("unknown_template_key", f"model returned {value!r}", "defaulted to headline.evidence")
    return "headline.evidence"


def _backfill_missing_citations(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citation_required_purposes = {"content", "summary", "closing"}
    citation_required_kinds = {"text", "bullets", "table", "chart", "quote", "callout", "kpi_cards"}

    for slide in slides:
        for block in slide.get("blocks", []):
            citations = block.get("source_citations")
            if (
                slide.get("purpose") in citation_required_purposes
                and block.get("kind") in citation_required_kinds
                and not citations
            ):
                _fallback(
                    "missing_citations",
                    f"slide {slide.get('slide_id', '?')} block {block.get('block_id', '?')}",
                    "set to [] for prompt_chain backfill",
                )
                block["source_citations"] = []

    return slides
