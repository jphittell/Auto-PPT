from __future__ import annotations

import math

import pytest

from pptx_gen.layout.resolver import resolve_deck_layout
from pptx_gen.layout.templates import (
    COLUMN_GUTTER_IN,
    CONTENT_WIDTH_NORMAL_IN,
    TEMPLATE_ALIASES,
    THREE_COL_WIDTH_IN,
    TWO_COL_WIDTH_IN,
    SLIDE_HEIGHT_IN,
    SLIDE_WIDTH_IN,
    canonical_template_key,
    get_template_definition,
    list_template_keys,
)
from pptx_gen.planning.schemas import PresentationSpec


# Tier 1 (core) templates — returned by list_template_keys() default
TIER1_TEMPLATE_KEYS = (
    "title.cover",
    "section.divider",
    "exec.summary",
    "headline.evidence",
    "kpi.big",
    "chart.takeaway",
    "closing.actions",
)

# Tier 2 (frequent) — included in list_template_keys() default
TIER2_TEMPLATE_KEYS = (
    "compare.2col",
    "impact.statement",
    "timeline.roadmap",
    "matrix.2x2",
    "team.grid",
    "process.steps",
    "dashboard.kpi",
)

# Tier 3 (situational) — included in list_template_keys() default
TIER3_TEMPLATE_KEYS = (
    "quote.photo",
    "content.3col",
    "icons.3",
    "icons.4",
    "content.photo",
    "agenda.table",
    "financial.table",
    "status.rag",
)

# Tier 0 (deprecated/hidden) — excluded from default list_template_keys()
DEPRECATED_TEMPLATE_KEYS = (
    "content.4col",
    "bold.photo",
    "split.content",
    "screenshot",
    "quote.texture",  # merged into quote.photo
)

EXPECTED_TEMPLATE_KEYS = TIER1_TEMPLATE_KEYS + TIER2_TEMPLATE_KEYS + TIER3_TEMPLATE_KEYS


def test_all_canonical_template_keys_resolve() -> None:
    keys = list_template_keys()
    assert set(keys) == set(EXPECTED_TEMPLATE_KEYS), (
        f"Missing: {set(EXPECTED_TEMPLATE_KEYS) - set(keys)}, Extra: {set(keys) - set(EXPECTED_TEMPLATE_KEYS)}"
    )
    for key in EXPECTED_TEMPLATE_KEYS:
        assert get_template_definition(key).template_key == key


def test_deprecated_templates_excluded_by_default() -> None:
    keys = list_template_keys()
    for key in DEPRECATED_TEMPLATE_KEYS:
        assert key not in keys, f"{key} should be hidden from planner (tier 0)"


def test_min_tier_zero_includes_all_templates() -> None:
    all_keys = list_template_keys(min_tier=0)
    all_expected = set(EXPECTED_TEMPLATE_KEYS) | set(DEPRECATED_TEMPLATE_KEYS)
    assert set(all_keys) == all_expected, (
        f"Missing: {all_expected - set(all_keys)}, Extra: {set(all_keys) - all_expected}"
    )
    # 20 original + 5 Phase 1&2 + 2 Phase 3 = 27 total
    assert len(all_keys) == 27


def test_new_phase1_phase2_templates_exist() -> None:
    for key in ("timeline.roadmap", "matrix.2x2", "team.grid", "process.steps", "dashboard.kpi"):
        defn = get_template_definition(key)
        assert defn.template_key == key
        assert defn.planner_tier == 2
        assert len(defn.slots) >= 2


def test_new_phase3_templates_exist() -> None:
    for key in ("financial.table", "status.rag"):
        defn = get_template_definition(key)
        assert defn.template_key == key
        assert defn.planner_tier == 3
        assert len(defn.slots) >= 2


def test_consolidation_aliases_redirect() -> None:
    # quote default → quote.photo (quote.texture deprecated)
    assert canonical_template_key("quote") == "quote.photo"
    # bold.photo → impact.statement
    assert canonical_template_key("bold.photo") == "impact.statement"
    # split.content → compare.2col
    assert canonical_template_key("split.content") == "compare.2col"
    # quote.texture still resolves its own registry entry (backward compat)
    assert canonical_template_key("quote.texture") == "quote.texture"


def test_phase3_aliases_resolve() -> None:
    for alias, expected in [
        ("financial.table", "financial.table"),
        ("financial", "financial.table"),
        ("p&l", "financial.table"),
        ("budget", "financial.table"),
        ("status.rag", "status.rag"),
        ("status", "status.rag"),
        ("rag", "status.rag"),
        ("project.status", "status.rag"),
    ]:
        assert canonical_template_key(alias) == expected, f"{alias!r} → {canonical_template_key(alias)!r}"


def test_new_template_aliases_resolve() -> None:
    for alias, expected in [
        ("timeline", "timeline.roadmap"),
        ("roadmap", "timeline.roadmap"),
        ("milestones", "timeline.roadmap"),
        ("matrix", "matrix.2x2"),
        ("2x2", "matrix.2x2"),
        ("competitive", "matrix.2x2"),
        ("team", "team.grid"),
        ("people", "team.grid"),
        ("process", "process.steps"),
        ("steps", "process.steps"),
        ("dashboard", "dashboard.kpi"),
        ("kpi.grid", "dashboard.kpi"),
        ("kpi.6up", "dashboard.kpi"),
    ]:
        assert canonical_template_key(alias) == expected, f"{alias!r} → {canonical_template_key(alias)!r}, expected {expected!r}"


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("title", "title.cover"),
        ("hero", "title.cover"),
        ("title_slide", "title.cover"),
        ("agenda", "closing.actions"),
        ("section", "section.divider"),
        ("section.divider", "section.divider"),
        ("executive", "exec.summary"),
        ("overview", "exec.summary"),
        ("executive_summary", "exec.summary"),
        ("architecture", "exec.summary"),
        ("architecture_grid", "exec.summary"),
        ("content", "headline.evidence"),
        ("1col", "headline.evidence"),
        ("single_col", "headline.evidence"),
        ("2col.text_image", "compare.2col"),
        ("content.2col.text", "compare.2col"),
        ("content.2col", "compare.2col"),
        ("text_image", "compare.2col"),
        ("summary.basic", "headline.evidence"),
        ("summary", "headline.evidence"),
        ("3col.cards", "compare.2col"),
        ("cards.3up", "compare.2col"),
        ("compare.3up", "compare.2col"),
        ("kpi", "kpi.big"),
        ("kpi_cards", "kpi.big"),
        ("chart", "chart.takeaway"),
        ("chart_focus", "chart.takeaway"),
        ("table", "headline.evidence"),
        ("appendix", "headline.evidence"),
        ("details", "headline.evidence"),
        ("backup", "headline.evidence"),
    ],
)
def test_aliases_normalize_to_expected_template(alias: str, canonical: str) -> None:
    assert TEMPLATE_ALIASES[alias] == canonical
    assert canonical_template_key(alias) == canonical


def test_every_template_has_unique_slot_ids_and_within_slide_bounds() -> None:
    for key in list_template_keys():
        template = get_template_definition(key)
        slot_ids = [slot.slot_id for slot in template.slots]
        assert len(slot_ids) == len(set(slot_ids)), key

        for slot in template.slots:
            assert slot.x >= 0, (key, slot.slot_id)
            assert slot.y >= 0, (key, slot.slot_id)
            assert slot.w > 0, (key, slot.slot_id)
            assert slot.h > 0, (key, slot.slot_id)
            assert slot.x + slot.w <= SLIDE_WIDTH_IN + 1e-9, (key, slot.slot_id)
            assert slot.y + slot.h <= SLIDE_HEIGHT_IN + 1e-9, (key, slot.slot_id)


def test_derived_column_math_is_exact() -> None:
    assert math.isclose(TWO_COL_WIDTH_IN, (CONTENT_WIDTH_NORMAL_IN - COLUMN_GUTTER_IN) / 2, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(
        THREE_COL_WIDTH_IN,
        (CONTENT_WIDTH_NORMAL_IN - (2 * COLUMN_GUTTER_IN)) / 3,
        rel_tol=0,
        abs_tol=1e-12,
    )


def test_unknown_template_key_fails_clearly() -> None:
    with pytest.raises(ValueError, match="unknown template_key: does-not-exist"):
        get_template_definition("does-not-exist")


def test_resolver_integrates_with_richer_template_registry(make_presentation_spec, make_slide, make_block) -> None:
    spec = PresentationSpec(
        **make_presentation_spec(
            slides=[
                    make_slide(
                        purpose="closing",
                        template_key="closing.actions",
                    blocks=[
                        make_block(
                            kind="bullets",
                            content={"items": ["Intro", "Metrics", "Risks"]},
                            with_citation=False,
                        )
                    ],
                )
            ]
        )
    )

    layout = resolve_deck_layout(spec)

    assert layout.deck_id == "quarterly-business-review"
    assert len(layout.slides) == 1
    assert [element.element_id for element in layout.slides[0].elements] == [
        "s1:headline",
        "s1:action_items",
        "s1:closing_callout",
        "s1:accent_bar",
    ]
    assert layout.slides[0].elements[1].data_ref == "block:b1"
    assert layout.slides[0].elements[2].kind.value == "shape"


def test_specialized_template_bindings_match_export_contract(
    make_presentation_spec,
    make_slide,
    make_block,
) -> None:
    spec = PresentationSpec(
        **make_presentation_spec(
            slides=[
                make_slide(
                    slide_id="quote-photo",
                    template_key="quote.photo",
                    blocks=[
                        make_block(
                            block_id="b1",
                            kind="quote",
                            content={"text": "Standardize the platform first.", "attribution": "CIO"},
                            with_citation=False,
                        ),
                        make_block(
                            block_id="b2",
                            kind="image",
                            content={"path": "C:/assets/leader.png"},
                            with_citation=False,
                        ),
                    ],
                ),
                make_slide(
                    slide_id="chart-takeaway",
                    template_key="chart.takeaway",
                    blocks=[
                        make_block(
                            block_id="b1",
                            kind="chart",
                            content={"chart_type": "bar", "series": [{"label": "Q1", "value": 1.0}]},
                            with_citation=False,
                        ),
                        make_block(
                            block_id="b2",
                            kind="callout",
                            content={"text": "Automation compounds over time."},
                            with_citation=False,
                        ),
                    ],
                ),
                make_slide(
                    slide_id="split-content",
                    template_key="split.content",
                    blocks=[
                        make_block(block_id="b1", content={"text": "Current state"}, with_citation=False),
                        make_block(block_id="b2", content={"text": "Target state"}, with_citation=False),
                    ],
                ),
                make_slide(
                    slide_id="icons-three",
                    template_key="icons.3",
                    blocks=[
                        make_block(
                            block_id="b1",
                            kind="callout",
                            content={
                                "cards": [
                                    {"title": "Discover", "text": "Clarify the operating model"},
                                    {"title": "Align", "text": "Sequence the workstreams"},
                                    {"title": "Scale", "text": "Operationalize the controls"},
                                ]
                            },
                            with_citation=False,
                        ),
                    ],
                ),
                make_slide(
                    slide_id="icons-four",
                    template_key="icons.4",
                    blocks=[
                        make_block(
                            block_id="b1",
                            kind="callout",
                            content={
                                "cards": [
                                    {"title": "Plan", "text": "Define milestones"},
                                    {"title": "Build", "text": "Implement shared services"},
                                    {"title": "Run", "text": "Measure adoption"},
                                    {"title": "Improve", "text": "Close control gaps"},
                                ]
                            },
                            with_citation=False,
                        ),
                    ],
                ),
                make_slide(
                    slide_id="agenda-table",
                    template_key="agenda.table",
                    blocks=[
                        make_block(
                            block_id="b1",
                            kind="table",
                            content={"columns": ["Section", "Focus"], "rows": [["Discovery", "Align priorities"]]},
                            with_citation=False,
                        ),
                    ],
                ),
            ]
        )
    )

    layout = resolve_deck_layout(spec)
    slides_by_id = {slide.slide_id: slide for slide in layout.slides}

    quote_payloads = {element.element_id.split(":")[1]: element.payload for element in slides_by_id["quote-photo"].elements}
    assert quote_payloads["quote"]["content"] == "Standardize the platform first."
    assert quote_payloads["supporting_text"]["content"] == "CIO"
    assert quote_payloads["image"]["content"] == "C:/assets/leader.png"

    chart_elements = {element.element_id.split(":")[1]: element for element in slides_by_id["chart-takeaway"].elements}
    assert chart_elements["takeaway"].kind.value == "shape"
    assert chart_elements["takeaway"].payload["content"] == "Automation compounds over time."

    # split.content now redirects to compare.2col — slots renamed accordingly
    split_payloads = {element.element_id.split(":")[1]: element.payload for element in slides_by_id["split-content"].elements}
    assert split_payloads["col_left"]["content"] == {"text": "Current state"}
    assert split_payloads["col_right"]["content"] == {"text": "Target state"}

    icons_three_payloads = {element.element_id.split(":")[1]: element.payload for element in slides_by_id["icons-three"].elements}
    assert icons_three_payloads["card_1_title"]["content"]["title"] == "Discover"
    assert icons_three_payloads["card_3_text"]["content"]["text"] == "Operationalize the controls"

    icons_four_payloads = {element.element_id.split(":")[1]: element.payload for element in slides_by_id["icons-four"].elements}
    assert icons_four_payloads["card_2_title"]["content"]["title"] == "Build"
    assert icons_four_payloads["card_4_text"]["content"]["text"] == "Close control gaps"

    agenda_payloads = {element.element_id.split(":")[1]: element.payload for element in slides_by_id["agenda-table"].elements}
    assert agenda_payloads["table_lead"]["content"] is None
    assert agenda_payloads["table_main"]["content"]["columns"] == ["Section", "Focus"]
