"""PDF export using reportlab — renders each slide as a landscape page."""

from __future__ import annotations

import io
import textwrap
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas


PAGE_W, PAGE_H = landscape(A4)
MARGIN = 40
CONTENT_W = PAGE_W - 2 * MARGIN

# Brand colours
ORACLE_RED = colors.HexColor("#C74634")
DARK = colors.HexColor("#1c1917")
MUTED = colors.HexColor("#78716c")
CARD_BG = colors.HexColor("#fafaf9")
CARD_BORDER = colors.HexColor("#e7e5e4")


def _draw_rounded_rect(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    r: float = 6,
    fill_color: colors.Color = CARD_BG,
    stroke_color: colors.Color = CARD_BORDER,
) -> None:
    c.saveState()
    c.setFillColor(fill_color)
    c.setStrokeColor(stroke_color)
    c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, r, fill=1, stroke=1)
    c.restoreState()


def _draw_text(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    font: str = "Helvetica",
    size: float = 10,
    color: colors.Color = DARK,
    max_width: float | None = None,
    bottom_limit: float | None = None,
) -> float:
    """Draw text, returning the y position after the last line.

    bottom_limit: if set, stop drawing lines that would fall below this y value.
    """
    from reportlab.pdfbase import pdfmetrics

    c.saveState()
    c.setFont(font, size)
    c.setFillColor(color)
    if max_width:
        # Use actual average character width instead of a rough estimate
        avg_char_w = pdfmetrics.stringWidth("abcdefghijklmnopqrstuvwxyz", font, size) / 26
        wrap_at = max(10, int(max_width / avg_char_w))
        lines = textwrap.wrap(text, width=wrap_at)
    else:
        lines = [text]
    line_height = size * 1.4
    cur_y = y
    for line in lines:
        if bottom_limit is not None and cur_y < bottom_limit:
            break
        c.drawString(x, cur_y, line)
        cur_y -= line_height
    c.restoreState()
    return cur_y


def _extract_cards(block: dict[str, Any]) -> list[dict[str, str]]:
    data = block.get("data")
    if isinstance(data, dict):
        cards = data.get("cards")
        if isinstance(cards, list):
            return [
                {
                    "title": str(card.get("title", "")),
                    "text": str(card.get("text", "")),
                }
                for card in cards
                if isinstance(card, dict)
            ]
    return []


def _extract_bullets(block: dict[str, Any]) -> list[str]:
    data = block.get("data")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [str(item) for item in items if item]
    content = block.get("content", "")
    if isinstance(content, str) and content.strip():
        return [line.lstrip("•*- ").strip() for line in content.splitlines() if line.strip()]
    return []


def _render_title_slide(c: canvas.Canvas, slide: dict[str, Any], deck_title: str) -> None:
    # Background accent bar
    c.saveState()
    c.setFillColor(ORACLE_RED)
    c.rect(0, PAGE_H - 6, PAGE_W, 6, fill=1, stroke=0)
    c.restoreState()

    y = PAGE_H - 80
    _draw_text(c, deck_title, MARGIN, y, "Helvetica", 11, MUTED)
    y -= 40
    _draw_text(c, slide.get("title", ""), MARGIN, y, "Helvetica-Bold", 28, DARK, CONTENT_W)
    y -= 50
    # Speaker notes as subtitle
    notes = slide.get("speaker_notes", "")
    if notes:
        _draw_text(c, notes, MARGIN, y, "Helvetica", 12, MUTED, CONTENT_W)


def _render_content_slide(c: canvas.Canvas, slide: dict[str, Any]) -> None:
    y = PAGE_H - 50

    # Template label
    template = slide.get("template_id", "")
    _draw_text(c, template.upper(), MARGIN, y, "Helvetica", 8, MUTED)
    y -= 20

    # Title
    y = _draw_text(c, slide.get("title", ""), MARGIN, y, "Helvetica-Bold", 20, DARK, CONTENT_W)
    y -= 15

    blocks = slide.get("blocks", [])
    for block in blocks:
        kind = block.get("kind", "")

        # Cards
        cards = _extract_cards(block)
        if cards:
            cols = min(len(cards), 3)
            card_gap = 12
            card_w = (CONTENT_W - card_gap * (cols - 1)) / cols
            card_h = 90
            row_cards = [cards[i : i + cols] for i in range(0, len(cards), cols)]
            for row in row_cards:
                card_x = MARGIN
                for card in row:
                    card_bottom = y - card_h
                    _draw_rounded_rect(c, card_x, card_bottom, card_w, card_h)
                    title_y = _draw_text(
                        c, card.get("title", ""), card_x + 10, y - 18,
                        "Helvetica-Bold", 10, DARK, card_w - 20,
                        bottom_limit=card_bottom + 6,
                    )
                    _draw_text(
                        c, card.get("text", ""), card_x + 10, title_y - 4,
                        "Helvetica", 9, MUTED, card_w - 20,
                        bottom_limit=card_bottom + 6,
                    )
                    card_x += card_w + card_gap
                y -= card_h + 10
            continue

        # Bullets — use returned cur_y so wrapped lines don't overlap the next bullet
        bullets = _extract_bullets(block)
        if bullets:
            for bullet in bullets:
                y = _draw_text(c, f"•  {bullet}", MARGIN + 10, y, "Helvetica", 10, DARK, CONTENT_W - 20)
                y -= 4  # small gap between bullets
            y -= 6
            continue

        # Plain text
        content = block.get("content", "")
        if isinstance(content, str) and content.strip():
            y = _draw_text(c, content, MARGIN, y, "Helvetica", 10, DARK, CONTENT_W)
            y -= 10

    # Slide number
    c.saveState()
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_W - MARGIN, 20, f"Slide {slide.get('index', '')}")
    c.restoreState()


def export_deck_to_pdf(deck: dict[str, Any]) -> bytes:
    """Render the full deck as a multi-page landscape PDF and return bytes."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle(deck.get("title", "Presentation"))
    c.setAuthor("Auto-PPT")

    slides = deck.get("slides", [])
    if not slides:
        c.drawString(72, PAGE_H / 2, "No slides to render.")
        c.showPage()
        c.save()
        return buf.getvalue()

    for slide in slides:
        purpose = slide.get("purpose", "content")
        if purpose == "title":
            _render_title_slide(c, slide, deck.get("title", ""))
        else:
            _render_content_slide(c, slide)
        c.showPage()

    c.save()
    return buf.getvalue()
