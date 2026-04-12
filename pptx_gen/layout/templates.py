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
    placeholder_idx: int | None = None


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    template_key: str
    description: str
    allowed_purposes: tuple[str, ...]
    strict_default: bool
    layout_index: int | None
    slots: tuple[TemplateSlot, ...]
    planner_tier: int = 1  # 1=core, 2=frequent, 3=situational, 0=deprecated/hidden
    # Slide archetypes this template is well-suited for.  Maps to SlideArchetype enum values
    # in planning/schemas.py.  Empty tuple means the template is purpose-driven (title, section,
    # closing) and archetype selection does not apply.
    compatible_archetypes: tuple[str, ...] = ()


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
    placeholder_idx: int | None = None,
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
        placeholder_idx=placeholder_idx,
    )


TEMPLATE_REGISTRY: Final[dict[str, TemplateDefinition]] = {
    "title.cover": TemplateDefinition(
        template_key="title.cover",
        description="Cover slide with title, subtitle, presenter metadata, and optional logo.",
        allowed_purposes=("title",),
        strict_default=True,
        layout_index=0,
        planner_tier=1,
        compatible_archetypes=(),  # structural — archetype does not apply
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.87, 2.35, 7.0, 1.4, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.87, 3.85, 7.0, 0.37, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=33),
            _slot("presenter", ResolvedElementKind.TEXTBOX, 0.87, 4.97, 5.55, 0.29, 0, "meta", SlotBinding(source="block_field", block_index=0, field="presenter"), placeholder_idx=35),
            _slot("date", ResolvedElementKind.TEXTBOX, 0.87, 5.27, 5.55, 0.45, 0, "meta", SlotBinding(source="block_field", block_index=0, field="date"), placeholder_idx=34),
            _slot("logo", ResolvedElementKind.IMAGE, 0.87, 6.28, 4.2, 0.37, 1, "logo", SlotBinding(source="block_field", block_index=0, field="logo"), placeholder_idx=36),
        ),
    ),
    "section.divider": TemplateDefinition(
        template_key="section.divider",
        description="Section divider with large headline and supporting tagline.",
        allowed_purposes=("section",),
        strict_default=True,
        layout_index=12,
        planner_tier=1,
        compatible_archetypes=(),  # structural
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.84, 2.56, 7.0, 1.4, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("tagline", ResolvedElementKind.TEXTBOX, 0.85, 4.52, 7.0, 0.75, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="tagline"), placeholder_idx=33),
            _slot("footer_info", ResolvedElementKind.TEXTBOX, 1.23, 7.03, 6.28, 0.40, 0, "footer", SlotBinding(source="block_field", block_index=0, field="footer_info"), placeholder_idx=39),
        ),
    ),
    "exec.summary": TemplateDefinition(
        template_key="exec.summary",
        description="Executive summary with key points, insight callout, and three supporting cards.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=32,
        planner_tier=1,
        compatible_archetypes=("executive_summary", "executive_overview"),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.84, 0.75, 11.67, 0.35, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
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
        layout_index=55,
        planner_tier=1,
        compatible_archetypes=("generic", "executive_overview"),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 11.67, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=41),
            _slot("body_text", ResolvedElementKind.TEXTBOX, 0.84, 1.75, 11.67, 4.93, 0, "body", SlotBinding(source="block", block_index=0), placeholder_idx=14),
            _slot("takeaway", ResolvedElementKind.SHAPE, 8.90, 1.75, 3.68, 4.95, 1, "takeaway", SlotBinding(source="block", block_index=1)),
            _slot("accent_bar", ResolvedElementKind.SHAPE, 0.75, 6.95, CONTENT_WIDTH_NORMAL_IN, 0.18, 1, "accent_bar", SlotBinding(source="static")),
        ),
    ),
    "kpi.big": TemplateDefinition(
        template_key="kpi.big",
        description="Three-up KPI layout.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=21,
        planner_tier=1,
        compatible_archetypes=("metrics",),  # 3-up large KPIs; dashboard archetype → dashboard.kpi
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.84, 0.76, 8.96, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.84, 1.10, 8.96, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=41),
            _slot("kpi_1", ResolvedElementKind.TEXTBOX, 0.83, 1.75, 5.56, 2.64, 0, "kpi", SlotBinding(source="block", block_index=0), placeholder_idx=15),
            _slot("kpi_2", ResolvedElementKind.TEXTBOX, 0.83, 5.09, 5.55, 1.59, 0, "kpi", SlotBinding(source="block", block_index=1), placeholder_idx=14),
            _slot("kpi_3", ResolvedElementKind.TEXTBOX, 6.90, 1.75, 5.55, 4.93, 0, "kpi", SlotBinding(source="block", block_index=2)),
        ),
    ),
    "compare.2col": TemplateDefinition(
        template_key="compare.2col",
        description="Two-column comparison with text in both columns.",
        allowed_purposes=("content",),
        strict_default=True,
        layout_index=57,
        planner_tier=2,
        compatible_archetypes=("comparison",),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 11.67, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=41),
            _slot("col_left", ResolvedElementKind.TEXTBOX, 0.84, 1.75, 5.56, 4.93, 0, "body", SlotBinding(source="block", block_index=0), placeholder_idx=14),
            _slot("col_right", ResolvedElementKind.TEXTBOX, 6.97, 1.75, 5.56, 4.93, 0, "body", SlotBinding(source="block", block_index=1), placeholder_idx=19),
        ),
    ),
    "chart.takeaway": TemplateDefinition(
        template_key="chart.takeaway",
        description="Chart-focused slide with a right-hand takeaway sidebar and citation footer.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=62,
        planner_tier=1,
        compatible_archetypes=("chart",),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 7.43, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 7.43, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=41),
            _slot("chart_container", ResolvedElementKind.CHART, 0.84, 1.75, 7.43, 4.93, 0, "chart", SlotBinding(source="block", block_index=0), placeholder_idx=14),
            _slot("takeaway", ResolvedElementKind.SHAPE, 9.08, 0.00, 4.25, 7.50, 1, "takeaway", SlotBinding(source="block_field", block_index=1, field="text")),
            _slot("cite_footer", ResolvedElementKind.TEXTBOX, 0.75, 6.70, 11.833, 0.30, 0, "citation", SlotBinding(source="block_field", block_index=0, field="source_citations")),
        ),
    ),
    "closing.actions": TemplateDefinition(
        template_key="closing.actions",
        description="Closing slide with action items and a final callout.",
        allowed_purposes=("content", "summary", "closing"),
        strict_default=True,
        layout_index=23,
        planner_tier=1,
        compatible_archetypes=(),  # structural — purpose-driven closing
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.84, 4.18, 5.50, 0.53, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("action_items", ResolvedElementKind.TEXTBOX, 0.83, 5.29, 5.50, 0.22, 0, "body", SlotBinding(source="block", block_index=0), placeholder_idx=37),
            _slot("closing_callout", ResolvedElementKind.SHAPE, 0.83, 5.59, 5.50, 0.98, 1, "takeaway", SlotBinding(source="block", block_index=1), placeholder_idx=36),
            _slot("accent_bar", ResolvedElementKind.SHAPE, 0.75, 6.95, 11.833, 0.18, 1, "accent_bar", SlotBinding(source="static")),
        ),
    ),
    "quote.photo": TemplateDefinition(
        template_key="quote.photo",
        description="Quote slide with a supporting photo.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=19,
        planner_tier=3,
        compatible_archetypes=(),  # decorative/situational — no archetype match
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 2.00, 6.86, 2.22, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("quote", ResolvedElementKind.TEXTBOX, 0.83, 5.33, 5.83, 0.98, 0, "body", SlotBinding(source="block_field", block_index=0, field="text"), placeholder_idx=36),
            _slot("supporting_text", ResolvedElementKind.TEXTBOX, 0.83, 4.97, 5.83, 0.29, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="attribution"), placeholder_idx=37),
            _slot("image", ResolvedElementKind.IMAGE, 9.08, 0.00, 4.25, 7.50, 0, "image", SlotBinding(source="block_field", block_index=1, field="path"), placeholder_idx=47),
        ),
    ),
    "quote.texture": TemplateDefinition(
        template_key="quote.texture",
        description="Standalone quote on textured background — deprecated; use quote.photo.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=17,
        planner_tier=0,
        compatible_archetypes=(),  # deprecated
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 2.61, 9.57, 1.60, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("quote", ResolvedElementKind.TEXTBOX, 0.83, 1.25, 3.16, 0.50, 0, "body", SlotBinding(source="block_field", block_index=0, field="text"), placeholder_idx=45),
            _slot("supporting_text", ResolvedElementKind.TEXTBOX, 0.83, 5.33, 5.83, 0.98, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="attribution"), placeholder_idx=36),
        ),
    ),
    "impact.statement": TemplateDefinition(
        template_key="impact.statement",
        description="Bold single-statement slide for a strong executive message.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=14,
        planner_tier=2,
        compatible_archetypes=(),  # decorative — chosen by purpose, not archetype
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.84, 3.30, 6.68, 0.90, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
        ),
    ),
    "content.3col": TemplateDefinition(
        template_key="content.3col",
        description="Three-column content layout.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=59,
        planner_tier=3,
        compatible_archetypes=("generic", "comparison"),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 11.67, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=41),
            _slot("col_1", ResolvedElementKind.TEXTBOX, 0.84, 1.75, 3.60, 4.93, 0, "body", SlotBinding(source="block", block_index=0), placeholder_idx=14),
            _slot("col_2", ResolvedElementKind.TEXTBOX, 4.87, 1.76, 3.60, 4.93, 0, "body", SlotBinding(source="block", block_index=1), placeholder_idx=20),
            _slot("col_3", ResolvedElementKind.TEXTBOX, 8.89, 1.77, 3.60, 4.93, 0, "body", SlotBinding(source="block", block_index=2), placeholder_idx=21),
        ),
    ),
    "content.4col": TemplateDefinition(
        template_key="content.4col",
        description="Four-column content layout — too dense for exec; prefer icons.4.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=60,
        planner_tier=0,
        compatible_archetypes=(),  # deprecated
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 11.67, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=41),
            _slot("col_1", ResolvedElementKind.TEXTBOX, 0.84, 1.76, 2.70, 4.93, 0, "body", SlotBinding(source="block", block_index=0), placeholder_idx=14),
            _slot("col_2", ResolvedElementKind.TEXTBOX, 3.83, 1.76, 2.70, 4.93, 0, "body", SlotBinding(source="block", block_index=1), placeholder_idx=15),
            _slot("col_3", ResolvedElementKind.TEXTBOX, 6.82, 1.76, 2.70, 4.93, 0, "body", SlotBinding(source="block", block_index=2), placeholder_idx=16),
            _slot("col_4", ResolvedElementKind.TEXTBOX, 9.81, 1.76, 2.70, 4.93, 0, "body", SlotBinding(source="block", block_index=3), placeholder_idx=20),
        ),
    ),
    "icons.3": TemplateDefinition(
        template_key="icons.3",
        description="Three icon cards with subheads and text.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=68,
        planner_tier=3,
        compatible_archetypes=("generic",),  # parallel concepts/features; process flow → process.steps
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 11.67, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=45),
            _slot("card_1_title", ResolvedElementKind.TEXTBOX, 1.00, 4.36, 2.49, 0.35, 0, "card", SlotBinding(source="block_items", block_index=0, field="cards", item_index=0), placeholder_idx=25),
            _slot("card_1_text", ResolvedElementKind.TEXTBOX, 1.00, 4.79, 2.49, 1.36, 0, "body", SlotBinding(source="block_items", block_index=0, field="cards", item_index=0), placeholder_idx=24),
            _slot("card_2_title", ResolvedElementKind.TEXTBOX, 5.25, 4.36, 2.49, 0.35, 0, "card", SlotBinding(source="block_items", block_index=0, field="cards", item_index=1), placeholder_idx=37),
            _slot("card_2_text", ResolvedElementKind.TEXTBOX, 5.25, 4.79, 2.49, 1.36, 0, "body", SlotBinding(source="block_items", block_index=0, field="cards", item_index=1), placeholder_idx=38),
            _slot("card_3_title", ResolvedElementKind.TEXTBOX, 9.46, 4.36, 2.49, 0.35, 0, "card", SlotBinding(source="block_items", block_index=0, field="cards", item_index=2), placeholder_idx=40),
            _slot("card_3_text", ResolvedElementKind.TEXTBOX, 9.46, 4.79, 2.49, 1.36, 0, "body", SlotBinding(source="block_items", block_index=0, field="cards", item_index=2), placeholder_idx=41),
        ),
    ),
    "icons.4": TemplateDefinition(
        template_key="icons.4",
        description="Four icon cards with subheads and text.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=70,
        planner_tier=3,
        compatible_archetypes=("generic",),  # parallel concepts/features; process flow → process.steps
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.84, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 11.84, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=41),
            _slot("card_1_title", ResolvedElementKind.TEXTBOX, 0.83, 4.36, 2.35, 0.35, 0, "card", SlotBinding(source="block_items", block_index=0, field="cards", item_index=0), placeholder_idx=25),
            _slot("card_1_text", ResolvedElementKind.TEXTBOX, 0.83, 4.79, 2.35, 1.36, 0, "body", SlotBinding(source="block_items", block_index=0, field="cards", item_index=0), placeholder_idx=24),
            _slot("card_2_title", ResolvedElementKind.TEXTBOX, 3.89, 4.36, 2.35, 0.35, 0, "card", SlotBinding(source="block_items", block_index=0, field="cards", item_index=1), placeholder_idx=43),
            _slot("card_2_text", ResolvedElementKind.TEXTBOX, 3.89, 4.79, 2.35, 1.36, 0, "body", SlotBinding(source="block_items", block_index=0, field="cards", item_index=1), placeholder_idx=44),
            _slot("card_3_title", ResolvedElementKind.TEXTBOX, 7.00, 4.36, 2.35, 0.35, 0, "card", SlotBinding(source="block_items", block_index=0, field="cards", item_index=2), placeholder_idx=46),
            _slot("card_3_text", ResolvedElementKind.TEXTBOX, 7.00, 4.79, 2.35, 1.36, 0, "body", SlotBinding(source="block_items", block_index=0, field="cards", item_index=2), placeholder_idx=47),
            _slot("card_4_title", ResolvedElementKind.TEXTBOX, 10.10, 4.36, 2.35, 0.35, 0, "card", SlotBinding(source="block_items", block_index=0, field="cards", item_index=3), placeholder_idx=49),
            _slot("card_4_text", ResolvedElementKind.TEXTBOX, 10.10, 4.79, 2.35, 1.36, 0, "body", SlotBinding(source="block_items", block_index=0, field="cards", item_index=3), placeholder_idx=50),
        ),
    ),
    "content.photo": TemplateDefinition(
        template_key="content.photo",
        description="Content slide with side photo.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=62,
        planner_tier=3,
        compatible_archetypes=("generic",),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 7.43, 0.34, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 7.43, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle"), placeholder_idx=41),
            _slot("body", ResolvedElementKind.TEXTBOX, 0.84, 1.75, 7.43, 4.93, 0, "body", SlotBinding(source="block", block_index=0), placeholder_idx=14),
            _slot("image", ResolvedElementKind.IMAGE, 9.08, 0.00, 4.25, 7.50, 0, "image", SlotBinding(source="block_field", block_index=1, field="path"), placeholder_idx=47),
        ),
    ),
    "bold.photo": TemplateDefinition(
        template_key="bold.photo",
        description="Bold statement with half-slide photo — deprecated; use impact.statement.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=80,
        planner_tier=0,
        compatible_archetypes=(),  # deprecated
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.84, 3.30, 5.03, 0.90, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("image", ResolvedElementKind.IMAGE, 6.67, 0.00, 6.66, 7.50, 0, "image", SlotBinding(source="block_field", block_index=1, field="path"), placeholder_idx=34),
        ),
    ),
    "split.content": TemplateDefinition(
        template_key="split.content",
        description="Split content layout with line divider — deprecated; use compare.2col.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=73,
        planner_tier=0,
        compatible_archetypes=(),  # deprecated
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.84, 3.30, 3.43, 0.90, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("body_left", ResolvedElementKind.TEXTBOX, 0.84, 1.75, 5.56, 4.93, 0, "body", SlotBinding(source="block", block_index=0)),
            _slot("body_right", ResolvedElementKind.TEXTBOX, 6.97, 1.75, 5.56, 4.93, 0, "body", SlotBinding(source="block", block_index=1)),
        ),
    ),
    "agenda.table": TemplateDefinition(
        template_key="agenda.table",
        description="Structured agenda or matrix table.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=35,
        planner_tier=3,
        compatible_archetypes=(),  # table layout; "matrix" archetype routes to matrix.2x2
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.84, 0.75, 8.20, 0.35, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("table_lead", ResolvedElementKind.TEXTBOX, 0.84, 1.41, 0.48, 4.06, 0, "body", SlotBinding(source="static"), placeholder_idx=14),
            _slot("table_main", ResolvedElementKind.TABLE, 1.52, 1.41, 7.52, 4.06, 0, "table", SlotBinding(source="block", block_index=0), placeholder_idx=18),
        ),
    ),
    "screenshot": TemplateDefinition(
        template_key="screenshot",
        description="Screenshot showcase with explanatory text — low exec relevance.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=82,
        planner_tier=0,
        compatible_archetypes=(),  # deprecated/low-exec
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 2.70, 4.11, 0.90, 0, "headline", SlotBinding(source="headline"), placeholder_idx=0),
            _slot("body", ResolvedElementKind.TEXTBOX, 0.83, 3.90, 4.11, 1.34, 0, "body", SlotBinding(source="block", block_index=0), placeholder_idx=24),
            _slot("image", ResolvedElementKind.IMAGE, 5.87, 1.85, 6.83, 4.12, 0, "image", SlotBinding(source="block_field", block_index=1, field="path"), placeholder_idx=38),
        ),
    ),
    # --- Phase 1 & 2 new templates (Tier 2) ---
    "timeline.roadmap": TemplateDefinition(
        template_key="timeline.roadmap",
        description="Horizontal milestone timeline with 3–5 steps.",
        allowed_purposes=("content",),
        strict_default=True,
        layout_index=None,
        planner_tier=2,
        compatible_archetypes=("timeline",),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline")),
            _slot("subtitle", ResolvedElementKind.TEXTBOX, 0.83, 1.10, 11.67, 0.36, 0, "subtitle", SlotBinding(source="block_field", block_index=0, field="subtitle")),
            _slot("timeline", ResolvedElementKind.SHAPE, 0.83, 1.70, 11.67, 4.93, 0, "body", SlotBinding(source="block", block_index=0)),
        ),
    ),
    "matrix.2x2": TemplateDefinition(
        template_key="matrix.2x2",
        description="2×2 analytical matrix with axis labels and four quadrant cards.",
        allowed_purposes=("content",),
        strict_default=True,
        layout_index=None,
        planner_tier=2,
        compatible_archetypes=("matrix",),  # 2x2 quadrant; side-by-side comparison → compare.2col
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline")),
            _slot("x_axis_label", ResolvedElementKind.TEXTBOX, 3.50, 6.90, 6.33, 0.30, 0, "meta", SlotBinding(source="block_field", block_index=0, field="x_axis_label")),
            _slot("y_axis_label", ResolvedElementKind.TEXTBOX, 0.20, 2.00, 1.00, 3.50, 0, "meta", SlotBinding(source="block_field", block_index=0, field="y_axis_label")),
            _slot("quadrant_tl", ResolvedElementKind.SHAPE, 1.33, 1.50, 5.50, 2.50, 0, "card", SlotBinding(source="block", block_index=0)),
            _slot("quadrant_tr", ResolvedElementKind.SHAPE, 7.00, 1.50, 5.50, 2.50, 0, "card", SlotBinding(source="block", block_index=1)),
            _slot("quadrant_bl", ResolvedElementKind.SHAPE, 1.33, 4.20, 5.50, 2.50, 0, "card", SlotBinding(source="block", block_index=2)),
            _slot("quadrant_br", ResolvedElementKind.SHAPE, 7.00, 4.20, 5.50, 2.50, 0, "card", SlotBinding(source="block", block_index=3)),
        ),
    ),
    "team.grid": TemplateDefinition(
        template_key="team.grid",
        description="Team slide with 3–4 person cards (image placeholder + name + title + bio).",
        allowed_purposes=("content",),
        strict_default=True,
        layout_index=None,
        planner_tier=2,
        compatible_archetypes=("team",),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline")),
            _slot("team_cards", ResolvedElementKind.SHAPE, 0.83, 1.50, 11.67, 5.25, 0, "body", SlotBinding(source="block", block_index=0)),
        ),
    ),
    "process.steps": TemplateDefinition(
        template_key="process.steps",
        description="Numbered 3–5 step process flow with connecting arrows.",
        allowed_purposes=("content",),
        strict_default=True,
        layout_index=None,
        planner_tier=2,
        compatible_archetypes=("process",),
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline")),
            _slot("steps", ResolvedElementKind.SHAPE, 0.83, 1.70, 11.67, 4.93, 0, "body", SlotBinding(source="block", block_index=0)),
        ),
    ),
    "dashboard.kpi": TemplateDefinition(
        template_key="dashboard.kpi",
        description="Dashboard with 4–6 KPI metric tiles in a 2×2 or 2×3 grid.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=None,
        planner_tier=2,
        compatible_archetypes=("dashboard",),  # 4-6 tile KPI grid; 3-up metrics → kpi.big
        slots=(
            _slot("headline", ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline")),
            _slot("kpi_grid", ResolvedElementKind.SHAPE, 0.83, 1.50, 11.67, 5.25, 0, "body", SlotBinding(source="block", block_index=0)),
        ),
    ),
    # --- Phase 3 new templates (Tier 3 — situational) ---
    "financial.table": TemplateDefinition(
        template_key="financial.table",
        description="Structured financial table with headline, full-width data, and footnote.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=None,
        planner_tier=3,
        compatible_archetypes=("financial",),
        slots=(
            _slot("headline",   ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline")),
            _slot("table_main", ResolvedElementKind.TABLE,   0.83, 1.30, 11.67, 5.50, 0, "table",    SlotBinding(source="block", block_index=0)),
            _slot("footnote",   ResolvedElementKind.TEXTBOX, 0.83, 7.00, 11.67, 0.28, 0, "citation", SlotBinding(source="block_field", block_index=1, field="text")),
        ),
    ),
    "status.rag": TemplateDefinition(
        template_key="status.rag",
        description="RAG status dashboard with per-initiative colored status cards.",
        allowed_purposes=("content", "summary"),
        strict_default=True,
        layout_index=None,
        planner_tier=3,
        compatible_archetypes=("status",),
        slots=(
            _slot("headline",     ResolvedElementKind.TEXTBOX, 0.83, 0.76, 11.67, 0.34, 0, "headline", SlotBinding(source="headline")),
            _slot("status_cards", ResolvedElementKind.SHAPE,   0.83, 1.30, 11.67, 5.70, 0, "body",     SlotBinding(source="block", block_index=0)),
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
    "quote": "quote.photo",        # consolidated: quote.texture deprecated
    "quote.photo": "quote.photo",
    "quote.texture": "quote.texture",  # kept for backward compat (tier 0)
    "impact": "impact.statement",
    "impact.statement": "impact.statement",
    "content.3col": "content.3col",
    "3col": "content.3col",
    "content.4col": "content.4col",
    "4col": "content.4col",
    "icons.3": "icons.3",
    "icons.4": "icons.4",
    "content.photo": "content.photo",
    "bold.photo": "impact.statement",   # consolidated: bold.photo deprecated
    "split.content": "compare.2col",    # consolidated: split.content deprecated
    "agenda.table": "agenda.table",
    "screenshot": "screenshot",
    # Phase 1 & 2 new templates
    "timeline.roadmap": "timeline.roadmap",
    "timeline": "timeline.roadmap",
    "roadmap": "timeline.roadmap",
    "milestones": "timeline.roadmap",
    "matrix.2x2": "matrix.2x2",
    "matrix": "matrix.2x2",
    "2x2": "matrix.2x2",
    "competitive": "matrix.2x2",
    "team.grid": "team.grid",
    "team": "team.grid",
    "people": "team.grid",
    "process.steps": "process.steps",
    "process": "process.steps",
    "steps": "process.steps",
    "dashboard.kpi": "dashboard.kpi",
    "dashboard": "dashboard.kpi",
    "kpi.grid": "dashboard.kpi",
    "kpi.6up": "dashboard.kpi",
    # Phase 3
    "financial.table": "financial.table",
    "financial": "financial.table",
    "p&l": "financial.table",
    "budget": "financial.table",
    "status.rag": "status.rag",
    "status": "status.rag",
    "rag": "status.rag",
    "project.status": "status.rag",
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


def list_template_keys(*, min_tier: int = 1) -> tuple[str, ...]:
    return tuple(key for key, defn in TEMPLATE_REGISTRY.items() if defn.planner_tier >= min_tier)
