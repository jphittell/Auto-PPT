from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

import pytest

from pptx_gen.assets.chart_renderer import render_chart_to_png
from pptx_gen.assets.resolver import ResolvedAssetBundle, resolve_assets
from pptx_gen.layout.schemas import ResolvedDeckLayout, StyleTokens
from pptx_gen.renderer.pptx_exporter import export_pptx


class _FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class _FakeResponse:
    def __init__(self, body: bytes, *, content_type: str = "application/json") -> None:
        self._body = body
        self.headers = _FakeHeaders(content_type)

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_resolve_assets_passes_local_images_to_cache(tmp_path: Path, style_tokens_payload: dict, tiny_png_bytes: bytes) -> None:
    source_image = tmp_path / "source.png"
    source_image.write_bytes(tiny_png_bytes)
    layout = ResolvedDeckLayout(
        deck_id="deck-assets",
        slides=[
            {
                "slide_id": "s1",
                "elements": [
                    {
                        "element_id": "s1:image",
                        "kind": "image",
                        "x": 0.5,
                        "y": 0.5,
                        "w": 1.0,
                        "h": 1.0,
                        "z": 0,
                        "data_ref": "block:b1",
                        "style_ref": "image",
                        "payload": {"content": {"path": str(source_image)}},
                    }
                ],
            }
        ],
    )

    bundle = resolve_assets(layout, cache_dir=tmp_path / "cache")

    assert isinstance(bundle, ResolvedAssetBundle)
    assert bundle.manifest.assets
    assert Path(bundle.manifest.assets[0].uri).exists()
    assert bundle.resolved_layout.slides[0].elements[0].payload["content"]["path"] == bundle.manifest.assets[0].uri


def test_resolve_assets_fails_on_missing_local_path(tmp_path: Path) -> None:
    layout = ResolvedDeckLayout(
        deck_id="deck-assets",
        slides=[
            {
                "slide_id": "s1",
                "elements": [
                    {
                        "element_id": "s1:image",
                        "kind": "image",
                        "x": 0.5,
                        "y": 0.5,
                        "w": 1.0,
                        "h": 1.0,
                        "z": 0,
                        "data_ref": "block:b1",
                        "style_ref": "image",
                        "payload": {"content": {"path": str(tmp_path / "missing.png")}},
                    }
                ],
            }
        ],
    )

    with pytest.raises(FileNotFoundError):
        resolve_assets(layout, cache_dir=tmp_path / "cache")


def test_resolve_assets_rejects_remote_image_url(tmp_path: Path) -> None:
    layout = ResolvedDeckLayout(
        deck_id="deck-assets",
        slides=[
            {
                "slide_id": "s1",
                "elements": [
                    {
                        "element_id": "s1:image",
                        "kind": "image",
                        "x": 0.5,
                        "y": 0.5,
                        "w": 1.0,
                        "h": 1.0,
                        "z": 0,
                        "data_ref": "block:b1",
                        "style_ref": "image",
                        "payload": {"content": {"path": "http://example.com/image.png"}},
                    }
                ],
            }
        ],
    )

    with pytest.raises(ValueError, match="remote asset URLs"):
        resolve_assets(layout, cache_dir=tmp_path / "cache")


def test_unsplash_asset_source_warns_and_returns_none_without_access_key(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from pptx_gen.assets.unsplash import UnsplashAssetSource

    source = UnsplashAssetSource(cache_dir=tmp_path / "cache", access_key="")

    with caplog.at_level("WARNING"):
        photo = source.fetch_photo("team meeting")

    assert photo is None
    assert "UNSPLASH_ACCESS_KEY is not set" in caplog.text


def test_resolve_assets_falls_back_to_unsplash_and_caches_image(
    tmp_path: Path,
    tiny_png_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pptx_gen.assets import unsplash as unsplash_module

    requests: list[str] = []

    def fake_urlopen(request: Request, timeout: float = 0):  # type: ignore[override]
        requests.append(request.full_url)
        if "search/photos" in request.full_url:
            assert request.get_header("Authorization") == "Client-ID test-unsplash-key"
            return _FakeResponse(
                json.dumps(
                    {
                        "results": [
                            {
                                "id": "photo-123",
                                "links": {
                                    "html": "https://unsplash.com/photos/photo-123",
                                    "download_location": "https://api.unsplash.com/photos/photo-123/download",
                                },
                                "user": {
                                    "name": "Jane Doe",
                                    "links": {"html": "https://unsplash.com/@janedoe"},
                                },
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        if request.full_url == "https://api.unsplash.com/photos/photo-123/download":
            assert request.get_header("Authorization") == "Client-ID test-unsplash-key"
            return _FakeResponse(json.dumps({"url": "https://images.unsplash.com/photo-123.png"}).encode("utf-8"))
        if request.full_url == "https://images.unsplash.com/photo-123.png":
            return _FakeResponse(tiny_png_bytes, content_type="image/png")
        raise AssertionError(f"unexpected URL: {request.full_url}")

    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "test-unsplash-key")
    monkeypatch.setattr(unsplash_module, "urlopen", fake_urlopen)

    layout = ResolvedDeckLayout(
        deck_id="deck-assets",
        slides=[
            {
                "slide_id": "s1",
                "elements": [
                    {
                        "element_id": "s1:image",
                        "kind": "image",
                        "x": 0.5,
                        "y": 0.5,
                        "w": 1.0,
                        "h": 1.0,
                        "z": 0,
                        "data_ref": "block:b1",
                        "style_ref": "image",
                        "payload": {"content": "team meeting"},
                    }
                ],
            }
        ],
    )

    bundle = resolve_assets(layout, cache_dir=tmp_path / "cache")

    assert requests == [
        "https://api.unsplash.com/search/photos?query=team+meeting&page=1&per_page=10&orientation=landscape",
        "https://api.unsplash.com/photos/photo-123/download",
        "https://images.unsplash.com/photo-123.png",
    ]
    assert isinstance(bundle, ResolvedAssetBundle)
    assert len(bundle.manifest.assets) == 1
    asset = bundle.manifest.assets[0]
    content = bundle.resolved_layout.slides[0].elements[0].payload["content"]
    assert Path(asset.uri).exists()
    assert content["path"] == asset.uri
    assert content["query"] == "team meeting"
    assert content["photographer_name"] == "Jane Doe"
    assert content["photographer_url"] == "https://unsplash.com/@janedoe?utm_source=auto-ppt&utm_medium=referral"
    assert content["download_url"] == "https://images.unsplash.com/photo-123.png"
    assert asset.source_uri == "https://unsplash.com/photos/photo-123?utm_source=auto-ppt&utm_medium=referral"
    assert asset.license == "Unsplash License"
    assert asset.attribution == "Photo by Jane Doe on Unsplash (https://unsplash.com/@janedoe?utm_source=auto-ppt&utm_medium=referral)"


def test_render_chart_to_png_and_resolve_for_renderer(tmp_path: Path, style_tokens_payload: dict) -> None:
    chart_path = render_chart_to_png(
        {
            "chart_type": "bar",
            "data": [{"label": "Q1", "value": 10}, {"label": "Q2", "value": 14}],
            "x_label": "Quarter",
            "y_label": "Value",
        },
        tmp_path / "chart.png",
    )
    assert chart_path.exists()
    assert chart_path.stat().st_size > 0

    layout = ResolvedDeckLayout(
        deck_id="deck-chart",
        slides=[
            {
                "slide_id": "s1",
                "elements": [
                    {
                        "element_id": "s1:chart",
                        "kind": "chart",
                        "x": 0.5,
                        "y": 0.5,
                        "w": 4.0,
                        "h": 2.5,
                        "z": 0,
                        "data_ref": "block:b1",
                        "style_ref": "chart",
                        "payload": {
                            "content": {
                                "chart_type": "line",
                                "data": [{"label": "Q1", "value": 10}, {"label": "Q2", "value": 12}],
                                "x_label": "Quarter",
                                "y_label": "Value",
                            }
                        },
                    }
                ],
            }
        ],
    )

    bundle = resolve_assets(layout, cache_dir=tmp_path / "cache")
    exported = export_pptx(layout=bundle.resolved_layout, style_tokens=StyleTokens(**style_tokens_payload), output_path=tmp_path / "chart-deck.pptx")
    assert exported.exists()
    assert bundle.manifest.assets[0].uri.endswith(".png")
