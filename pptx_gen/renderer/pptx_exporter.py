"""Deterministic PPTX exporter built on renderer slide operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.util import Inches

from pptx_gen.layout.schemas import PageSize, ResolvedDeckLayout, ResolvedElement, ResolvedElementKind, StyleTokens
from pptx_gen.renderer.slide_ops import (
    add_bullets,
    add_chart_image,
    add_image,
    add_shape,
    add_table,
    add_text,
    add_title,
    extract_local_asset_path,
    extract_table_content,
    extract_text_lines,
    set_background_color,
)


SLIDE_SIZES = {
    PageSize.WIDESCREEN: (13.333, 7.5),
    PageSize.STANDARD: (10.0, 7.5),
}


def export_pptx(
    *,
    layout: ResolvedDeckLayout,
    style_tokens: StyleTokens,
    output_path: str | Path,
    template_path: str | Path | None = None,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    presentation = Presentation(str(template_path)) if template_path else Presentation()
    slide_width, slide_height = SLIDE_SIZES[layout.page_size]
    presentation.slide_width = Inches(slide_width)
    presentation.slide_height = Inches(slide_height)

    blank_layout = presentation.slide_layouts[6]
    for slide_layout in layout.slides:
        slide = presentation.slides.add_slide(blank_layout)
        set_background_color(slide, style_tokens.colors.bg)
        for element in sorted(slide_layout.elements, key=lambda item: item.z):
            _render_element(slide, element, style_tokens)

    presentation.save(str(output_path))
    return output_path


def _render_element(slide: Any, element: ResolvedElement, style_tokens: StyleTokens) -> None:
    payload = element.payload or {}
    content = payload.get("content")

    if element.kind is ResolvedElementKind.TEXTBOX:
        lines = extract_text_lines(content)
        if payload.get("block_kind") == "bullets" or (isinstance(content, dict) and isinstance(content.get("items"), list)):
            add_bullets(
                slide,
                lines,
                x=element.x,
                y=element.y,
                w=element.w,
                h=element.h,
                style_tokens=style_tokens,
                style_ref=element.style_ref,
            )
        else:
            text = "\n".join(lines)
            renderer = add_title if element.style_ref == "headline" else add_text
            renderer(
                slide,
                text,
                x=element.x,
                y=element.y,
                w=element.w,
                h=element.h,
                style_tokens=style_tokens,
                style_ref=element.style_ref,
            )
        return

    if element.kind is ResolvedElementKind.IMAGE:
        image_path = extract_local_asset_path(content)
        if image_path is None:
            raise FileNotFoundError(f"image element {element.element_id} is missing a local asset path")
        add_image(slide, image_path, x=element.x, y=element.y, w=element.w, h=element.h)
        return

    if element.kind is ResolvedElementKind.CHART:
        image_path = extract_local_asset_path(content)
        if image_path is None:
            raise FileNotFoundError(f"chart element {element.element_id} is missing a local asset path")
        add_chart_image(slide, image_path, x=element.x, y=element.y, w=element.w, h=element.h)
        return

    if element.kind is ResolvedElementKind.TABLE:
        table_content = extract_table_content(content)
        if table_content is None:
            raise ValueError(f"table element {element.element_id} is missing columns/rows content")
        columns, rows = table_content
        add_table(
            slide,
            columns,
            rows,
            x=element.x,
            y=element.y,
            w=element.w,
            h=element.h,
            style_tokens=style_tokens,
            style_ref=element.style_ref,
        )
        return

    if element.kind is ResolvedElementKind.SHAPE:
        text = "\n".join(extract_text_lines(content)) or None
        add_shape(
            slide,
            x=element.x,
            y=element.y,
            w=element.w,
            h=element.h,
            style_tokens=style_tokens,
            style_ref=element.style_ref,
            text=text,
        )
        return

    raise ValueError(f"unsupported resolved element kind: {element.kind}")
