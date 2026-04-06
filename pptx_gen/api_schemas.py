"""FastAPI request and response models for the web UI."""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    chunk_count: int = Field(ge=0)
    title: str = Field(min_length=1)
    element_types: dict[str, int] = Field(default_factory=dict)


HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class PlanDeckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_ids: list[str] = Field(min_length=1)
    goal: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    tone: float = Field(ge=0, le=100)
    slide_count: int = Field(ge=6, le=20)


class ContentBlockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    content: str = ""
    data: dict[str, Any] | None = None
    citation: str | None = None


class SlideSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    index: int = Field(ge=1)
    purpose: str = Field(min_length=1)
    archetype: str | None = None
    title: str = Field(min_length=1)
    blocks: list[ContentBlockResponse] = Field(default_factory=list)
    template_id: str = Field(min_length=1)
    speaker_notes: str | None = None


class ThemeSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    primary_color: str = Field(pattern=HEX_COLOR_PATTERN)
    accent_color: str = Field(pattern=HEX_COLOR_PATTERN)
    heading_font: str = Field(min_length=1)
    body_font: str = Field(min_length=1)
    logo_present: bool = False


class PresentationSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    doc_ids: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    slides: list[SlideSpecResponse] = Field(default_factory=list)
    created_at: str = Field(min_length=1)
    theme: ThemeSummaryResponse | None = None


class PlanDeckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    doc_ids: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    slides: list[SlideSpecResponse] = Field(default_factory=list)
    created_at: str = Field(min_length=1)


class TemplateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    alias: str = Field(min_length=1)
    columns: int = Field(ge=1)
    description: str = Field(min_length=1)
    deck_default_allowed: bool = False


class OutlineSlideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    index: int = Field(ge=1)
    purpose: str = Field(min_length=1)
    title: str = Field(min_length=1)
    template_id: str = Field(min_length=1)


class BrandKitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo_data_url: str | None = None
    primary_color: str = Field(pattern=HEX_COLOR_PATTERN)
    accent_color: str = Field(pattern=HEX_COLOR_PATTERN)
    font_pair: str = Field(min_length=1)


class GenerateDeckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1)
    outline: list[OutlineSlideRequest] = Field(min_length=1)
    selected_template_id: str = Field(min_length=1)
    brand_kit: BrandKitRequest


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["pdf", "pptx"]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    phase: Literal["1"] = "1"
    ingest: bool = True
    generation: Literal["live"] = "live"


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"] = "assistant"
    content: str = Field(min_length=1)


class ChatGenerateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    inferred_goal: str = Field(min_length=1)
    inferred_audience: str = Field(min_length=1)
    inferred_slide_count: int = Field(ge=1)
    messages: list[ChatMessageResponse] = Field(default_factory=list)
    deck: PresentationSpecResponse
