from __future__ import annotations

from pathlib import Path

import pytest

from pptx_gen.assets.chart_renderer import render_chart_to_png
from pptx_gen.assets.resolver import ResolvedAssetBundle, resolve_assets
from pptx_gen.layout.schemas import ResolvedDeckLayout, StyleTokens
from pptx_gen.renderer.pptx_exporter import export_pptx


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
