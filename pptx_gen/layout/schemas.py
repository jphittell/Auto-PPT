"""Pydantic contracts for style tokens and resolved layout."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


HEX_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class ImageSourcePolicy(str, Enum):
    PROVIDED_ONLY = "provided_only"
    STOCK = "stock"
    AI = "ai"


class PageSize(str, Enum):
    WIDESCREEN = "16:9"
    STANDARD = "4:3"


class ResolvedElementKind(str, Enum):
    TEXTBOX = "textbox"
    IMAGE = "image"
    SHAPE = "shape"
    TABLE = "table"
    CHART = "chart"


class FontTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1)
    body: str = Field(min_length=1)
    mono: str = Field(min_length=1)


class ColorTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bg: str = Field(pattern=HEX_PATTERN)
    text: str = Field(pattern=HEX_PATTERN)
    accent: str = Field(pattern=HEX_PATTERN)
    muted: str = Field(pattern=HEX_PATTERN)


class SpacingTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    margin_in: float = Field(gt=0)
    gutter_in: float = Field(gt=0)


class ImageTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_policy: ImageSourcePolicy = ImageSourcePolicy.PROVIDED_ONLY
    style_prompt: str = ""


class StyleTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fonts: FontTokens
    colors: ColorTokens
    spacing: SpacingTokens
    images: ImageTokens = Field(default_factory=ImageTokens)


class ResolvedElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str = Field(min_length=1)
    kind: ResolvedElementKind
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    w: float = Field(gt=0)
    h: float = Field(gt=0)
    z: int = Field(ge=0)
    data_ref: str = Field(min_length=1)
    style_ref: str | None = None
    payload: dict[str, Any] | None = None


class ResolvedSlideLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    elements: list[ResolvedElement] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_element_ids(self) -> "ResolvedSlideLayout":
        seen: set[str] = set()
        for element in self.elements:
            if element.element_id in seen:
                raise ValueError(f"duplicate element_id within slide: {element.element_id}")
            seen.add(element.element_id)
        return self


class ResolvedDeckLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    deck_id: str = Field(min_length=1)
    page_size: PageSize = PageSize.WIDESCREEN
    slides: list[ResolvedSlideLayout] = Field(min_length=1)
    extensions: dict[str, Any] | None = None

