"""Deterministic QA validators and structured reports."""

from __future__ import annotations

import math
from enum import Enum
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from pptx_gen.layout.schemas import ResolvedDeckLayout, ResolvedElement, ResolvedElementKind, StyleTokens
from pptx_gen.layout.templates import SLIDE_HEIGHT_IN, SLIDE_WIDTH_IN
from pptx_gen.renderer.slide_ops import extract_local_asset_path, extract_text_lines, style_profile


class QAStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class QAItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str = Field(min_length=1)
    check: str = Field(min_length=1)
    status: QAStatus
    message: str = Field(min_length=1)
    slide_id: str | None = None
    element_id: str | None = None
    metric: float | None = None


class QADimensionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    status: QAStatus
    passed_checks: int = Field(ge=0, default=0)
    warnings: int = Field(ge=0, default=0)
    failures: int = Field(ge=0, default=0)


class QAReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1)
    passed: bool
    items: list[QAItem] = Field(default_factory=list)
    executability: QADimensionReport
    layout_quality: QADimensionReport
    text_quality: QADimensionReport
    image_quality: QADimensionReport
    color_quality: QADimensionReport
    design_summary: str = Field(min_length=1)


def validate_layout(layout: ResolvedDeckLayout, *, style_tokens: StyleTokens) -> QAReport:
    executability_items = [
        QAItem(
            dimension="executability",
            check="layout.resolved",
            status=QAStatus.PASS,
            message="resolved layout is available for validation",
        )
    ]
    layout_items: list[QAItem] = []
    text_items: list[QAItem] = []
    image_items: list[QAItem] = []
    color_items: list[QAItem] = []

    for slide in layout.slides:
        text_word_count = 0
        for element in slide.elements:
            layout_items.extend(_bounds_items(slide.slide_id, element))
            if element.kind in {ResolvedElementKind.TEXTBOX, ResolvedElementKind.SHAPE}:
                words = _word_count(extract_text_lines((element.payload or {}).get("content")))
                text_word_count += words
                overflow_item = _overflow_item(slide.slide_id, element, style_tokens)
                if overflow_item is not None:
                    text_items.append(overflow_item)
                bullet_item = _bullet_density_item(slide.slide_id, element)
                if bullet_item is not None:
                    text_items.append(bullet_item)
            if element.kind in {ResolvedElementKind.IMAGE, ResolvedElementKind.CHART}:
                image_items.extend(_image_items(slide.slide_id, element))
            if element.kind is ResolvedElementKind.CHART:
                image_items.extend(_chart_data_size_items(slide.slide_id, element))
            if element.kind in {ResolvedElementKind.TEXTBOX, ResolvedElementKind.SHAPE}:
                color_items.extend(_contrast_items(slide.slide_id, element, style_tokens))

        layout_items.extend(_overlap_items(slide.slide_id, slide.elements))
        if text_word_count > 80:
            text_items.append(
                QAItem(
                    dimension="text",
                    check="text.density",
                    status=QAStatus.WARN,
                    message=f"slide content is dense at {text_word_count} words",
                    slide_id=slide.slide_id,
                    metric=float(text_word_count),
                )
            )

    items = executability_items + layout_items + text_items + image_items + color_items
    return _build_report("layout", items)


def validate_export(
    output_path: str | Path,
    *,
    layout: ResolvedDeckLayout,
    style_tokens: StyleTokens,
    render_error: Exception | None = None,
) -> QAReport:
    output_path = Path(output_path)
    items: list[QAItem] = []
    if render_error is not None:
        items.append(
            QAItem(
                dimension="executability",
                check="render.export",
                status=QAStatus.FAIL,
                message=f"render failed: {render_error}",
            )
        )
        return _build_report("export", items)

    if not output_path.exists():
        items.append(
            QAItem(
                dimension="executability",
                check="render.artifact_exists",
                status=QAStatus.FAIL,
                message=f"rendered artifact missing: {output_path}",
            )
        )
        return _build_report("export", items)

    items.append(
        QAItem(
            dimension="executability",
            check="render.artifact_exists",
            status=QAStatus.PASS,
            message=f"rendered artifact written to {output_path}",
            metric=float(output_path.stat().st_size),
        )
    )
    layout_report = validate_layout(layout, style_tokens=style_tokens)
    return _build_report("export", items + layout_report.items)


def _build_report(stage: str, items: list[QAItem]) -> QAReport:
    grouped = {
        "executability": _dimension_report("executability", [item for item in items if item.dimension == "executability"]),
        "layout": _dimension_report("layout", [item for item in items if item.dimension == "layout"]),
        "text": _dimension_report("text", [item for item in items if item.dimension == "text"]),
        "image": _dimension_report("image", [item for item in items if item.dimension == "image"]),
        "color": _dimension_report("color", [item for item in items if item.dimension == "color"]),
    }
    passed = all(report.status is not QAStatus.FAIL for report in grouped.values())
    summary = ", ".join(f"{name}={report.status.value}" for name, report in grouped.items())
    return QAReport(
        stage=stage,
        passed=passed,
        items=items,
        executability=grouped["executability"],
        layout_quality=grouped["layout"],
        text_quality=grouped["text"],
        image_quality=grouped["image"],
        color_quality=grouped["color"],
        design_summary=summary,
    )


def _dimension_report(name: str, items: list[QAItem]) -> QADimensionReport:
    failures = sum(1 for item in items if item.status is QAStatus.FAIL)
    warnings = sum(1 for item in items if item.status is QAStatus.WARN)
    passed_checks = sum(1 for item in items if item.status is QAStatus.PASS)
    status = QAStatus.FAIL if failures else QAStatus.WARN if warnings else QAStatus.PASS
    return QADimensionReport(
        name=name,
        status=status,
        passed_checks=passed_checks,
        warnings=warnings,
        failures=failures,
    )


def _bounds_items(slide_id: str, element: ResolvedElement) -> list[QAItem]:
    if element.x + element.w <= SLIDE_WIDTH_IN and element.y + element.h <= SLIDE_HEIGHT_IN:
        return []
    return [
        QAItem(
            dimension="layout",
            check="layout.bounds",
            status=QAStatus.FAIL,
            message="element exceeds slide bounds",
            slide_id=slide_id,
            element_id=element.element_id,
        )
    ]


def _overlap_items(slide_id: str, elements: list[ResolvedElement]) -> list[QAItem]:
    items: list[QAItem] = []
    for index, left in enumerate(elements):
        for right in elements[index + 1 :]:
            overlap = _intersection_area(left, right)
            if overlap == 0:
                continue
            smaller_area = min(left.w * left.h, right.w * right.h)
            ratio = overlap / smaller_area if smaller_area else 0
            if ratio > 0.01:
                items.append(
                    QAItem(
                        dimension="layout",
                        check="layout.overlap",
                        status=QAStatus.FAIL,
                        message=f"{left.element_id} overlaps {right.element_id}",
                        slide_id=slide_id,
                        element_id=left.element_id,
                        metric=ratio,
                    )
                )
    return items


def _overflow_item(slide_id: str, element: ResolvedElement, style_tokens: StyleTokens) -> QAItem | None:
    lines = extract_text_lines((element.payload or {}).get("content"))
    if not lines:
        return None
    text = "\n".join(lines)
    profile = style_profile(style_tokens, element.style_ref or "body", element.kind)
    font_size_pt = float(profile["font_size_pt"])
    estimated_chars_per_line = max(8, int(element.w * (15 if font_size_pt <= 12 else 11 if font_size_pt <= 18 else 8)))
    estimated_lines = max(1, math.ceil(len(text) / estimated_chars_per_line))
    line_height_in = (font_size_pt / 72.0) * 1.2
    capacity = max(1, int(element.h / line_height_in))
    if estimated_lines > capacity:
        return QAItem(
            dimension="text",
            check="text.overflow",
            status=QAStatus.FAIL,
            message=f"text likely overflows box ({estimated_lines} lines > {capacity})",
            slide_id=slide_id,
            element_id=element.element_id,
            metric=float(estimated_lines - capacity),
        )
    return None


def _image_items(slide_id: str, element: ResolvedElement) -> list[QAItem]:
    payload = element.payload or {}
    content = payload.get("content")
    path = extract_local_asset_path(content)
    if path is None:
        return [
            QAItem(
                dimension="image",
                check="image.local_asset",
                status=QAStatus.FAIL,
                message="image/chart element is missing a local asset path",
                slide_id=slide_id,
                element_id=element.element_id,
            )
        ]
    items = [
        QAItem(
            dimension="image",
            check="image.local_asset",
            status=QAStatus.PASS if path.exists() else QAStatus.FAIL,
            message="local image asset exists" if path.exists() else f"missing local asset: {path}",
            slide_id=slide_id,
            element_id=element.element_id,
        )
    ]
    if isinstance(content, dict):
        width_px = content.get("width_px")
        height_px = content.get("height_px")
        if isinstance(width_px, (int, float)) and isinstance(height_px, (int, float)) and width_px > 0 and height_px > 0:
            source_ratio = float(width_px) / float(height_px)
            slot_ratio = element.w / element.h
            if abs(source_ratio - slot_ratio) > 0.35:
                items.append(
                    QAItem(
                        dimension="image",
                        check="image.aspect_ratio",
                        status=QAStatus.WARN,
                        message="image aspect ratio differs noticeably from slot ratio",
                        slide_id=slide_id,
                        element_id=element.element_id,
                        metric=abs(source_ratio - slot_ratio),
                    )
                )
    return items


def _contrast_items(slide_id: str, element: ResolvedElement, style_tokens: StyleTokens) -> list[QAItem]:
    if not extract_text_lines((element.payload or {}).get("content")):
        return []
    profile = style_profile(style_tokens, element.style_ref or "body", element.kind)
    fg = profile["text_color"]
    bg = profile["fill_color"] if element.kind is ResolvedElementKind.SHAPE else style_tokens.colors.bg
    ratio = _contrast_ratio(fg, bg)
    if ratio < 3.0:
        status = QAStatus.FAIL
    elif ratio < 4.5:
        status = QAStatus.WARN
    else:
        return []
    return [
        QAItem(
            dimension="color",
            check="color.contrast",
            status=status,
            message=f"contrast ratio is {ratio:.2f}:1",
            slide_id=slide_id,
            element_id=element.element_id,
            metric=ratio,
        )
    ]


def _bullet_density_item(slide_id: str, element: ResolvedElement) -> QAItem | None:
    lines = extract_text_lines((element.payload or {}).get("content"))
    bullet_count = sum(1 for line in lines if str(line).strip())
    if bullet_count > 7:
        return QAItem(
            dimension="text",
            check="text.bullet_density",
            status=QAStatus.WARN,
            message=f"element has {bullet_count} bullets; consider trimming to ≤7",
            slide_id=slide_id,
            element_id=element.element_id,
            metric=float(bullet_count),
        )
    return None


def _chart_data_size_items(slide_id: str, element: ResolvedElement) -> list[QAItem]:
    payload = element.payload or {}
    content = payload.get("content")
    data = content if isinstance(content, dict) else payload
    items: list[QAItem] = []
    series = data.get("series") if isinstance(data, dict) else None
    categories = data.get("categories") if isinstance(data, dict) else None
    if isinstance(series, list) and len(series) > 8:
        items.append(
            QAItem(
                dimension="image",
                check="chart.series_count",
                status=QAStatus.WARN,
                message=f"chart has {len(series)} series; >8 reduces legibility",
                slide_id=slide_id,
                element_id=element.element_id,
                metric=float(len(series)),
            )
        )
    if isinstance(categories, list) and len(categories) > 20:
        items.append(
            QAItem(
                dimension="image",
                check="chart.category_count",
                status=QAStatus.WARN,
                message=f"chart has {len(categories)} categories; >20 reduces legibility",
                slide_id=slide_id,
                element_id=element.element_id,
                metric=float(len(categories)),
            )
        )
    return items


def _intersection_area(left: ResolvedElement, right: ResolvedElement) -> float:
    overlap_w = max(0.0, min(left.x + left.w, right.x + right.w) - max(left.x, right.x))
    overlap_h = max(0.0, min(left.y + left.h, right.y + right.h) - max(left.y, right.y))
    return overlap_w * overlap_h


def _word_count(lines: Iterable[str]) -> int:
    return sum(len(str(line).split()) for line in lines)


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter = max(_luminance(foreground), _luminance(background))
    darker = min(_luminance(foreground), _luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(color_hex: str) -> float:
    values = tuple(int(color_hex.lstrip("#")[index : index + 2], 16) / 255 for index in (0, 2, 4))
    normalized = []
    for value in values:
        if value <= 0.03928:
            normalized.append(value / 12.92)
        else:
            normalized.append(((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * normalized[0] + 0.7152 * normalized[1] + 0.0722 * normalized[2]
