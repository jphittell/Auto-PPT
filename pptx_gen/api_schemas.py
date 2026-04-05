"""FastAPI request and response models for the web UI."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    chunk_count: int = Field(ge=0)
    title: str = Field(min_length=1)
    element_types: dict[str, int] = Field(default_factory=dict)


class GenerateDeckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    tone: float = Field(ge=0, le=100)
    slide_count: int = Field(ge=6, le=20)


class ContentBlockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    content: str = ""
    citation: str | None = None


class SlideSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    index: int = Field(ge=1)
    purpose: str = Field(min_length=1)
    title: str = Field(min_length=1)
    blocks: list[ContentBlockResponse] = Field(default_factory=list)
    template_id: str = Field(min_length=1)
    speaker_notes: str | None = None


class PresentationSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
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


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["pdf", "pptx"]


class UpgradeRequiredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["upgrade_required"] = "upgrade_required"
    tier: Literal["pro"] = "pro"


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    phase: Literal["1"] = "1"
    ingest: bool = True
    generation: Literal["mock"] = "mock"
