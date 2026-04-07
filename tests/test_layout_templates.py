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


EXPECTED_TEMPLATE_KEYS = (
    "title.cover",
    "section.divider",
    "exec.summary",
    "headline.evidence",
    "kpi.big",
    "compare.2col",
    "chart.takeaway",
    "closing.actions",
)


def test_all_canonical_template_keys_resolve() -> None:
    assert list_template_keys() == EXPECTED_TEMPLATE_KEYS
    for key in EXPECTED_TEMPLATE_KEYS:
        assert get_template_definition(key).template_key == key


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
