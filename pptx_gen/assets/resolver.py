"""Local-only asset resolution for renderer-ready layouts."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pptx_gen.assets.chart_renderer import render_chart_to_png
from pptx_gen.layout.schemas import ResolvedDeckLayout, ResolvedElement, ResolvedElementKind, ResolvedSlideLayout
from pptx_gen.renderer.slide_ops import extract_local_asset_path


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


class ResolvedAssetBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: AssetManifest
    resolved_layout: ResolvedDeckLayout
    asset_dir: str = Field(min_length=1)


def resolve_assets(
    layout: ResolvedDeckLayout,
    *,
    cache_dir: str | Path,
) -> ResolvedAssetBundle:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    manifest_assets: list[AssetRecord] = []
    slides: list[ResolvedSlideLayout] = []

    for slide in layout.slides:
        elements = []
        for element in slide.elements:
            updated_element, asset_record = _resolve_element_asset(element, cache_dir)
            if updated_element is not None:
                elements.append(updated_element)
            if asset_record is not None:
                manifest_assets.append(asset_record)
        slides.append(ResolvedSlideLayout(slide_id=slide.slide_id, elements=elements))

    return ResolvedAssetBundle(
        manifest=AssetManifest(assets=manifest_assets),
        resolved_layout=ResolvedDeckLayout(
            deck_id=layout.deck_id,
            page_size=layout.page_size,
            slides=slides,
            extensions=layout.extensions,
        ),
        asset_dir=str(cache_dir),
    )


def _resolve_element_asset(
    element: ResolvedElement,
    cache_dir: Path,
) -> tuple[ResolvedElement | None, AssetRecord | None]:
    if element.kind not in {ResolvedElementKind.IMAGE, ResolvedElementKind.CHART}:
        return element, None

    payload = dict(element.payload or {})
    content = payload.get("content")
    if content in (None, "", {}, []):
        return None, None

    if element.kind is ResolvedElementKind.IMAGE:
        source_path = extract_local_asset_path(content)
        if source_path is None:
            raise FileNotFoundError(f"image element {element.element_id} is missing a local asset path")
        cached_path, sha256 = _copy_local_asset(source_path, cache_dir)
        payload["content"] = _merge_asset_content(content, cached_path)
    else:
        if not isinstance(content, dict):
            raise ValueError(f"chart element {element.element_id} must contain a chart spec dict")
        cache_name = f"{_safe_name(element.element_id)}.png"
        cached_path = render_chart_to_png(content, cache_dir / cache_name)
        sha256 = _hash_file(cached_path)
        payload["content"] = {**content, "path": str(cached_path)}

    updated = element.model_copy(update={"payload": payload})
    asset = AssetRecord(
        asset_id=element.element_id,
        type=AssetType.IMAGE,
        uri=str(cached_path),
        sha256=sha256,
        source_uri=_source_uri_for_content(content),
        created_at=datetime.now(timezone.utc),
    )
    return updated, asset


def _copy_local_asset(source_path: Path, cache_dir: Path) -> tuple[Path, str]:
    # Remote URL rejection happens earlier while content is still raw string data via
    # extract_local_asset_path(); this helper only copies an already-local Path.
    if not source_path.exists():
        raise FileNotFoundError(f"asset path does not exist: {source_path}")

    sha256 = _hash_file(source_path)
    destination = cache_dir / f"{sha256}{source_path.suffix.lower() or '.bin'}"
    if not destination.exists():
        shutil.copy2(source_path, destination)
    return destination, sha256


def _merge_asset_content(content: object, cached_path: Path) -> dict[str, object]:
    if isinstance(content, dict):
        merged = dict(content)
        merged["path"] = str(cached_path)
        return merged
    if isinstance(content, str):
        return {"path": str(cached_path), "source_path": content}
    return {"path": str(cached_path)}


def _source_uri_for_content(content: object) -> str | None:
    if isinstance(content, dict):
        for key in ("path", "local_path", "file_path", "asset_path", "uri"):
            value = content.get(key)
            if isinstance(value, str):
                return value
        return None
    if isinstance(content, str):
        return content
    return None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in "-._" else "-" for char in value)
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-") or "asset"
