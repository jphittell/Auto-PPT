"""Layout resolver boundary and template-key normalization."""

from __future__ import annotations

from pptx_gen.layout.schemas import ResolvedDeckLayout
from pptx_gen.layout.templates import TEMPLATE_ALIASES, TEMPLATE_CATALOG
from pptx_gen.planning.schemas import PresentationSpec


def canonical_template_key(template_key: str) -> str:
    return TEMPLATE_ALIASES.get(template_key, template_key)


def resolve_deck_layout(spec: PresentationSpec) -> ResolvedDeckLayout:
    """TODO: map SlideSpec blocks to absolute slide coordinates."""

    for slide in spec.slides:
        key = canonical_template_key(slide.layout_intent.template_key)
        if key not in TEMPLATE_CATALOG:
            raise ValueError(f"unknown template_key: {slide.layout_intent.template_key}")
    raise NotImplementedError("Layout resolution is not implemented in Phase 1.")

