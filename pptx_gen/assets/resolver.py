"""Asset resolution boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AssetType(str, Enum):
    IMAGE = "image"
    ICON = "icon"
    FONT = "font"
    DATA_ATTACHMENT = "data_attachment"


class AssetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1)
    type: AssetType
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    source_uri: str | None = None
    license: str | None = None
    attribution: str | None = None
    created_at: datetime | None = None


class AssetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    assets: list[AssetRecord] = Field(default_factory=list)


def resolve_assets(*args, **kwargs) -> AssetManifest:
    # TODO: download, cache, and hash image and chart assets before rendering.
    raise NotImplementedError("Asset resolution is not implemented in Phase 1.")

