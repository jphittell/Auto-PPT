"""Named template registry and alias normalization."""

from __future__ import annotations

from typing import Final


TEMPLATE_CATALOG: Final[dict[str, str]] = {
    "title.hero": "Hero title slide with subtitle metadata.",
    "agenda.list": "Single-column agenda bullets.",
    "section.header": "Section divider slide.",
    "content.1col": "Single-column content layout.",
    "content.2col.text_image": "Two-column layout with text and image.",
    "content.3col.cards": "Three-column comparison or card layout.",
    "kpi.3up": "Three-up KPI card layout.",
    "chart.full": "Full-width chart layout.",
    "table.full": "Full-width table layout.",
    "appendix.details": "Dense appendix/details layout.",
}

TEMPLATE_ALIASES: Final[dict[str, str]] = {
    "2col.text_image": "content.2col.text_image",
    "3col.cards": "content.3col.cards",
    "title": "title.hero",
}
