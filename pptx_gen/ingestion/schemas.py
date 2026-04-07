"""Pydantic contracts for ingestion and chunking."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"
CHUNK_ID_PATTERN = r"^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:\d+$"
LOCATOR_PATTERN = r"^[A-Za-z0-9_.-]+:page\d+$"


class SourceType(str, Enum):
    UPLOAD = "upload"
    URL = "url"
    DRIVE = "drive"
    SHAREPOINT = "sharepoint"
    DB = "db"
    API = "api"


class ChunkingMode(str, Enum):
    NONE = "none"
    BY_ELEMENT = "by_element"
    SEMANTIC = "semantic"


class ContentElementType(str, Enum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"


class ContentClassification(str, Enum):
    AUDIENCE_CONTENT = "audience_content"
    META_PLANNING = "meta_planning"
    BOILERPLATE = "boilerplate"


class SourcePermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_principals: list[str] = Field(default_factory=list)
    can_share: bool = False


class SourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SourceType
    id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    permissions: SourcePermissions | None = None


class ContentObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    element_id: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    type: ContentElementType
    text: str = Field(min_length=1)
    extensions: dict[str, Any] | None = None

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped


class DocumentInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    language: str = Field(min_length=2)
    elements: list[ContentObject] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_element_ids(self) -> "DocumentInfo":
        seen: set[str] = set()
        for element in self.elements:
            if element.element_id in seen:
                raise ValueError(f"duplicate element_id within document: {element.element_id}")
            seen.add(element.element_id)
        return self


class IngestionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunking: ChunkingMode = ChunkingMode.BY_ELEMENT
    redact_pii: bool = True
    max_chunk_chars: int = Field(default=1200, ge=1, le=1200)


class IngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=SCHEMA_VERSION_PATTERN)
    source: SourceInfo
    document: DocumentInfo
    options: IngestionOptions = Field(default_factory=IngestionOptions)
    extensions: dict[str, Any] | None = None


class ChunkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(pattern=CHUNK_ID_PATTERN)
    chunk_index: int = Field(ge=0)
    doc_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    element_id: str = Field(min_length=1)
    element_type: ContentElementType
    classification: ContentClassification = ContentClassification.AUDIENCE_CONTENT
    page: int | None = Field(default=None, ge=1)
    locator: str = Field(pattern=LOCATOR_PATTERN)
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            raise ValueError("chunk text must not be blank")
        return normalized
