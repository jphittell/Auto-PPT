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
    "title.cover": TemplateDefinition(
        template_key="title.cover",
        description="Cover slide with title, subtitle, presenter metadata, and optional logo.",
        allowed_purposes=("title",),
        strict_default=True,
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 1.50, 2.50, 10.33, 1.25, 0, "headline", SlotBinding(source="headline")),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 2.00, 4.00, 9.33, 0.75, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle")),
            _slot("presenter", ResolvedElementKind.TEXTBOX, 0.75, 6.50, 5.00, 0.40, 0, "meta", SlotBinding(source="block_field", block_index=0, field="presenter")),
            _slot("date", ResolvedElementKind.TEXTBOX, 0.75, 6.90, 5.00, 0.40, 0, "meta", SlotBinding(source="block_field", block_index=0, field="date")),
            _slot("logo", ResolvedElementKind.IMAGE, 11.50, 6.50, 1.08, 0.50, 1, "logo", SlotBinding(source="block_field", block_index=0, field="logo")),
        ),
    ),
    "section.divider": TemplateDefinition(
        template_key="section.divider",
        description="Section divider with large headline and supporting tagline.",
        allowed_purposes=("section",),
        strict_default=True,
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 1.00, 3.00, 11.33, 1.25, 0, "headline", SlotBinding(source="headline")),
            _slot("tagline", ResolvedElementKind.TEXTBOX, 1.00, 4.30, 11.33, 0.60, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="tagline")),
            _slot("footer_info", ResolvedElementKind.TEXTBOX, 0.75, 6.80, CONTENT_WIDTH_NORMAL_IN, 0.30, 0, "footer", SlotBinding(source="block_field", block_index=0, field="footer_info")),
        ),
    ),
    "exec.summary": TemplateDefinition(
        template_key="exec.summary",
        description="Executive summary with key points, insight callout, and three supporting cards.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.75, 0.70, 11.833, 0.70, 0, "headline", SlotBinding(source="headline")),
            _slot("key_points", ResolvedElementKind.TEXTBOX, 0.75, 1.70, 5.20, 2.50, 0, "body", SlotBinding(source="block", block_index=0)),
            _slot("insight_callout", ResolvedElementKind.SHAPE, 0.75, 4.45, 5.20, 1.80, 1, "takeaway", SlotBinding(source="block", block_index=1)),
            _slot("card_1", ResolvedElementKind.SHAPE, 6.25, 1.70, 6.33, 1.55, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=0)),
            _slot("card_2", ResolvedElementKind.SHAPE, 6.25, 3.50, 6.33, 1.55, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=1)),
            _slot("card_3", ResolvedElementKind.SHAPE, 6.25, 5.30, 6.33, 1.55, 0, "card", SlotBinding(source="block_items", block_index=2, field="cards", item_index=2)),
        ),
    ),
    "headline.evidence": TemplateDefinition(
        template_key="headline.evidence",
        description="Headline with evidence body and takeaway sidebar.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.75, 0.75, CONTENT_WIDTH_NORMAL_IN, 0.75, 0, "headline", SlotBinding(source="headline")),
            _slot("body_text", ResolvedElementKind.TEXTBOX, 0.75, 1.75, 7.85, 4.95, 0, "body", SlotBinding(source="block", block_index=0)),
            _slot("takeaway", ResolvedElementKind.SHAPE, 8.90, 1.75, 3.68, 4.95, 1, "takeaway", SlotBinding(source="block", block_index=1)),
            _slot("accent_bar", ResolvedElementKind.SHAPE, 0.75, 6.95, CONTENT_WIDTH_NORMAL_IN, 0.18, 1, "accent_bar", SlotBinding(source="static")),
        ),
    ),
    "kpi.big": TemplateDefinition(
        template_key="kpi.big",
        description="Three-up KPI layout.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.75, 0.75, CONTENT_WIDTH_NORMAL_IN, 0.75, 0, "headline", SlotBinding(source="headline")),
            _slot("kpi_1", ResolvedElementKind.TEXTBOX, 0.75, 2.50, THREE_COL_WIDTH_IN, 2.50, 0, "kpi", SlotBinding(source="block", block_index=0)),
            _slot("kpi_2", ResolvedElementKind.TEXTBOX, 0.75 + THREE_COL_WIDTH_IN + COLUMN_GUTTER_IN, 2.50, THREE_COL_WIDTH_IN, 2.50, 0, "kpi", SlotBinding(source="block", block_index=1)),
            _slot("kpi_3", ResolvedElementKind.TEXTBOX, 0.75 + (2 * THREE_COL_WIDTH_IN) + (2 * COLUMN_GUTTER_IN), 2.50, THREE_COL_WIDTH_IN, 2.50, 0, "kpi", SlotBinding(source="block", block_index=2)),
        ),
    ),
    "compare.2col": TemplateDefinition(
        template_key="compare.2col",
        description="Two-column comparison with text in both columns.",
        allowed_purposes=("content",),
        strict_default=True,
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.75, 0.75, CONTENT_WIDTH_NORMAL_IN, 0.75, 0, "headline", SlotBinding(source="headline")),
            _slot("col_left", ResolvedElementKind.TEXTBOX, 0.75, 1.75, TWO_COL_WIDTH_IN, 5.00, 0, "body", SlotBinding(source="block", block_index=0)),
            _slot("col_right", ResolvedElementKind.TEXTBOX, 0.75 + TWO_COL_WIDTH_IN + COLUMN_GUTTER_IN, 1.75, TWO_COL_WIDTH_IN, 5.00, 0, "body", SlotBinding(source="block", block_index=1)),
        ),
    ),
    "chart.takeaway": TemplateDefinition(
        template_key="chart.takeaway",
        description="Chart-focused slide with a right-hand takeaway sidebar and citation footer.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.75, 0.75, 11.833, 0.75, 0, "headline", SlotBinding(source="headline")),
            _slot("chart_container", ResolvedElementKind.CHART, 0.75, 1.75, 8.30, 4.70, 0, "chart", SlotBinding(source="block", block_index=0)),
            _slot("takeaway", ResolvedElementKind.SHAPE, 9.35, 1.75, 3.23, 4.70, 1, "takeaway", SlotBinding(source="block", block_index=1)),
            _slot("cite_footer", ResolvedElementKind.TEXTBOX, 0.75, 6.70, 11.833, 0.30, 0, "citation", SlotBinding(source="block_field", block_index=0, field="source_citations")),
        ),
    ),
    "closing.actions": TemplateDefinition(
        template_key="closing.actions",
        description="Closing slide with action items and a final callout.",
        allowed_purposes=("content", "summary", "closing"),
        strict_default=True,
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.75, 0.75, 11.833, 0.75, 0, "headline", SlotBinding(source="headline")),
            _slot("action_items", ResolvedElementKind.TEXTBOX, 0.75, 1.75, 11.833, 3.50, 0, "body", SlotBinding(source="block", block_index=0)),
            _slot("closing_callout", ResolvedElementKind.SHAPE, 0.75, 5.50, 11.833, 1.25, 1, "takeaway", SlotBinding(source="block", block_index=1)),
            _slot("accent_bar", ResolvedElementKind.SHAPE, 0.75, 6.95, 11.833, 0.18, 1, "accent_bar", SlotBinding(source="static")),
        ),
    ),
}


TEMPLATE_ALIASES: Final[dict[str, str]] = {
    "title": "title.cover",
    "hero": "title.cover",
    "title_slide": "title.cover",
    "title.hero": "title.cover",
    "section": "section.divider",
    "section.divider": "section.divider",
    "section.header": "section.divider",
    "executive": "exec.summary",
    "overview": "exec.summary",
    "executive_summary": "exec.summary",
    "executive_overview": "exec.summary",
    "executive.overview": "exec.summary",
    "architecture": "exec.summary",
    "architecture_grid": "exec.summary",
    "architecture.grid": "exec.summary",
    "content": "headline.evidence",
    "1col": "headline.evidence",
    "single_col": "headline.evidence",
    "content.1col": "headline.evidence",
    "summary.basic": "headline.evidence",
    "summary": "headline.evidence",
    "table": "headline.evidence",
    "table.full": "headline.evidence",
    "appendix": "headline.evidence",
    "appendix.details": "headline.evidence",
    "details": "headline.evidence",
    "backup": "headline.evidence",
    "kpi": "kpi.big",
    "kpi_cards": "kpi.big",
    "kpi.3up": "kpi.big",
    "compare": "compare.2col",
    "2col.text_image": "compare.2col",
    "content.2col.text_image": "compare.2col",
    "content.2col": "compare.2col",
    "content.2col.text": "compare.2col",
    "text_image": "compare.2col",
    "3col.cards": "compare.2col",
    "content.3col.cards": "compare.2col",
    "cards.3up": "compare.2col",
    "compare.3up": "compare.2col",
    "chart": "chart.takeaway",
    "chart_focus": "chart.takeaway",
    "chart.full": "chart.takeaway",
    "closing": "closing.actions",
    "agenda": "closing.actions",
    "agenda.list": "closing.actions",
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
