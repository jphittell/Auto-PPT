"""Deterministic slide template registry and alias normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from pptx_gen.layout.schemas import ResolvedElementKind


SLIDE_WIDTH_IN: Final[float] = 13.333
SLIDE_HEIGHT_IN: Final[float] = 7.5
NORMAL_MARGIN_IN: Final[float] = 0.75
THIN_MARGIN_IN: Final[float] = 0.50
COLUMN_GUTTER_IN: Final[float] = 0.20
ROW_GUTTER_IN: Final[float] = 0.25
CONTENT_WIDTH_NORMAL_IN: Final[float] = 11.833
CONTENT_HEIGHT_NORMAL_IN: Final[float] = 6.0
CONTENT_WIDTH_THIN_IN: Final[float] = 12.333
TWO_COL_WIDTH_IN: Final[float] = (CONTENT_WIDTH_NORMAL_IN - COLUMN_GUTTER_IN) / 2
THREE_COL_WIDTH_IN: Final[float] = (CONTENT_WIDTH_NORMAL_IN - (2 * COLUMN_GUTTER_IN)) / 3


BindingSource = Literal["headline", "block", "block_field", "block_items", "static"]


@dataclass(frozen=True, slots=True)
class SlotBinding:
    source: BindingSource
    block_index: int | None = None
    field: str | None = None
    item_index: int | None = None


@dataclass(frozen=True, slots=True)
class TemplateSlot:
    slot_id: str
    kind: ResolvedElementKind
    x: float
    y: float
    w: float
    h: float
    z: int
    style_ref: str
    binding: SlotBinding


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    template_key: str
    description: str
    allowed_purposes: tuple[str, ...]
    strict_default: bool
    slots: tuple[TemplateSlot, ...]


def _slot(
    slot_id: str,
    kind: ResolvedElementKind,
    x: float,
    y: float,
    w: float,
    h: float,
    z: int,
    style_ref: str,
    binding: SlotBinding,
) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        kind=kind,
        x=x,
        y=y,
        w=w,
        h=h,
        z=z,
        style_ref=style_ref,
        binding=binding,
    )


TEMPLATE_REGISTRY: Final[dict[str, TemplateDefinition]] = {
    "title.hero": TemplateDefinition(
        template_key="title.hero",
        description="Hero title slide with supporting metadata and optional logo.",
        allowed_purposes=("title",),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                1.50,
                2.50,
                10.33,
                1.25,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "subtitle",
                ResolvedElementKind.TEXTBOX,
                2.00,
                4.00,
                9.33,
                0.75,
                0,
                "subtitle",
                SlotBinding(source="block_field", block_index=0, field="subtitle"),
            ),
            _slot(
                "presenter",
                ResolvedElementKind.TEXTBOX,
                0.75,
                6.50,
                5.00,
                0.40,
                0,
                "meta",
                SlotBinding(source="block_field", block_index=0, field="presenter"),
            ),
            _slot(
                "date",
                ResolvedElementKind.TEXTBOX,
                0.75,
                6.90,
                5.00,
                0.40,
                0,
                "meta",
                SlotBinding(source="block_field", block_index=0, field="date"),
            ),
            _slot(
                "logo",
                ResolvedElementKind.IMAGE,
                11.50,
                6.50,
                1.08,
                0.50,
                1,
                "logo",
                SlotBinding(source="block_field", block_index=0, field="logo"),
            ),
        ),
    ),
    "agenda.list": TemplateDefinition(
        template_key="agenda.list",
        description="Agenda layout with a headline, list body, and footer progress bar.",
        allowed_purposes=("agenda",),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.75,
                CONTENT_WIDTH_NORMAL_IN,
                0.75,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "agenda_body",
                ResolvedElementKind.TEXTBOX,
                1.50,
                1.80,
                10.33,
                4.80,
                0,
                "body",
                SlotBinding(source="block", block_index=0),
            ),
            _slot(
                "progress_bar",
                ResolvedElementKind.SHAPE,
                0.00,
                7.35,
                SLIDE_WIDTH_IN,
                0.15,
                1,
                "accent_bar",
                SlotBinding(source="static"),
            ),
        ),
    ),
    "section.header": TemplateDefinition(
        template_key="section.header",
        description="Section divider with large headline and supporting tagline.",
        allowed_purposes=("section",),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                1.00,
                3.00,
                11.33,
                1.25,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "tagline",
                ResolvedElementKind.TEXTBOX,
                1.00,
                4.30,
                11.33,
                0.60,
                0,
                "subtitle",
                SlotBinding(source="block_field", block_index=0, field="tagline"),
            ),
            _slot(
                "footer_info",
                ResolvedElementKind.TEXTBOX,
                0.75,
                6.80,
                CONTENT_WIDTH_NORMAL_IN,
                0.30,
                0,
                "footer",
                SlotBinding(source="block_field", block_index=0, field="footer_info"),
            ),
        ),
    ),
    "executive.overview": TemplateDefinition(
        template_key="executive.overview",
        description="Executive overview slide with summary, insight, capability cards, and footer metrics.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.70,
                CONTENT_WIDTH_NORMAL_IN,
                0.70,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "summary",
                ResolvedElementKind.TEXTBOX,
                0.75,
                1.70,
                4.15,
                1.75,
                0,
                "body",
                SlotBinding(source="block", block_index=0),
            ),
            _slot(
                "insight",
                ResolvedElementKind.SHAPE,
                0.75,
                3.70,
                4.15,
                1.25,
                1,
                "takeaway",
                SlotBinding(source="block", block_index=1),
            ),
            _slot("card_1", ResolvedElementKind.SHAPE, 5.30, 1.70, 3.40, 1.55, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=0)),
            _slot("card_2", ResolvedElementKind.SHAPE, 8.98, 1.70, 3.40, 1.55, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=1)),
            _slot("card_3", ResolvedElementKind.SHAPE, 5.30, 3.55, 3.40, 1.55, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=2)),
            _slot("card_4", ResolvedElementKind.SHAPE, 8.98, 3.55, 3.40, 1.55, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=3)),
            _slot("card_5", ResolvedElementKind.SHAPE, 5.30, 5.40, 3.40, 1.25, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=4)),
            _slot("card_6", ResolvedElementKind.SHAPE, 8.98, 5.40, 3.40, 1.25, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=5)),
            _slot(
                "footer_metrics",
                ResolvedElementKind.TEXTBOX,
                0.75,
                6.78,
                CONTENT_WIDTH_NORMAL_IN,
                0.32,
                0,
                "footer",
                SlotBinding(source="block_field", block_index=3, field="text"),
            ),
        ),
    ),
    "architecture.grid": TemplateDefinition(
        template_key="architecture.grid",
        description="Architecture grid slide with summary, six component cards, and footer note.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.70,
                CONTENT_WIDTH_NORMAL_IN,
                0.70,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "summary",
                ResolvedElementKind.TEXTBOX,
                0.75,
                1.55,
                CONTENT_WIDTH_NORMAL_IN,
                0.75,
                0,
                "body",
                SlotBinding(source="block", block_index=0),
            ),
            _slot("card_1", ResolvedElementKind.SHAPE, 0.75, 2.55, 3.82, 1.45, 0, "card", SlotBinding(source="block_items", block_index=1, field="cards", item_index=0)),
            _slot("card_2", ResolvedElementKind.SHAPE, 4.76, 2.55, 3.82, 1.45, 0, "card", SlotBinding(source="block_items", block_index=1, field="cards", item_index=1)),
            _slot("card_3", ResolvedElementKind.SHAPE, 8.77, 2.55, 3.82, 1.45, 0, "card", SlotBinding(source="block_items", block_index=1, field="cards", item_index=2)),
            _slot("card_4", ResolvedElementKind.SHAPE, 0.75, 4.25, 3.82, 1.45, 0, "card", SlotBinding(source="block_items", block_index=1, field="cards", item_index=3)),
            _slot("card_5", ResolvedElementKind.SHAPE, 4.76, 4.25, 3.82, 1.45, 0, "card", SlotBinding(source="block_items", block_index=1, field="cards", item_index=4)),
            _slot("card_6", ResolvedElementKind.SHAPE, 8.77, 4.25, 3.82, 1.45, 0, "card", SlotBinding(source="block_items", block_index=1, field="cards", item_index=5)),
            _slot(
                "footer_note",
                ResolvedElementKind.TEXTBOX,
                0.75,
                6.45,
                CONTENT_WIDTH_NORMAL_IN,
                0.35,
                0,
                "footer",
                SlotBinding(source="block_field", block_index=2, field="text"),
            ),
        ),
    ),
    "content.1col": TemplateDefinition(
        template_key="content.1col",
        description="Editorial content slide with a text column and takeaway panel.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.75,
                CONTENT_WIDTH_NORMAL_IN,
                0.75,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "body_text",
                ResolvedElementKind.TEXTBOX,
                0.75,
                1.75,
                7.85,
                4.95,
                0,
                "body",
                SlotBinding(source="block", block_index=0),
            ),
            _slot(
                "takeaway",
                ResolvedElementKind.SHAPE,
                8.90,
                1.75,
                3.68,
                4.95,
                1,
                "takeaway",
                SlotBinding(source="block", block_index=1),
            ),
            _slot(
                "accent_bar",
                ResolvedElementKind.SHAPE,
                0.75,
                6.95,
                CONTENT_WIDTH_NORMAL_IN,
                0.18,
                1,
                "accent_bar",
                SlotBinding(source="static"),
            ),
        ),
    ),
    "content.2col.text_image": TemplateDefinition(
        template_key="content.2col.text_image",
        description="Two-column content slide with text at left and image or chart at right.",
        allowed_purposes=("content",),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.75,
                CONTENT_WIDTH_NORMAL_IN,
                0.75,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "text_col",
                ResolvedElementKind.TEXTBOX,
                0.75,
                1.75,
                TWO_COL_WIDTH_IN,
                5.00,
                0,
                "body",
                SlotBinding(source="block", block_index=0),
            ),
            _slot(
                "image_col",
                ResolvedElementKind.IMAGE,
                0.75 + TWO_COL_WIDTH_IN + COLUMN_GUTTER_IN,
                1.75,
                TWO_COL_WIDTH_IN,
                5.00,
                0,
                "image",
                SlotBinding(source="block", block_index=1),
            ),
        ),
    ),
    "content.3col.cards": TemplateDefinition(
        template_key="content.3col.cards",
        description="Three-card comparison layout.",
        allowed_purposes=("content",),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.75,
                CONTENT_WIDTH_NORMAL_IN,
                0.75,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "card_left",
                ResolvedElementKind.SHAPE,
                0.75,
                1.75,
                THREE_COL_WIDTH_IN,
                5.00,
                0,
                "card",
                SlotBinding(source="block_items", block_index=0, field="cards", item_index=0),
            ),
            _slot(
                "card_mid",
                ResolvedElementKind.SHAPE,
                0.75 + THREE_COL_WIDTH_IN + COLUMN_GUTTER_IN,
                1.75,
                THREE_COL_WIDTH_IN,
                5.00,
                0,
                "card",
                SlotBinding(source="block_items", block_index=0, field="cards", item_index=1),
            ),
            _slot(
                "card_right",
                ResolvedElementKind.SHAPE,
                0.75 + (2 * THREE_COL_WIDTH_IN) + (2 * COLUMN_GUTTER_IN),
                1.75,
                THREE_COL_WIDTH_IN,
                5.00,
                0,
                "card",
                SlotBinding(source="block_items", block_index=0, field="cards", item_index=2),
            ),
        ),
    ),
    "kpi.3up": TemplateDefinition(
        template_key="kpi.3up",
        description="Three-up KPI layout.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.75,
                CONTENT_WIDTH_NORMAL_IN,
                0.75,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "kpi_1",
                ResolvedElementKind.TEXTBOX,
                0.75,
                2.50,
                THREE_COL_WIDTH_IN,
                2.50,
                0,
                "kpi",
                SlotBinding(source="block", block_index=0),
            ),
            _slot(
                "kpi_2",
                ResolvedElementKind.TEXTBOX,
                0.75 + THREE_COL_WIDTH_IN + COLUMN_GUTTER_IN,
                2.50,
                THREE_COL_WIDTH_IN,
                2.50,
                0,
                "kpi",
                SlotBinding(source="block", block_index=1),
            ),
            _slot(
                "kpi_3",
                ResolvedElementKind.TEXTBOX,
                0.75 + (2 * THREE_COL_WIDTH_IN) + (2 * COLUMN_GUTTER_IN),
                2.50,
                THREE_COL_WIDTH_IN,
                2.50,
                0,
                "kpi",
                SlotBinding(source="block", block_index=2),
            ),
        ),
    ),
    "chart.full": TemplateDefinition(
        template_key="chart.full",
        description="Full-width chart slide with supporting citation footer.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.75,
                CONTENT_WIDTH_NORMAL_IN,
                0.75,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "chart_container",
                ResolvedElementKind.CHART,
                0.75,
                1.75,
                CONTENT_WIDTH_NORMAL_IN,
                5.00,
                0,
                "chart",
                SlotBinding(source="block", block_index=0),
            ),
            _slot(
                "cite_footer",
                ResolvedElementKind.TEXTBOX,
                0.75,
                6.80,
                CONTENT_WIDTH_NORMAL_IN,
                0.30,
                0,
                "citation",
                SlotBinding(source="block_field", block_index=0, field="source_citations"),
            ),
        ),
    ),
    "table.full": TemplateDefinition(
        template_key="table.full",
        description="Full-width table slide.",
        allowed_purposes=("content", "appendix"),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.75,
                0.75,
                CONTENT_WIDTH_NORMAL_IN,
                0.75,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "table_area",
                ResolvedElementKind.TABLE,
                0.75,
                1.75,
                CONTENT_WIDTH_NORMAL_IN,
                5.00,
                0,
                "table",
                SlotBinding(source="block", block_index=0),
            ),
        ),
    ),
    "appendix.details": TemplateDefinition(
        template_key="appendix.details",
        description="Dense appendix layout with thin margins.",
        allowed_purposes=("appendix",),
        strict_default=True,
        slots=(
            _slot(
                "headline",
                ResolvedElementKind.TEXTBOX,
                0.50,
                0.50,
                CONTENT_WIDTH_THIN_IN,
                0.60,
                0,
                "headline",
                SlotBinding(source="headline"),
            ),
            _slot(
                "dense_content",
                ResolvedElementKind.TEXTBOX,
                0.50,
                1.20,
                CONTENT_WIDTH_THIN_IN,
                5.80,
                0,
                "dense_body",
                SlotBinding(source="block", block_index=0),
            ),
        ),
    ),
}


TEMPLATE_ALIASES: Final[dict[str, str]] = {
    "title": "title.hero",
    "hero": "title.hero",
    "title_slide": "title.hero",
    "agenda": "agenda.list",
    "section": "section.header",
    "section.divider": "section.header",
    "executive": "executive.overview",
    "overview": "executive.overview",
    "executive_overview": "executive.overview",
    "architecture": "architecture.grid",
    "architecture_grid": "architecture.grid",
    "content": "content.1col",
    "1col": "content.1col",
    "single_col": "content.1col",
    "2col.text_image": "content.2col.text_image",
    "content.2col.text": "content.2col.text_image",
    "content.2col": "content.2col.text_image",
    "text_image": "content.2col.text_image",
    "summary.basic": "content.1col",
    "summary": "content.1col",
    "3col.cards": "content.3col.cards",
    "cards.3up": "content.3col.cards",
    "compare.3up": "content.3col.cards",
    "kpi": "kpi.3up",
    "kpi_cards": "kpi.3up",
    "chart": "chart.full",
    "chart_focus": "chart.full",
    "table": "table.full",
    "appendix": "appendix.details",
    "details": "appendix.details",
    "backup": "appendix.details",
}


def canonical_template_key(template_key: str) -> str:
    normalized = template_key.strip()
    return TEMPLATE_ALIASES.get(normalized, normalized)


def get_template_definition(template_key: str) -> TemplateDefinition:
    canonical_key = canonical_template_key(template_key)
    try:
        return TEMPLATE_REGISTRY[canonical_key]
    except KeyError as exc:
        raise ValueError(f"unknown template_key: {template_key}") from exc


def list_template_keys() -> tuple[str, ...]:
    return tuple(TEMPLATE_REGISTRY.keys())
