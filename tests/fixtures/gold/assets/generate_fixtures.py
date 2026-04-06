"""Generate gold asset fixture images for testing.

Run from repo root:
    .venv/Scripts/python.exe tests/fixtures/gold/assets/generate_fixtures.py

Creates synthetic test images in each category. These are intentionally simple
(colored rectangles with text labels) — they exist to give the asset resolver,
renderer, and QA stages real files to operate on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).parent

# Try to get a system font; fall back to Pillow's default bitmap font
try:
    FONT = ImageFont.truetype("arial.ttf", 24)
    FONT_SM = ImageFont.truetype("arial.ttf", 16)
except OSError:
    FONT = ImageFont.load_default()
    FONT_SM = FONT


def _make_image(
    path: Path,
    width: int,
    height: int,
    bg_color: str,
    label: str,
    text_color: str = "#FFFFFF",
    mode: str = "RGB",
) -> dict:
    """Create a labeled test image and return its manifest entry."""
    img = Image.new(mode, (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Draw label centered
    bbox = draw.textbbox((0, 0), label, font=FONT)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = (height - th) // 2
    draw.text((x, y), label, fill=text_color, font=FONT)

    # Draw size watermark bottom-right
    size_label = f"{width}x{height}"
    draw.text((width - 120, height - 30), size_label, fill=text_color, font=FONT_SM)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "file": str(path.relative_to(BASE)),
        "width": width,
        "height": height,
        "sha256": sha,
        "category": path.parent.name,
    }


def generate_photos(manifest: list) -> None:
    """10 business/consulting photos at 1920x1080."""
    names = [
        "office_meeting", "team_collaboration", "whiteboard_session",
        "executive_portrait", "conference_room", "laptop_workspace",
        "handshake_deal", "presentation_stage", "data_center", "city_skyline",
    ]
    colors = [
        "#2C3E50", "#1A5276", "#1E8449", "#7D3C98", "#B9770E",
        "#2E4053", "#154360", "#0B5345", "#6C3483", "#935116",
    ]
    for name, color in zip(names, colors):
        entry = _make_image(
            BASE / "photos" / f"photo_{name}.png",
            1920, 1080, color, name.replace("_", " ").title(),
        )
        manifest.append(entry)


def generate_logos(manifest: list) -> None:
    """10 logo/icon images at 512x512."""
    names = [
        "acme_corp", "globex", "initech", "umbrella_co", "wayne_ent",
        "stark_ind", "cyberdyne", "soylent", "oscorp", "lexcorp",
    ]
    colors = [
        "#E74C3C", "#3498DB", "#2ECC71", "#9B59B6", "#F39C12",
        "#1ABC9C", "#E67E22", "#34495E", "#D35400", "#8E44AD",
    ]
    for name, color in zip(names, colors):
        entry = _make_image(
            BASE / "logos" / f"logo_{name}.png",
            512, 512, color, name.replace("_", " ").upper(),
        )
        manifest.append(entry)


def generate_screenshots(manifest: list) -> None:
    """10 UI screenshots at 1440x900."""
    names = [
        "dashboard_main", "settings_page", "user_profile", "analytics_view",
        "login_screen", "data_table", "chart_builder", "notification_panel",
        "search_results", "admin_console",
    ]
    colors = [
        "#ECF0F1", "#F8F9FA", "#E8EAF6", "#FFF3E0", "#E0F2F1",
        "#F3E5F5", "#FFF8E1", "#E1F5FE", "#FBE9E7", "#F1F8E9",
    ]
    for name, color in zip(names, colors):
        entry = _make_image(
            BASE / "screenshots" / f"ss_{name}.png",
            1440, 900, color, name.replace("_", " ").title(),
            text_color="#333333",
        )
        manifest.append(entry)


def generate_backgrounds(manifest: list) -> None:
    """10 background images at 1920x1080."""
    names = [
        "gradient_blue", "gradient_dark", "subtle_grid", "minimal_white",
        "accent_stripe", "corner_frame", "split_panel", "dot_pattern",
        "diagonal_line", "solid_navy",
    ]
    colors = [
        "#1A237E", "#212121", "#37474F", "#FAFAFA", "#0D47A1",
        "#263238", "#455A64", "#546E7A", "#1B5E20", "#0D47A1",
    ]
    for name, color in zip(names, colors):
        entry = _make_image(
            BASE / "backgrounds" / f"bg_{name}.png",
            1920, 1080, color, name.replace("_", " ").title(),
        )
        manifest.append(entry)


def generate_charts(manifest: list) -> None:
    """10 chart PNG images at 1600x900."""
    names = [
        "revenue_bar", "margin_line", "market_pie", "pipeline_funnel",
        "kpi_sparklines", "waterfall_bridge", "scatter_cac_ltv",
        "stacked_segments", "donut_share", "combo_revenue_nrr",
    ]
    colors = [
        "#FFFFFF", "#FFFFFF", "#FFFFFF", "#FFFFFF", "#FFFFFF",
        "#FFFFFF", "#FFFFFF", "#FFFFFF", "#FFFFFF", "#FFFFFF",
    ]
    for name, color in zip(names, colors):
        entry = _make_image(
            BASE / "charts" / f"chart_{name}.png",
            1600, 900, color, f"[Chart: {name.replace('_', ' ').title()}]",
            text_color="#333333",
        )
        manifest.append(entry)


def generate_bad_assets(manifest: list) -> None:
    """Intentionally problematic assets for negative testing."""

    # 1. Wrong aspect ratio — very tall and narrow
    entry = _make_image(
        BASE / "bad" / "bad_wrong_aspect.png",
        200, 2000, "#FF0000", "WRONG\nASPECT",
    )
    entry["defect"] = "wrong_aspect_ratio"
    manifest.append(entry)

    # 2. Tiny image — 16x16
    entry = _make_image(
        BASE / "bad" / "bad_tiny.png",
        16, 16, "#FF6600", "T",
    )
    entry["defect"] = "too_small"
    manifest.append(entry)

    # 3. Missing file — record only, no actual file
    manifest.append({
        "file": "bad/bad_missing_file.png",
        "width": 800,
        "height": 600,
        "sha256": "0" * 64,
        "category": "bad",
        "defect": "file_does_not_exist",
    })

    # 4. Transparent PNG with very low alpha
    img = Image.new("RGBA", (800, 600), (255, 255, 255, 10))
    draw = ImageDraw.Draw(img)
    draw.text((200, 280), "NEARLY INVISIBLE", fill=(200, 200, 200, 20), font=FONT)
    path = BASE / "bad" / "bad_transparent.png"
    img.save(str(path))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest.append({
        "file": "bad/bad_transparent.png",
        "width": 800,
        "height": 600,
        "sha256": sha,
        "category": "bad",
        "defect": "nearly_invisible_transparency",
    })

    # 5. Huge dimensions but low content — 4000x4000 solid color
    entry = _make_image(
        BASE / "bad" / "bad_oversized.png",
        4000, 4000, "#000000", "OVERSIZED",
    )
    entry["defect"] = "oversized_dimensions"
    manifest.append(entry)

    # 6. Zero-byte file
    zero_path = BASE / "bad" / "bad_zero_bytes.png"
    zero_path.write_bytes(b"")
    manifest.append({
        "file": "bad/bad_zero_bytes.png",
        "width": 0,
        "height": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
        "category": "bad",
        "defect": "zero_byte_file",
    })


def main() -> None:
    manifest: list[dict] = []

    generate_photos(manifest)
    generate_logos(manifest)
    generate_screenshots(manifest)
    generate_backgrounds(manifest)
    generate_charts(manifest)
    generate_bad_assets(manifest)

    manifest_path = BASE / "asset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    good = [e for e in manifest if "defect" not in e]
    bad = [e for e in manifest if "defect" in e]
    print(f"Generated {len(good)} good assets + {len(bad)} bad assets")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
