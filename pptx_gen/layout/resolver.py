"""Layout resolver built on the deterministic template registry."""

from __future__ import annotations

from typing import Any

from pptx_gen.layout.schemas import ResolvedDeckLayout, ResolvedSlideLayout
from pptx_gen.layout.templates import (
    TemplateDefinition,
    TemplateSlot,
    canonical_template_key,
    get_template_definition,
)
from pptx_gen.planning.schemas import PresentationBlock, PresentationSpec, SlideSpec


def resolve_deck_layout(spec: PresentationSpec) -> ResolvedDeckLayout:
    slides: list[ResolvedSlideLayout] = []

    for slide in spec.slides:
        template = get_template_definition(slide.layout_intent.template_key)
        slides.append(_resolve_slide(slide, template))

    return ResolvedDeckLayout(
        deck_id=_deck_id_from_title(spec.title),
        slides=slides,
    )


def _resolve_slide(slide: SlideSpec, template: TemplateDefinition) -> ResolvedSlideLayout:
    elements = []
    for slot in template.slots:
        payload, data_ref = _resolve_slot_payload(slide, slot)
        elements.append(
            {
                "element_id": f"{slide.slide_id}:{slot.slot_id}",
                "kind": slot.kind,
                "x": slot.x,
                "y": slot.y,
                "w": slot.w,
                "h": slot.h,
                "z": slot.z,
                "data_ref": data_ref,
                "style_ref": slot.style_ref,
                "payload": payload,
            }
        )

    return ResolvedSlideLayout(slide_id=slide.slide_id, elements=elements)


def _resolve_slot_payload(slide: SlideSpec, slot: TemplateSlot) -> tuple[dict[str, Any], str]:
    binding = slot.binding

    if binding.source == "headline":
        return (
            {
                "slot_id": slot.slot_id,
                "template_key": canonical_template_key(slide.layout_intent.template_key),
                "content": slide.headline,
            },
            f"slide:{slide.slide_id}:headline",
        )

    if binding.source == "static":
        return (
            {
                "slot_id": slot.slot_id,
                "template_key": canonical_template_key(slide.layout_intent.template_key),
                "content": None,
            },
            f"slide:{slide.slide_id}:{slot.slot_id}",
        )

    block = _block_at(slide.blocks, binding.block_index)
    if block is None:
        return (
            {
                "slot_id": slot.slot_id,
                "template_key": canonical_template_key(slide.layout_intent.template_key),
                "content": None,
            },
            f"slide:{slide.slide_id}:{slot.slot_id}",
        )

    if binding.source == "block":
        return _payload_for_block(slot, block)

    if binding.source == "block_field":
        return _payload_for_block_field(slot, block, binding.field)

    if binding.source == "block_items":
        return _payload_for_block_item(slot, block, binding.field, binding.item_index)

    raise ValueError(f"unsupported slot binding source: {binding.source}")


def _payload_for_block(slot: TemplateSlot, block: PresentationBlock) -> tuple[dict[str, Any], str]:
    return (
        {
            "slot_id": slot.slot_id,
            "block_id": block.block_id,
            "block_kind": block.kind.value,
            "content": block.content,
        },
        f"block:{block.block_id}",
    )


def _payload_for_block_field(
    slot: TemplateSlot,
    block: PresentationBlock,
    field_name: str | None,
) -> tuple[dict[str, Any], str]:
    if field_name is None:
        return _payload_for_block(slot, block)
    value = block.content.get(field_name)
    if value is None and field_name == "source_citations":
        value = [citation.model_dump() for citation in block.source_citations]
    return (
        {
            "slot_id": slot.slot_id,
            "block_id": block.block_id,
            "block_kind": block.kind.value,
            "field": field_name,
            "content": value,
        },
        f"block:{block.block_id}:{field_name}",
    )


def _payload_for_block_item(
    slot: TemplateSlot,
    block: PresentationBlock,
    field_name: str | None,
    item_index: int | None,
) -> tuple[dict[str, Any], str]:
    if field_name is None or item_index is None:
        return _payload_for_block(slot, block)
    values = block.content.get(field_name, [])
    item = values[item_index] if isinstance(values, list) and item_index < len(values) else None
    return (
        {
            "slot_id": slot.slot_id,
            "block_id": block.block_id,
            "block_kind": block.kind.value,
            "field": field_name,
            "item_index": item_index,
            "content": item,
        },
        f"block:{block.block_id}:{field_name}[{item_index}]",
    )


def _block_at(blocks: list[PresentationBlock], index: int | None) -> PresentationBlock | None:
    if index is None:
        return blocks[0] if blocks else None
    if 0 <= index < len(blocks):
        return blocks[index]
    return None


def _deck_id_from_title(title: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in title).strip("-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized or "deck"
