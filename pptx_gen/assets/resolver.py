"""Asset resolution for renderer-ready layouts."""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from pptx_gen.assets.chart_renderer import render_chart_to_png
from pptx_gen.assets.unsplash import UnsplashAssetSource, UnsplashPhoto
from pptx_gen.layout.schemas import ResolvedDeckLayout, ResolvedElement, ResolvedElementKind, ResolvedSlideLayout
from pptx_gen.renderer.slide_ops import extract_local_asset_path


logger = logging.getLogger(__name__)


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


class _ResolvedImageAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, object]
    cached_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    source_uri: str | None = None
    license: str | None = None
    attribution: str | None = None


def resolve_assets(
    layout: ResolvedDeckLayout,
    *,
    cache_dir: str | Path,
    unsplash_source: UnsplashAssetSource | None = None,
) -> ResolvedAssetBundle:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    unsplash_source = unsplash_source or UnsplashAssetSource(cache_dir=cache_dir)

    manifest_assets: list[AssetRecord] = []
    slides: list[ResolvedSlideLayout] = []

    for slide in layout.slides:
        elements = []
        for element in slide.elements:
            updated_element, asset_record = _resolve_element_asset(element, cache_dir, unsplash_source)
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
    unsplash_source: UnsplashAssetSource,
) -> tuple[ResolvedElement | None, AssetRecord | None]:
    if element.kind not in {ResolvedElementKind.IMAGE, ResolvedElementKind.CHART}:
        return element, None

    payload = dict(element.payload or {})
    content = payload.get("content")
    if content in (None, "", {}, []):
        return None, None

    if element.kind is ResolvedElementKind.IMAGE:
        resolved_image = _resolve_image_asset(content, cache_dir, unsplash_source, element_id=element.element_id)
        if resolved_image is None:
            return None, None
        cached_path = Path(resolved_image.cached_path)
        sha256 = resolved_image.sha256
        payload["content"] = resolved_image.content
        source_uri = resolved_image.source_uri
        license_name = resolved_image.license
        attribution = resolved_image.attribution
    else:
        if not isinstance(content, dict):
            raise ValueError(f"chart element {element.element_id} must contain a chart spec dict")
        cache_name = f"{_safe_name(element.element_id)}.png"
        cached_path = render_chart_to_png(content, cache_dir / cache_name)
        sha256 = _hash_file(cached_path)
        payload["content"] = {**content, "path": str(cached_path)}
        source_uri = _source_uri_for_content(content)
        license_name = None
        attribution = None

    updated = element.model_copy(update={"payload": payload})
    asset = AssetRecord(
        asset_id=element.element_id,
        type=AssetType.IMAGE,
        uri=str(cached_path),
        sha256=sha256,
        source_uri=source_uri,
        license=license_name,
        attribution=attribution,
        created_at=datetime.now(timezone.utc),
    )
    return updated, asset


def _resolve_image_asset(
    content: object,
    cache_dir: Path,
    unsplash_source: UnsplashAssetSource,
    *,
    element_id: str,
) -> _ResolvedImageAsset | None:
    source_path = extract_local_asset_path(content)
    query = _search_query_for_image_content(content)

    if source_path is None:
        if query is None:
            raise FileNotFoundError(f"image element {element_id} is missing a local asset path")
        return _resolve_unsplash_image(content, unsplash_source, element_id=element_id, query=query)

    if source_path.exists():
        cached_path, sha256 = _copy_local_asset(source_path, cache_dir)
        return _ResolvedImageAsset(
            content=_merge_asset_content(content, cached_path),
            cached_path=str(cached_path),
            sha256=sha256,
            source_uri=_source_uri_for_content(content),
        )

    if query is None:
        raise FileNotFoundError(f"asset path does not exist: {source_path}")

    return _resolve_unsplash_image(content, unsplash_source, element_id=element_id, query=query)


def _resolve_unsplash_image(
    content: object,
    unsplash_source: UnsplashAssetSource,
    *,
    element_id: str,
    query: str,
) -> _ResolvedImageAsset | None:
    photo = unsplash_source.fetch_photo(query)
    if photo is None:
        logger.warning("Unsplash fallback did not resolve image element '%s' for query '%s'", element_id, query)
        return None

    cached_path = Path(photo.cached_path)
    return _ResolvedImageAsset(
        content=_merge_unsplash_content(content, photo),
        cached_path=str(cached_path),
        sha256=_hash_file(cached_path),
        source_uri=photo.url,
        license="Unsplash License",
        attribution=_unsplash_attribution(photo),
    )


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


def _merge_unsplash_content(content: object, photo: UnsplashPhoto) -> dict[str, object]:
    if isinstance(content, dict):
        merged: dict[str, object] = dict(content)
    else:
        merged = {}
        if isinstance(content, str):
            if _looks_like_path_string(content):
                merged["source_path"] = content
            else:
                merged["query"] = content
    merged.update(
        {
            "path": photo.cached_path,
            "url": photo.url,
            "download_url": photo.download_url,
            "photographer_name": photo.photographer_name,
            "photographer_url": photo.photographer_url,
        }
    )
    return merged


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


def _search_query_for_image_content(content: object) -> str | None:
    if isinstance(content, str):
        return _normalize_query_candidate(content)

    if not isinstance(content, dict):
        return None

    for key in ("query", "search_query", "image_query", "prompt"):
        value = content.get(key)
        if isinstance(value, str):
            candidate = _normalize_query_candidate(value, allow_pathlike=True)
            if candidate:
                return candidate

    for key in ("description", "alt_text", "text", "title", "caption"):
        value = content.get(key)
        if isinstance(value, str):
            candidate = _normalize_query_candidate(value, allow_pathlike=True)
            if candidate:
                return candidate

    for key in ("path", "local_path", "file_path", "asset_path", "uri"):
        value = content.get(key)
        if isinstance(value, str):
            candidate = _normalize_query_candidate(value)
            if candidate:
                return candidate

    return None


def _normalize_query_candidate(value: str, *, allow_pathlike: bool = False) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return None
    if not allow_pathlike and _looks_like_path_string(candidate):
        return None
    return candidate


def _looks_like_path_string(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    parsed = urlparse(stripped)
    if parsed.scheme in {"http", "https"}:
        return False
    if len(stripped) >= 2 and stripped[1] == ":" and stripped[0].isalpha():
        return True
    if "\\" in stripped or "/" in stripped:
        return True
    if Path(stripped).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tif", ".tiff"}:
        return True
    return False


def _unsplash_attribution(photo: UnsplashPhoto) -> str:
    return f"Photo by {photo.photographer_name} on Unsplash ({photo.photographer_url})"


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
