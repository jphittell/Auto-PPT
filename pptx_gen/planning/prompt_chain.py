"""Five-step planning orchestration with schema-validated fallbacks."""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path
from typing import Protocol

from pptx_gen.indexing.embedder import SupportsEmbedding
from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.layout.schemas import StyleTokens
from pptx_gen.planning.schemas import (
    DeckBrief,
    DeckTheme,
    DesignRefinement,
    LayoutIntent,
    OutlineItem,
    OutlineSpec,
    PresentationBlock,
    PresentationBlockKind,
    PresentationSpec,
    RetrievalPlan,
    RetrievalPlanItem,
    RetrievalQuery,
    RetrievedChunk,
    SlideArchetype,
    SlidePurpose,
    SlideSpec,
    SourceCitation,
)


class StructuredLLMClient(Protocol):
    """Model-agnostic structured-output boundary for later implementation."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
        """Return schema-valid JSON for the requested contract."""


def collect_deck_brief(
    *,
    user_request: str,
    audience: str,
    goal: str,
    tone: str = "executive",
    slide_count_target: int = 6,
    source_corpus_ids: list[str],
    document_title: str | None = None,
    source_texts: list[str] | None = None,
    llm_client: StructuredLLMClient | None = None,
) -> DeckBrief:
    source_texts = source_texts or []
    source_preview = _source_preview(source_texts)
    if llm_client is not None:
        result = llm_client.generate_json(
            system_prompt=_load_prompt("step0_system.md"),
            user_prompt=_render_prompt(
                "step1_brief.md",
                {
                    "{user_request}": user_request,
                    "{audience}": audience,
                    "{goal}": goal,
                    "{talk_length_minutes}": str(max(5, slide_count_target * 2)),
                    "{style_tokens_summary}": tone,
                    "{source_ids}": ", ".join(source_corpus_ids),
                    "{document_title}": document_title or "",
                    "{source_preview}": source_preview,
                },
            ),
            schema_name="DeckBrief",
        )
        brief = DeckBrief.model_validate(result)
        return _augment_brief(
            brief,
            document_title=document_title,
            source_texts=source_texts,
            user_request=user_request,
            goal=goal,
        )

    brief = DeckBrief(
        audience=audience,
        goal=goal,
        tone=tone,
        slide_count_target=max(3, min(20, slide_count_target)),
        source_corpus_ids=source_corpus_ids,
        questions_for_user=[],
    )
    return _augment_brief(
        brief,
        document_title=document_title,
        source_texts=source_texts,
        user_request=user_request,
        goal=goal,
    )


def generate_outline(
    brief: DeckBrief,
    *,
    llm_client: StructuredLLMClient | None = None,
) -> OutlineSpec:
    if llm_client is not None:
        result = llm_client.generate_json(
            system_prompt=_load_prompt("step0_system.md"),
            user_prompt=_render_prompt(
                "step2_outline.md",
                {
                    "{deck_brief_json}": brief.model_dump_json(indent=2),
                    "{slide_count_target}": str(brief.slide_count_target),
                },
            ),
            schema_name="OutlineSpec",
        )
        return OutlineSpec.model_validate(result)

    takeaways = _outline_takeaways(brief)
    deck_title = str((brief.extensions or {}).get("document_title", brief.goal))
    include_agenda = brief.slide_count_target >= 5
    reserved = 3 if include_agenda else 2
    content_count = max(1, brief.slide_count_target - reserved)
    content_messages = _plan_content_messages(brief, takeaways, content_count)
    overview_message = _overview_message(brief, takeaways)

    outline: list[OutlineItem] = [
        OutlineItem(
            slide_id="s1",
            purpose=SlidePurpose.TITLE,
            headline=_short_headline(deck_title, fallback="Deck Overview"),
            message=_trim_words(brief.goal, 14),
            evidence_queries=[],
            template_key="title.hero",
        )
    ]

    next_index = 2
    if include_agenda:
        outline.append(
            OutlineItem(
                slide_id=f"s{next_index}",
                purpose=SlidePurpose.AGENDA,
                headline="Agenda",
                message="Review goals, evidence, and next actions.",
                evidence_queries=[],
                template_key="agenda.list",
            )
        )
        next_index += 1

    for content_index, message in enumerate(content_messages):
        archetype = SlideArchetype.GENERIC
        headline = _short_headline(message, fallback=f"Slide {next_index}")
        template_key = _recommended_content_template(
            message,
            brief.goal,
            brief.audience,
            str((brief.extensions or {}).get("document_title", "")),
        )
        if content_index == 0 and content_count >= 3:
            archetype = SlideArchetype.EXECUTIVE_OVERVIEW
            headline = "Executive Overview"
            message = overview_message
            template_key = "executive.overview"
            evidence_queries = [
                "hybrid architecture ingestion retrieval planning layout assets deterministic export",
                "executive summary hybrid architecture visually polished pptx decks",
                "design quality strategies template first rule based free form",
            ]
        elif content_index == 1 and _is_pipeline_story(brief):
            archetype = SlideArchetype.ARCHITECTURE_GRID
            headline = "Architecture Components"
            template_key = "architecture.grid"
            evidence_queries = [
                "ingestion retrieval planning layout asset generation validation export",
                "six component pipeline architecture presentation systems",
                "connectors uploads cloud files structured data rag planning layout export",
            ]
        elif template_key == "architecture.grid":
            archetype = SlideArchetype.ARCHITECTURE_GRID
            headline = "Architecture Components"
            evidence_queries = [
                "ingestion retrieval planning layout asset generation validation export",
                "six component pipeline architecture presentation systems",
                "connectors uploads cloud files structured data rag planning layout export",
            ]
        else:
            evidence_queries = _evidence_queries_for_message(message)
        outline.append(
            OutlineItem(
                slide_id=f"s{next_index}",
                purpose=SlidePurpose.CONTENT,
                archetype=archetype,
                headline=headline,
                message=_trim_words(message, 18),
                evidence_queries=evidence_queries,
                template_key=template_key,
            )
        )
        next_index += 1

    outline.append(
        OutlineItem(
            slide_id=f"s{next_index}",
            purpose=SlidePurpose.SUMMARY,
            archetype=SlideArchetype.EXECUTIVE_OVERVIEW,
            headline="Key Takeaways",
            message="Summarize the strongest supported points and actions.",
            evidence_queries=[],
            template_key="content.3col.cards",
        )
    )

    return OutlineSpec(outline=outline, questions_for_user=[])


def build_retrieval_plan(
    brief: DeckBrief,
    outline: OutlineSpec,
    *,
    min_date: date | None = None,
    llm_client: StructuredLLMClient | None = None,
) -> RetrievalPlan:
    if llm_client is not None:
        result = llm_client.generate_json(
            system_prompt=_load_prompt("step0_system.md"),
            user_prompt=_render_prompt(
                "step3_retrieval.md",
                {
                    "{outline_json}": outline.model_dump_json(indent=2),
                    "{source_ids}": ", ".join(brief.source_corpus_ids),
                    "{min_date}": min_date.isoformat() if min_date else "null",
                },
            ),
            schema_name="RetrievalPlan",
        )
        return RetrievalPlan.model_validate(result)

    items: list[RetrievalPlanItem] = []
    for item in outline.outline:
        if item.purpose not in {SlidePurpose.CONTENT, SlidePurpose.APPENDIX}:
            continue
        queries = item.evidence_queries or _evidence_queries_for_message(item.message)
        items.append(
            RetrievalPlanItem(
                slide_id=item.slide_id,
                queries=[
                    RetrievalQuery(query=query, doc_ids=list(brief.source_corpus_ids), min_date=min_date)
                    for query in queries[:5]
                ],
            )
        )
    return RetrievalPlan(retrieval_plan=items, questions_for_user=[])


def execute_retrieval_plan(
    retrieval_plan: RetrievalPlan,
    *,
    vector_store: InMemoryVectorStore,
    embedder: SupportsEmbedding,
    max_results_per_query: int = 2,
    max_chunks_per_slide: int = 5,
) -> dict[str, list[RetrievedChunk]]:
    slide_hits: dict[str, list[RetrievedChunk]] = {}
    for item in retrieval_plan.retrieval_plan:
        seen_chunk_ids: set[str] = set()
        hits: list[RetrievedChunk] = []
        for query in item.queries:
            embedding = embedder.encode([query.query])[0]
            for hit in vector_store.query(query_embedding=embedding, n_results=max_results_per_query):
                if query.doc_ids and hit.source_id not in query.doc_ids:
                    continue
                if hit.chunk_id in seen_chunk_ids:
                    continue
                hits.append(hit)
                seen_chunk_ids.add(hit.chunk_id)
                if len(hits) >= max_chunks_per_slide:
                    break
            if len(hits) >= max_chunks_per_slide:
                break
        slide_hits[item.slide_id] = hits
    return slide_hits


def generate_presentation_spec(
    brief: DeckBrief,
    outline: OutlineSpec,
    retrieved_chunks_by_slide: dict[str, list[RetrievedChunk]],
    *,
    deck_title: str,
    style_tokens: StyleTokens,
    theme_name: str = "Auto PPT",
    language: str = "en-US",
    llm_client: StructuredLLMClient | None = None,
) -> PresentationSpec:
    tone_label = _tone_label(brief.tone)
    if llm_client is not None:
        result = llm_client.generate_json(
            system_prompt=_load_prompt("step0_system.md"),
            user_prompt=_render_prompt(
                "step4_slidespec.md",
                {
                    "{deck_brief_json}": brief.model_dump_json(indent=2),
                    "{outline_json}": outline.model_dump_json(indent=2),
                    "{retrieved_chunks_json}": _serialize_retrieved_chunks(retrieved_chunks_by_slide),
                    "{style_tokens_json}": style_tokens.model_dump_json(indent=2),
                },
            ),
            schema_name="PresentationSpec",
        )
        spec = PresentationSpec.model_validate(result)
        spec = _enforce_authoritative_fields(
            spec,
            brief=brief,
            outline=outline,
            deck_title=deck_title,
            language=language,
            retrieved_chunks_by_slide=retrieved_chunks_by_slide,
            tone_label=tone_label,
        )
        spec = _inject_missing_citations(spec, retrieved_chunks_by_slide, brief)
        return _upgrade_visual_templates(spec, retrieved_chunks_by_slide, brief)

    slides: list[SlideSpec] = []
    summary_citations: list[SourceCitation] = []
    takeaways = list((brief.extensions or {}).get("key_takeaways", []))

    for item in outline.outline:
        slide_chunks = retrieved_chunks_by_slide.get(item.slide_id, [])
        if item.purpose is SlidePurpose.TITLE:
            slides.append(_build_title_slide(item=item, brief=brief, tone_label=tone_label))
            continue

        if item.purpose is SlidePurpose.AGENDA:
            slides.append(_build_agenda_slide(item=item, outline=outline))
            continue

        if item.purpose is SlidePurpose.SUMMARY:
            summary_items = [_trim_words(text, 6) for text in (takeaways or [brief.goal])][:3]
            summary_block_citations = summary_citations[:1] or _citations_from_chunks(slide_chunks)[:1] or _fallback_citation(brief.source_corpus_ids)
            summary_template = item.template_key or "content.3col.cards"
            if summary_template == "content.3col.cards":
                slides.append(
                    SlideSpec(
                        slide_id=item.slide_id,
                        purpose=item.purpose,
                        layout_intent=LayoutIntent(template_key="content.3col.cards", strict_template=True),
                        headline=item.headline,
                        speaker_notes=_speaker_notes(item.message, "Close on supported actions."),
                        blocks=[
                            PresentationBlock(
                                block_id="b1",
                                kind=PresentationBlockKind.CALLOUT,
                                content={"cards": _cards_from_points(summary_items, title_prefix="Takeaway")},
                                source_citations=summary_block_citations,
                            )
                        ],
                    )
                )
                continue
            if summary_template == "executive.overview" or item.archetype is SlideArchetype.EXECUTIVE_OVERVIEW:
                slides.append(
                    _executive_overview_slide(
                        item=item,
                        brief=brief,
                        tone_label=tone_label,
                        slide_chunks=slide_chunks,
                        citations=summary_block_citations,
                        summary_items=summary_items,
                    )
                )
                continue
            if summary_template == "architecture.grid" or item.archetype is SlideArchetype.ARCHITECTURE_GRID:
                slides.append(
                    _architecture_grid_slide(
                        item=item,
                        brief=brief,
                        slide_chunks=slide_chunks,
                        citations=summary_block_citations,
                        summary_items=summary_items,
                    )
                )
                continue
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
                    archetype=item.archetype,
                    layout_intent=LayoutIntent(template_key="content.1col", strict_template=True),
                    headline=item.headline,
                    speaker_notes=_speaker_notes(item.message, "Close on supported actions."),
                    blocks=[
                        PresentationBlock(
                            block_id="b1",
                            kind=PresentationBlockKind.BULLETS,
                            content={"items": summary_items},
                            source_citations=summary_block_citations,
                        ),
                        PresentationBlock(
                            block_id="b2",
                            kind=PresentationBlockKind.CALLOUT,
                            content={"text": _callout_from_chunks(slide_chunks, fallback=brief.goal, tone_label=tone_label)},
                            source_citations=summary_block_citations,
                        ),
                    ],
                )
            )
            continue

        bullets = _bullets_from_chunks(slide_chunks, fallback=item.message)
        citations = _citations_from_chunks(slide_chunks)[:2]
        if citations:
            summary_citations.extend(citations)
        template_key = item.template_key or "content.1col"
        if template_key == "executive.overview" or item.archetype is SlideArchetype.EXECUTIVE_OVERVIEW:
            slides.append(
                _executive_overview_slide(
                    item=item,
                    brief=brief,
                    tone_label=tone_label,
                    slide_chunks=slide_chunks,
                    citations=citations or _fallback_citation(brief.source_corpus_ids),
                    summary_items=bullets,
                )
            )
            continue
        if template_key == "architecture.grid" or item.archetype is SlideArchetype.ARCHITECTURE_GRID:
            slides.append(
                _architecture_grid_slide(
                    item=item,
                    brief=brief,
                    slide_chunks=slide_chunks,
                    citations=citations or _fallback_citation(brief.source_corpus_ids),
                    summary_items=bullets,
                )
            )
            continue
        if template_key == "content.3col.cards":
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
                    archetype=item.archetype,
                    layout_intent=LayoutIntent(template_key=template_key, strict_template=True),
                    headline=item.headline,
                    speaker_notes=_speaker_notes(item.message, "Reference cited source material while presenting."),
                    blocks=[
                        PresentationBlock(
                            block_id="b1",
                            kind=PresentationBlockKind.CALLOUT,
                            content={"cards": _cards_from_points(bullets, title_prefix="Capability")},
                            source_citations=citations or _fallback_citation(brief.source_corpus_ids),
                        )
                    ],
                )
            )
            continue
        if template_key == "kpi.3up":
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
                    archetype=item.archetype,
                    layout_intent=LayoutIntent(template_key=template_key, strict_template=True),
                    headline=item.headline,
                    speaker_notes=_speaker_notes(item.message, "Reference cited source material while presenting."),
                    blocks=[
                        PresentationBlock(
                            block_id=f"b{index + 1}",
                            kind=PresentationBlockKind.TEXT,
                            content={"text": value},
                            source_citations=citations or _fallback_citation(brief.source_corpus_ids),
                        )
                        for index, value in enumerate(_kpi_points_from_bullets(bullets))
                    ],
                )
            )
            continue
        slides.append(
            SlideSpec(
                slide_id=item.slide_id,
                purpose=item.purpose,
                archetype=item.archetype,
                layout_intent=LayoutIntent(template_key=template_key, strict_template=True),
                headline=item.headline,
                speaker_notes=_speaker_notes(item.message, "Reference cited source material while presenting."),
                blocks=[
                    PresentationBlock(
                        block_id="b1",
                        kind=PresentationBlockKind.BULLETS,
                        content={"items": bullets},
                        source_citations=citations or _fallback_citation(brief.source_corpus_ids),
                    ),
                    PresentationBlock(
                        block_id="b2",
                        kind=PresentationBlockKind.CALLOUT,
                        content={"text": _callout_from_chunks(slide_chunks, fallback=item.message, tone_label=tone_label)},
                        source_citations=citations or _fallback_citation(brief.source_corpus_ids),
                    ),
                ],
            )
        )

    spec = PresentationSpec(
        title=deck_title,
        audience=brief.audience,
        language=language,
        theme=DeckTheme(name=theme_name, style_tokens=style_tokens),
        slides=slides,
        questions_for_user=[],
    )
    return _upgrade_visual_templates(spec, retrieved_chunks_by_slide, brief)


def revise_for_design_quality(
    spec: PresentationSpec,
    *,
    qa_report_json: str,
    render_artifact_path: str | Path | None,
    llm_client: StructuredLLMClient | None = None,
    user_brief: str | None = None,
    enabled: bool = False,
) -> tuple[PresentationSpec, str, bool]:
    """Run one optional design-only refinement round and preserve citations."""

    if not enabled:
        return spec, "refinement disabled", False
    if render_artifact_path is None or not Path(render_artifact_path).exists():
        return spec, "refinement skipped: render artifact unavailable", False
    if llm_client is None:
        return spec, "refinement skipped: no llm client configured", False

    result = llm_client.generate_json(
        system_prompt=_load_prompt("step0_system.md"),
        user_prompt=_render_prompt(
            "step5_design_revise.md",
            {
                "{presentation_spec_json}": spec.model_dump_json(indent=2),
                "{style_tokens_json}": spec.theme.style_tokens.model_dump_json(indent=2),
                "{qa_report_json}": qa_report_json,
                "{render_artifact_path}": str(render_artifact_path),
                "{user_brief}": user_brief or "",
            },
        ),
        schema_name="DesignRefinement",
    )
    refinement = DesignRefinement.model_validate(result)
    revised = refinement.presentation_spec
    _ensure_citations_preserved(spec, revised)
    return revised, "; ".join(refinement.rationale) or "refinement applied", refinement.applied


def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / name
    return path.read_text(encoding="utf-8")


def _render_prompt(name: str, replacements: dict[str, str]) -> str:
    prompt = _load_prompt(name)
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


def _inject_missing_citations(
    spec: PresentationSpec,
    retrieved_chunks_by_slide: dict[str, list[RetrievedChunk]],
    brief: DeckBrief,
) -> PresentationSpec:
    """Ensure every factual block on content/summary slides has at least one citation."""
    citation_required_purposes = {SlidePurpose.CONTENT, SlidePurpose.SUMMARY, SlidePurpose.APPENDIX}
    citation_required_kinds = {
        PresentationBlockKind.TEXT,
        PresentationBlockKind.BULLETS,
        PresentationBlockKind.TABLE,
        PresentationBlockKind.CHART,
        PresentationBlockKind.QUOTE,
        PresentationBlockKind.CALLOUT,
        PresentationBlockKind.KPI_CARDS,
    }
    # Build a global fallback citation from any retrieved chunk or brief source IDs
    global_fallback: list[SourceCitation] = []
    for chunks in retrieved_chunks_by_slide.values():
        if chunks:
            global_fallback = _citations_from_chunks(chunks[:1])
            break
    if not global_fallback:
        global_fallback = _fallback_citation(brief.source_corpus_ids)

    updated_slides = []
    for slide in spec.slides:
        if slide.purpose not in citation_required_purposes:
            updated_slides.append(slide)
            continue
        slide_fallback = (
            _citations_from_chunks(retrieved_chunks_by_slide.get(slide.slide_id, [])[:1])
            or global_fallback
        )
        updated_blocks = []
        for block in slide.blocks:
            if block.kind in citation_required_kinds and not block.source_citations:
                block = block.model_copy(update={"source_citations": list(slide_fallback)})
            updated_blocks.append(block)
        updated_slides.append(slide.model_copy(update={"blocks": updated_blocks}))
    return spec.model_copy(update={"slides": updated_slides})


_PLACEHOLDER_HEADLINE_RE = re.compile(r"^slide\s+\d+$", re.IGNORECASE)
_PLACEHOLDER_TITLES = {"generated presentation", "untitled", "slide title", "untitled presentation"}


def _enforce_authoritative_fields(
    spec: PresentationSpec,
    *,
    brief: DeckBrief,
    outline: OutlineSpec,
    deck_title: str,
    language: str,
    retrieved_chunks_by_slide: dict[str, list[RetrievedChunk]],
    tone_label: str,
) -> PresentationSpec:
    """Override LLM-generated fields that must match authoritative pipeline values."""
    # Build headline lookup — only exclude pure numeric placeholders like "Slide 1"
    outline_headlines: dict[str, str] = {
        item.slide_id: item.headline
        for item in outline.outline
        if item.headline and not _PLACEHOLDER_HEADLINE_RE.fullmatch(item.headline.strip())
    }
    outline_messages: dict[str, str] = {
        item.slide_id: item.message
        for item in outline.outline
        if item.message
    }
    outline_items: dict[str, OutlineItem] = {item.slide_id: item for item in outline.outline}
    slides = []
    for slide in spec.slides:
        outline_item = outline_items.get(slide.slide_id)
        if outline_item is not None:
            slide = slide.model_copy(
                update={
                    "purpose": outline_item.purpose,
                    "archetype": outline_item.archetype,
                    "layout_intent": LayoutIntent(
                        template_key=outline_item.template_key or slide.layout_intent.template_key,
                        strict_template=True,
                    ),
                }
            )
        outline_headline = outline_headlines.get(slide.slide_id, "")
        current_headline = slide.headline or ""
        is_placeholder = (
            not current_headline
            or bool(_PLACEHOLDER_HEADLINE_RE.fullmatch(current_headline.strip()))
            or current_headline.strip().lower() in _PLACEHOLDER_TITLES
        )
        if outline_headline and is_placeholder:
            slide = slide.model_copy(update={"headline": outline_headline})

        slide_chunks = retrieved_chunks_by_slide.get(slide.slide_id, [])
        if outline_item is not None and slide.purpose is SlidePurpose.TITLE:
            slides.append(_build_title_slide(item=outline_item, brief=brief, tone_label=tone_label))
            continue
        if outline_item is not None and slide.purpose is SlidePurpose.AGENDA:
            slides.append(_build_agenda_slide(item=outline_item, outline=outline))
            continue
        if outline_item is not None and (
            outline_item.template_key == "executive.overview"
            or (
                outline_item.archetype is SlideArchetype.EXECUTIVE_OVERVIEW
                and outline_item.template_key != "content.3col.cards"
            )
        ):
            slides.append(
                _executive_overview_slide(
                    item=outline_item,
                    brief=brief,
                    tone_label=tone_label,
                    slide_chunks=slide_chunks,
                    citations=_slide_citations(slide, slide_chunks, brief),
                    summary_items=_slide_summary_points(slide, slide_chunks, fallback=outline_item.message, limit=6),
                )
            )
            continue
        if outline_item is not None and (
            outline_item.template_key == "architecture.grid" or outline_item.archetype is SlideArchetype.ARCHITECTURE_GRID
        ):
            slides.append(
                _architecture_grid_slide(
                    item=outline_item,
                    brief=brief,
                    slide_chunks=slide_chunks,
                    citations=_slide_citations(slide, slide_chunks, brief),
                    summary_items=_slide_summary_points(slide, slide_chunks, fallback=outline_item.message, limit=6),
                )
            )
            continue
        if outline_item is not None and outline_item.template_key == "content.3col.cards" and not _slide_has_cards(slide):
            cards = _cards_for_slide(slide, slide_chunks, title_prefix="Capability", desired_count=3) or _cards_from_points(
                _slide_summary_points(slide, slide_chunks, fallback=outline_item.message, limit=3),
                title_prefix="Capability",
            )
            slide = slide.model_copy(
                update={
                    "layout_intent": LayoutIntent(template_key="content.3col.cards", strict_template=True),
                    "blocks": [
                        PresentationBlock(
                            block_id=slide.blocks[0].block_id if slide.blocks else "b1",
                            kind=PresentationBlockKind.CALLOUT,
                            content={"cards": cards},
                            source_citations=_slide_citations(slide, slide_chunks, brief),
                        )
                    ],
                }
            )

        # Replace empty/degenerate block content with content from the outline message
        fallback_message = outline_messages.get(slide.slide_id, "")
        updated_blocks = []
        for block in slide.blocks:
            if block.kind is PresentationBlockKind.BULLETS:
                content = block.content or {}
                items = content.get("items") if isinstance(content, dict) else None
                if isinstance(items, list):
                    clean = [str(i).strip() for i in items if str(i).strip()]
                    if not clean and fallback_message:
                        clean = [_trim_words(fallback_message, 12)]
                    if clean != items:
                        block = block.model_copy(update={"content": {"items": clean or [fallback_message or "See source"]}})
            elif block.kind is PresentationBlockKind.TEXT:
                content = block.content or {}
                text = content.get("text", "") if isinstance(content, dict) else ""
                parsed_cards = _parse_serialized_card_text(str(text)) if isinstance(text, str) else None
                if parsed_cards:
                    block = block.model_copy(
                        update={
                            "kind": PresentationBlockKind.CALLOUT,
                            "content": {"cards": _normalize_card_records(parsed_cards, title_prefix="Capability", desired_count=3)},
                        }
                    )
                    slide = slide.model_copy(update={"layout_intent": LayoutIntent(template_key="content.3col.cards", strict_template=True)})
                if not str(text).strip() and fallback_message:
                    block = block.model_copy(update={"content": {"text": _trim_words(fallback_message, 12)}})
            elif block.kind is PresentationBlockKind.TABLE:
                content = block.content or {}
                if isinstance(content, dict):
                    cols = content.get("columns", [])
                    rows = content.get("rows", [])
                    is_degenerate = (
                        len(cols) <= 1
                        or not rows
                        or all(not any(str(cell).strip() for cell in row) for row in rows)
                    )
                    if is_degenerate and fallback_message:
                        # Demote to bullets rather than show an empty table
                        block = block.model_copy(update={
                            "kind": PresentationBlockKind.BULLETS,
                            "content": {"items": [_trim_words(fallback_message, 12)]},
                        })
                        slide = slide.model_copy(update={"layout_intent": LayoutIntent(template_key="content.1col", strict_template=True)})
            updated_blocks.append(block)
        if updated_blocks != list(slide.blocks):
            slide = slide.model_copy(update={"blocks": updated_blocks})
        slides.append(slide)
    return spec.model_copy(update={
        "title": deck_title,
        "audience": brief.audience,
        "language": language,
        "slides": slides,
    })


def _ensure_citations_preserved(original: PresentationSpec, revised: PresentationSpec) -> None:
    original_citations = {
        (slide.slide_id, block.block_id): [citation.model_dump() for citation in block.source_citations]
        for slide in original.slides
        for block in slide.blocks
    }
    revised_citations = {
        (slide.slide_id, block.block_id): [citation.model_dump() for citation in block.source_citations]
        for slide in revised.slides
        for block in slide.blocks
    }

    if original_citations.keys() != revised_citations.keys():
        raise ValueError("design refinement must preserve slide/block identity")

    for key, citations in original_citations.items():
        if citations != revised_citations[key]:
            raise ValueError(f"design refinement must preserve citations for {key[0]}:{key[1]}")


def _derive_takeaways(source_texts: list[str], goal: str) -> list[str]:
    takeaways: list[str] = []
    seen: set[str] = set()
    for text in source_texts:
        for candidate in _candidate_phrases(text):
            normalized = _normalize_phrase(candidate)
            if not normalized or normalized in seen:
                continue
            takeaways.append(candidate)
            seen.add(normalized)
            if len(takeaways) == 6:
                return takeaways
    if not takeaways:
        takeaways = [_trim_words(goal, 8)]
    return takeaways


def _augment_brief(
    brief: DeckBrief,
    *,
    document_title: str | None,
    source_texts: list[str],
    user_request: str,
    goal: str,
) -> DeckBrief:
    takeaways = _derive_takeaways(source_texts, goal)
    thesis = _trim_words(document_title or goal or user_request, 12)
    extensions = dict(brief.extensions or {})
    extensions.setdefault("document_title", document_title or "Generated Presentation")
    extensions.setdefault("one_sentence_thesis", thesis)
    extensions.setdefault("key_takeaways", takeaways)
    extensions.setdefault("user_request", user_request)
    extensions.setdefault("deck_archetype", _infer_deck_archetype(document_title, goal, user_request, source_texts))
    extensions.setdefault("audience_focus", _audience_focus_label(brief.audience))
    extensions.setdefault("source_preview", _source_preview(source_texts))
    return brief.model_copy(update={"extensions": extensions})


def _infer_deck_archetype(
    document_title: str | None,
    goal: str,
    user_request: str,
    source_texts: list[str],
) -> str:
    haystack = " ".join([document_title or "", goal, user_request, *source_texts[:5]]).lower()
    if any(term in haystack for term in ("release notes", "known issues", "upgrade considerations", "readiness")):
        return "release_readiness"
    if any(term in haystack for term in ("options analysis", "option 1", "option 2", "pros", "cons")):
        return "options_analysis"
    if any(term in haystack for term in ("positions vs", "versus", "decision guide", "when to choose")):
        return "decision_guide"
    return "executive_summary"


def _source_preview(source_texts: list[str]) -> str:
    """Return a representative excerpt of actual source content for LLM context."""
    chunks = [text.strip() for text in source_texts if text.strip()]
    if not chunks:
        return ""
    parts: list[str] = []
    total = 0
    limit = 2500
    for chunk in chunks[:12]:
        if total >= limit:
            break
        remaining = limit - total
        if len(chunk) > remaining:
            if remaining > 120:
                parts.append(chunk[:remaining].rsplit(" ", 1)[0] + "…")
            break
        parts.append(chunk)
        total += len(chunk) + 2  # +2 for separator
    return "\n\n".join(parts)


def _expand_content_messages(takeaways: list[str], goal: str, count: int) -> list[str]:
    base = takeaways or [_trim_words(goal, 10)]
    messages: list[str] = []
    for index in range(count):
        source = base[index % len(base)]
        if index < len(base):
            messages.append(source)
        else:
            suffix = "evidence" if index % 2 == 0 else "implications"
            messages.append(f"{source} {suffix}")
    return messages


def _outline_takeaways(brief: DeckBrief) -> list[str]:
    raw_takeaways = list((brief.extensions or {}).get("key_takeaways", []))
    title_norm = _normalize_phrase(str((brief.extensions or {}).get("document_title", brief.goal)))
    goal_norm = _normalize_phrase(brief.goal)
    filtered: list[str] = []
    seen: set[str] = set()
    for takeaway in raw_takeaways:
        trimmed = str(takeaway).strip(" -\t")
        normalized = _normalize_phrase(trimmed)
        if not trimmed or not normalized or normalized in seen:
            continue
        if normalized == title_norm or normalized == goal_norm:
            continue
        if trimmed.lower().startswith("how ai presentation systems ingest data"):
            continue
        if len(trimmed.split()) < 5:
            continue
        filtered.append(trimmed.rstrip(".,;:"))
        seen.add(normalized)
    return filtered


def _plan_content_messages(brief: DeckBrief, takeaways: list[str], count: int) -> list[str]:
    if _is_pipeline_story(brief):
        seeded = [
            "Hybrid architecture: ingestion, retrieval, planning, layout, assets, and deterministic export",
            "Architecture components: ingestion, retrieval, planning, layout, assets, QA, and export",
            "Design quality strategies: template-first, rule-based layout, and free-form constraints",
            "Implementation implications: connectors, cloud files, structured data, and reproducible PPTX export",
        ]
        messages: list[str] = []
        seen: set[str] = set()
        for candidate in [*seeded, *takeaways]:
            normalized = _normalize_phrase(candidate)
            if not normalized or normalized in seen:
                continue
            messages.append(candidate)
            seen.add(normalized)
            if len(messages) >= count:
                return messages
        return messages
    return _expand_content_messages(takeaways, brief.goal, count)


def _overview_message(brief: DeckBrief, takeaways: list[str]) -> str:
    if _is_pipeline_story(brief):
        return "Hybrid architecture: ingestion, retrieval, planning, layout, assets, and deterministic export"
    thesis = str((brief.extensions or {}).get("one_sentence_thesis", brief.goal))
    supporting = takeaways[0] if takeaways else brief.goal
    return _trim_words(f"{thesis}. {supporting}.", 18)


def _is_pipeline_story(brief: DeckBrief) -> bool:
    haystack = " ".join(
        [
            brief.goal,
            str((brief.extensions or {}).get("document_title", "")),
            str((brief.extensions or {}).get("source_preview", "")),
        ]
    ).lower()
    required = ("ingestion", "retrieval", "layout")
    return all(term in haystack for term in required)


def _recommended_content_template(message: str, goal: str, audience: str = "", document_title: str = "") -> str:
    haystack = f"{message} {goal} {audience} {document_title}".lower()
    if any(term in haystack for term in ("metric", "kpi", "score", "rate", "roi", "growth", "performance")):
        return "kpi.3up"
    if any(
        term in haystack
        for term in (
            "architecture",
            "pipeline",
            "component",
            "ingestion",
            "retrieval",
            "layout",
            "asset",
            "export",
            "renderer",
        )
    ):
        return "architecture.grid"
    if any(
        term in haystack
        for term in (
            "capability",
            "workstream",
            "overview",
            "landscape",
            "tools",
        )
    ):
        return "content.3col.cards"
    if any(
        term in haystack
        for term in (
            "strategy",
            "strategies",
            "benefit",
            "benefits",
            "principle",
            "principles",
            "quality",
            "practice",
            "delivery",
        )
    ):
        return "content.3col.cards"
    return "content.1col"


def _cards_from_points(items: list[str], *, title_prefix: str) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for index, item in enumerate(items[:3], start=1):
        title = _card_title_from_point(item, fallback=f"{title_prefix} {index}")
        cards.append({"title": title, "text": _trim_words(item, 6)})
    while len(cards) < 3:
        index = len(cards) + 1
        cards.append({"title": f"{title_prefix} {index}", "text": f"Detail {index}"})
    return cards


def _build_title_slide(*, item: OutlineItem, brief: DeckBrief, tone_label: str) -> SlideSpec:
    return SlideSpec(
        slide_id=item.slide_id,
        purpose=item.purpose,
        layout_intent=LayoutIntent(template_key="title.hero", strict_template=True),
        headline=item.headline,
        speaker_notes=_speaker_notes(item.message, brief.goal),
        blocks=[
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.TEXT,
                content={
                    "subtitle": _title_subtitle(brief),
                    "presenter": _trim_words(brief.audience, 6),
                    "date": date.today().isoformat(),
                    "tagline": tone_label,
                },
            )
        ],
    )


def _build_agenda_slide(*, item: OutlineItem, outline: OutlineSpec) -> SlideSpec:
    agenda_items = [
        _trim_words(outline_item.headline, 4)
        for outline_item in outline.outline
        if outline_item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}
    ][:4]
    return SlideSpec(
        slide_id=item.slide_id,
        purpose=item.purpose,
        layout_intent=LayoutIntent(template_key="agenda.list", strict_template=True),
        headline=item.headline,
        speaker_notes=_speaker_notes(item.message, "Move quickly through the deck structure."),
        blocks=[
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.BULLETS,
                content={"items": agenda_items or ["Overview", "Evidence", "Actions"]},
            )
        ],
    )


def _title_subtitle(brief: DeckBrief) -> str:
    audience_focus = str((brief.extensions or {}).get("audience_focus") or _audience_focus_label(brief.audience)).strip()
    if audience_focus:
        return _trim_words(f"{audience_focus} | {brief.goal}", 12)
    return _trim_words(brief.goal, 10)


def _audience_focus_label(audience: str) -> str:
    normalized = audience.lower()
    if "oracle" in normalized and "consult" in normalized:
        return "implementation lens for Oracle consulting teams"
    if "consult" in normalized:
        return "implementation lens for consulting teams"
    if "investor" in normalized:
        return "investment lens for external stakeholders"
    if "board" in normalized:
        return "decision lens for board stakeholders"
    return f"framing for {audience}"


def _card_title_from_point(item: str, *, fallback: str) -> str:
    words = [word.strip(",.:;") for word in str(item).split() if word]
    title = " ".join(words[:3]).strip()
    return title or fallback


def _kpi_points_from_bullets(items: list[str]) -> list[str]:
    values = [_trim_words(item, 4) for item in items[:3]]
    while len(values) < 3:
        values.append(f"Insight {len(values) + 1}")
    return values


def _executive_overview_slide(
    *,
    item: OutlineItem,
    brief: DeckBrief,
    tone_label: str,
    slide_chunks: list[RetrievedChunk],
    citations: list[SourceCitation],
    summary_items: list[str],
) -> SlideSpec:
    summary_text = _overview_summary_text(item, brief, slide_chunks)
    cards = _overview_cards(slide_chunks, summary_items)
    footer_text = f"{len(cards)} components | {_footer_metric_label(slide_chunks, brief)}"
    return SlideSpec(
        slide_id=item.slide_id,
        purpose=item.purpose,
        archetype=SlideArchetype.EXECUTIVE_OVERVIEW,
        layout_intent=LayoutIntent(template_key="executive.overview", strict_template=True),
        headline=item.headline,
        speaker_notes=_speaker_notes(item.message, "Lead with the architecture and why it matters."),
        blocks=[
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.TEXT,
                content={"text": summary_text},
                source_citations=citations,
            ),
            PresentationBlock(
                block_id="b2",
                kind=PresentationBlockKind.CALLOUT,
                content={"text": _specialist_callout(brief, slide_chunks, fallback=item.message, tone_label=tone_label)},
                source_citations=citations,
            ),
            PresentationBlock(
                block_id="b3",
                kind=PresentationBlockKind.CALLOUT,
                content={"cards": cards},
                source_citations=citations,
            ),
            PresentationBlock(
                block_id="b4",
                kind=PresentationBlockKind.TEXT,
                content={"text": footer_text},
                source_citations=citations,
            ),
        ],
    )


def _architecture_grid_slide(
    *,
    item: OutlineItem,
    brief: DeckBrief,
    slide_chunks: list[RetrievedChunk],
    citations: list[SourceCitation],
    summary_items: list[str],
) -> SlideSpec:
    summary_text = _architecture_summary_text(item, brief, slide_chunks)
    cards = _architecture_cards(slide_chunks, summary_items)
    footer_text = f"{len(cards)} components | {_footer_metric_label(slide_chunks, brief)}"
    return SlideSpec(
        slide_id=item.slide_id,
        purpose=item.purpose,
        archetype=SlideArchetype.ARCHITECTURE_GRID,
        layout_intent=LayoutIntent(template_key="architecture.grid", strict_template=True),
        headline=item.headline,
        speaker_notes=_speaker_notes(item.message, "Walk through the components and how they connect."),
        blocks=[
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.TEXT,
                content={"text": summary_text},
                source_citations=citations,
            ),
            PresentationBlock(
                block_id="b2",
                kind=PresentationBlockKind.CALLOUT,
                content={"cards": cards},
                source_citations=citations,
            ),
            PresentationBlock(
                block_id="b3",
                kind=PresentationBlockKind.TEXT,
                content={"text": footer_text},
                source_citations=citations,
            ),
        ],
    )


def _overview_summary_text(item: OutlineItem, brief: DeckBrief, slide_chunks: list[RetrievedChunk]) -> str:
    phrases = []
    for chunk in slide_chunks:
        phrases.extend(_candidate_phrases(chunk.text))
        if len(phrases) >= 2:
            break
    if phrases:
        return _trim_words(f"{' '.join(phrases[:2])}. {_audience_summary_suffix(brief)}", 10)
    thesis = str((brief.extensions or {}).get("one_sentence_thesis", brief.goal))
    return _trim_words(f"{thesis}. {_audience_summary_suffix(brief)}", 10)


def _overview_cards(slide_chunks: list[RetrievedChunk], summary_items: list[str]) -> list[dict[str, str]]:
    semantic_cards = _semantic_cards_from_chunks(slide_chunks, desired_count=6, mode="overview")
    if semantic_cards:
        return semantic_cards
    points = list(summary_items)
    for chunk in slide_chunks:
        for phrase in _candidate_phrases(chunk.text):
            if phrase not in points:
                points.append(phrase)
            if len(points) >= 6:
                return _compact_cards(points[:6], title_prefix="Capability")
    return _compact_cards(points[:6], title_prefix="Capability")


def _architecture_summary_text(item: OutlineItem, brief: DeckBrief, slide_chunks: list[RetrievedChunk]) -> str:
    phrases = []
    for chunk in slide_chunks:
        phrases.extend(_candidate_phrases(chunk.text))
        if len(phrases) >= 1:
            break
    if phrases:
        return _trim_words(f"{phrases[0]} supports {_audience_summary_suffix(brief)}", 10)
    thesis = str((brief.extensions or {}).get("one_sentence_thesis", brief.goal))
    return _trim_words(f"{thesis}. {_audience_summary_suffix(brief)}", 10)


def _architecture_cards(slide_chunks: list[RetrievedChunk], summary_items: list[str]) -> list[dict[str, str]]:
    semantic_cards = _semantic_cards_from_chunks(slide_chunks, desired_count=6, mode="architecture")
    if semantic_cards:
        return semantic_cards
    components: list[str] = []
    for chunk in slide_chunks:
        for phrase in _candidate_phrases(chunk.text):
            if phrase not in components:
                components.append(phrase)
            if len(components) >= 6:
                return _compact_cards(components[:6], title_prefix="Component")
    for item in summary_items:
        if item not in components:
            components.append(item)
        if len(components) >= 6:
            break
    return _compact_cards(components[:6], title_prefix="Component")


def _audience_summary_suffix(brief: DeckBrief) -> str:
    normalized = brief.audience.lower()
    if "oracle" in normalized and "consult" in normalized:
        return "Oracle consulting delivery."
    if "consult" in normalized:
        return "Consulting delivery."
    return _trim_words(brief.goal, 3)


def _specialist_callout(
    brief: DeckBrief,
    slide_chunks: list[RetrievedChunk],
    *,
    fallback: str,
    tone_label: str,
) -> str:
    normalized = brief.audience.lower()
    if "oracle" in normalized and "consult" in normalized:
        return f"Oracle consulting lens | {tone_label}"
    if "consult" in normalized:
        return f"Consulting lens | {tone_label}"
    for chunk in slide_chunks:
        for candidate in _candidate_phrases(chunk.text):
            if _normalize_phrase(candidate) != _normalize_phrase(fallback):
                return f"{_trim_words(candidate, 2)} | {tone_label}"
    return f"Supported evidence | {tone_label}"


def _footer_metric_label(slide_chunks: list[RetrievedChunk], brief: DeckBrief) -> str:
    joined = " ".join(chunk.text.lower() for chunk in slide_chunks)
    if "oracle" in brief.audience.lower() and "consult" in brief.audience.lower():
        return "governance"
    if "vector" in joined or "retrieval" in joined:
        return "grounded retrieval"
    if "constraint" in joined or "layout" in joined:
        return "layout controls"
    return "pipeline coverage"


def _compact_cards(items: list[str], *, title_prefix: str, desired_count: int = 6) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for index, item in enumerate(items[:desired_count], start=1):
        words = [word.strip(",.:;") for word in str(item).split() if word]
        title = " ".join(words[:2]).strip() or f"{title_prefix} {index}"
        cards.append({"title": title, "text": _trim_words(item, 2)})
    while len(cards) < desired_count:
        index = len(cards) + 1
        cards.append({"title": f"{title_prefix} {index}", "text": f"Detail {index}"})
    return cards


def _upgrade_visual_templates(
    spec: PresentationSpec,
    retrieved_chunks_by_slide: dict[str, list[RetrievedChunk]],
    brief: DeckBrief,
) -> PresentationSpec:
    updated_slides: list[SlideSpec] = []
    changed = False

    for slide in spec.slides:
        upgraded = _maybe_upgrade_slide_to_table(slide, retrieved_chunks_by_slide.get(slide.slide_id, []))
        upgraded = _maybe_upgrade_slide_to_cards(upgraded, retrieved_chunks_by_slide.get(slide.slide_id, []), brief)
        if upgraded is not slide:
            changed = True
        updated_slides.append(upgraded)

    if not changed:
        return spec
    return PresentationSpec.model_validate(spec.model_copy(update={"slides": updated_slides}).model_dump())


def _maybe_upgrade_slide_to_table(slide: SlideSpec, chunks: list[RetrievedChunk]) -> SlideSpec:
    if slide.purpose not in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}:
        return slide
    if any(block.kind in {PresentationBlockKind.IMAGE, PresentationBlockKind.TABLE, PresentationBlockKind.CHART, PresentationBlockKind.KPI_CARDS} for block in slide.blocks):
        return slide

    trigger_text = " ".join([slide.headline, slide.speaker_notes, *[chunk.text for chunk in chunks]]).lower()
    if not any(term in trigger_text for term in ("option", "compare", "comparison", "approach", "tradeoff", "pros", "cons", "criteria")):
        return slide

    table_content = _extract_comparison_table(chunks)
    if table_content is None:
        return slide

    citations = []
    for block in slide.blocks:
        citations.extend(block.source_citations)
    if not citations:
        citations = _citations_from_chunks(chunks)[:2]
    if not citations:
        return slide

    table_block = PresentationBlock(
        block_id=slide.blocks[0].block_id,
        kind=PresentationBlockKind.TABLE,
        content=table_content,
        source_citations=citations,
    )
    return slide.model_copy(
        update={
            "layout_intent": LayoutIntent(template_key="table.full", strict_template=True),
            "blocks": [table_block],
        }
    )


def _maybe_upgrade_slide_to_cards(slide: SlideSpec, chunks: list[RetrievedChunk], brief: DeckBrief) -> SlideSpec:
    if slide.purpose not in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}:
        return slide
    if slide.layout_intent.template_key in {"executive.overview", "architecture.grid", "table.full", "chart.full"}:
        return slide

    serialized_cards = _cards_for_slide(slide, chunks, title_prefix="Capability", desired_count=3)
    trigger_text = " ".join([slide.headline, slide.speaker_notes, *[chunk.text for chunk in chunks]]).lower()
    should_upgrade = (
        _slide_contains_serialized_cards(slide)
        or any(
            term in trigger_text
            for term in ("strategy", "benefit", "benefits", "quality", "practice", "principle", "landscape", "tool")
        )
    )
    if not should_upgrade or not serialized_cards:
        return slide

    citations = _slide_citations(slide, chunks, brief)
    card_block = PresentationBlock(
        block_id=slide.blocks[0].block_id,
        kind=PresentationBlockKind.CALLOUT,
        content={"cards": serialized_cards},
        source_citations=citations,
    )
    return slide.model_copy(
        update={
            "layout_intent": LayoutIntent(template_key="content.3col.cards", strict_template=True),
            "blocks": [card_block],
        }
    )


def _slide_citations(
    slide: SlideSpec,
    chunks: list[RetrievedChunk],
    brief: DeckBrief,
) -> list[SourceCitation]:
    citations: list[SourceCitation] = []
    for block in slide.blocks:
        citations.extend(block.source_citations)
    return citations or _citations_from_chunks(chunks)[:2] or _fallback_citation(brief.source_corpus_ids)


def _slide_summary_points(
    slide: SlideSpec,
    chunks: list[RetrievedChunk],
    *,
    fallback: str,
    limit: int,
) -> list[str]:
    points: list[str] = []
    seen: set[str] = set()
    for block in slide.blocks:
        for line in _block_lines(block):
            normalized = _normalize_phrase(line)
            if not normalized or normalized in seen:
                continue
            points.append(line)
            seen.add(normalized)
            if len(points) >= limit:
                return points
    for chunk in chunks:
        for candidate in _candidate_phrases(chunk.text):
            normalized = _normalize_phrase(candidate)
            if not normalized or normalized in seen:
                continue
            points.append(candidate)
            seen.add(normalized)
            if len(points) >= limit:
                return points
    if not points and fallback:
        points = _bullets_from_chunks([], fallback=fallback)
    return points[:limit]


def _slide_has_cards(slide: SlideSpec) -> bool:
    for block in slide.blocks:
        cards = block.content.get("cards") if isinstance(block.content, dict) else None
        if isinstance(cards, list) and cards:
            return True
    return False


def _slide_contains_serialized_cards(slide: SlideSpec) -> bool:
    for block in slide.blocks:
        if block.kind is not PresentationBlockKind.TEXT:
            continue
        content = block.content if isinstance(block.content, dict) else {}
        text = content.get("text")
        if isinstance(text, str) and _parse_serialized_card_text(text):
            return True
    return False


def _cards_for_slide(
    slide: SlideSpec,
    chunks: list[RetrievedChunk],
    *,
    title_prefix: str,
    desired_count: int,
) -> list[dict[str, str]]:
    trigger_text = " ".join([slide.headline, slide.speaker_notes, *[chunk.text for chunk in chunks]]).lower()
    semantic_mode = "strategy" if any(
        term in trigger_text for term in ("strategy", "quality", "benefit", "benefits", "principle", "practice")
    ) else "overview" if any(
        term in trigger_text for term in ("tool", "landscape", "overview", "architecture", "pipeline", "component")
    ) else None
    if semantic_mode:
        semantic_cards = _semantic_cards_from_chunks(chunks, desired_count=desired_count, mode=semantic_mode)
        if semantic_cards:
            return semantic_cards

    for block in slide.blocks:
        if not isinstance(block.content, dict):
            continue
        cards = block.content.get("cards")
        if isinstance(cards, list) and cards:
            return _normalize_card_records(cards, title_prefix=title_prefix, desired_count=desired_count)
        text = block.content.get("text")
        if isinstance(text, str):
            parsed = _parse_serialized_card_text(text)
            if parsed:
                return _normalize_card_records(parsed, title_prefix=title_prefix, desired_count=desired_count)
        items = block.content.get("items")
        if isinstance(items, list) and items:
            return _compact_cards([str(item) for item in items], title_prefix=title_prefix, desired_count=desired_count)

    phrases: list[str] = []
    for chunk in chunks:
        for candidate in _candidate_phrases(chunk.text):
            phrases.append(candidate)
            if len(phrases) >= desired_count:
                return _compact_cards(phrases, title_prefix=title_prefix, desired_count=desired_count)
    return _compact_cards(phrases[:desired_count], title_prefix=title_prefix, desired_count=desired_count) if phrases else []


def _normalize_card_records(
    records: list[object],
    *,
    title_prefix: str,
    desired_count: int,
) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for index, record in enumerate(records[:desired_count], start=1):
        if isinstance(record, dict):
            title = str(record.get("title") or record.get("label") or f"{title_prefix} {index}").strip()
            text_parts = [str(record.get(key)).strip() for key in ("text", "value", "description") if record.get(key)]
            text = _trim_words(" ".join(text_parts) or title, 10)
            cards.append({"title": title, "text": text})
        elif record is not None:
            cards.append({"title": f"{title_prefix} {index}", "text": _trim_words(str(record), 10)})
    while len(cards) < desired_count:
        index = len(cards) + 1
        cards.append({"title": f"{title_prefix} {index}", "text": f"Detail {index}"})
    return cards


def _parse_serialized_card_text(text: str) -> list[dict[str, object]] | None:
    stripped = text.strip()
    if not stripped.startswith("[") or "title" not in stripped:
        return None
    try:
        parsed = ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    if not all(isinstance(item, dict) for item in parsed):
        return None
    return parsed


def _semantic_cards_from_chunks(
    chunks: list[RetrievedChunk],
    *,
    desired_count: int,
    mode: str,
) -> list[dict[str, str]]:
    joined = " ".join(chunk.text for chunk in chunks)
    lower = joined.lower()
    if not lower.strip():
        return []

    if mode == "strategy":
        definitions = [
            (
                ("template-first", "template driven", "template-driven"),
                "Template-First",
                "Fixed layouts.",
            ),
            (
                ("rule-based", "auto-layout", "auto layout", "constraint"),
                "Rule-Based Layout",
                "Constraints and resize.",
            ),
            (
                ("free-form", "free form", "generated from scratch"),
                "Free-Form Generation",
                "Model proposes structure.",
            ),
            (
                ("qa", "validation", "overlap", "contrast"),
                "QA and Validation",
                "Checks catch issues.",
            ),
        ]
    else:
        definitions = [
            (
                ("structured data", "connector", "connectors", "records"),
                "Structured Data Ingestion",
                "Documents and records.",
            ),
            (
                ("document upload", "uploads", "drive", "cloud file", "word/docs", "pdf"),
                "Document and Cloud Inputs",
                "Uploads and cloud files.",
            ),
            (
                ("retrieval", "rag", "vector", "embedding", "vectorization"),
                "RAG-style Retrieval",
                "Source grounding.",
            ),
            (
                ("planning", "outline", "brief", "intent"),
                "Outline-first Planning",
                "Brief and outline.",
            ),
            (
                ("template", "layout", "constraint", "alignment"),
                "Template-driven Layout",
                "Deterministic composition.",
            ),
            (
                ("asset", "chart", "icon", "visual"),
                "Asset Generation",
                "Charts and icons.",
            ),
            (
                ("export", "pptx", "ooxml", "renderer", "render"),
                "Deterministic Export",
                "Editable PPTX output.",
            ),
            (
                ("qa", "validation", "overlap", "consistency"),
                "QA and Validation",
                "Overlap and consistency.",
            ),
        ]

    cards: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for keywords, title, text in definitions:
        if any(keyword in lower for keyword in keywords):
            if title in seen_titles:
                continue
            cards.append({"title": title, "text": _trim_words(text, 3)})
            seen_titles.add(title)
            if len(cards) >= desired_count:
                return cards[:desired_count]
    for _, title, text in definitions:
        if title in seen_titles:
            continue
        cards.append({"title": title, "text": _trim_words(text, 3)})
        seen_titles.add(title)
        if len(cards) >= desired_count:
            return cards[:desired_count]
    return cards[:desired_count]


def _extract_comparison_table(chunks: list[RetrievedChunk]) -> dict[str, list[list[str]] | list[str]] | None:
    current_metric: str | None = None
    option_labels: list[str] = []
    rows: list[list[str]] = []
    metric_to_values: dict[str, dict[str, str]] = {}
    option_pattern = re.compile(r"^Option\s+\d+(?:\s+\(([^)]+)\))?:\s*(.+)$", re.IGNORECASE)

    for chunk in chunks:
        for raw_line in chunk.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            option_match = option_pattern.match(line)
            if option_match and current_metric:
                option_label = option_match.group(1) or f"Option {len(option_labels) + 1}"
                option_label = _trim_words(option_label, 2) or "Option"
                if option_label not in option_labels:
                    option_labels.append(option_label)
                value = _compress_comparison_value(option_match.group(2))
                metric_to_values.setdefault(current_metric, {})[option_label] = value
                continue

            if line.endswith(":"):
                current_metric = None
                continue

            if ":" not in line and len(line.split()) <= 6:
                current_metric = line

    if len(option_labels) < 2 or not metric_to_values:
        return None

    columns = ["Criterion", *option_labels[:3]]
    for metric, values in list(metric_to_values.items())[:4]:
        row = [metric]
        populated = 0
        for option_label in option_labels[:3]:
            cell = values.get(option_label, "")
            if cell:
                populated += 1
            row.append(cell)
        if populated >= 2:
            rows.append(row)

    if len(rows) < 2:
        return None

    word_count = _count_words_in_value({"columns": columns, "rows": rows})
    if word_count > 40:
        return None
    return {"columns": columns, "rows": rows}


def _compress_comparison_value(value: str) -> str:
    lowered = value.lower()
    if "not supported" in lowered or "batch only" in lowered:
        return "Batch only"
    if "event-driven" in lowered and "polling" in lowered:
        return "Event or poll"
    if "event-driven" in lowered:
        return "Real-time"
    if "low to medium" in lowered:
        return "Low-Med"
    if "medium to high" in lowered:
        return "Med-High"
    if "moderate ongoing cost" in lowered or "moderate" in lowered:
        return "Moderate"
    if "lowest initial cost" in lowered or "lowest" in lowered:
        return "Lowest"
    if "low" in lowered and "medium" not in lowered:
        return "Low"
    if "medium" in lowered and "high" not in lowered:
        return "Medium"
    if "high" in lowered:
        return "High"
    return _trim_words(value.replace(".", ""), 2)


def _count_words_in_value(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(re.findall(r"\b\w+\b", value))
    if isinstance(value, list):
        return sum(_count_words_in_value(item) for item in value)
    if isinstance(value, dict):
        return sum(_count_words_in_value(item) for item in value.values())
    return len(re.findall(r"\b\w+\b", str(value)))


def _evidence_queries_for_message(message: str) -> list[str]:
    trimmed = _trim_words(message, 10)
    return [
        trimmed,
        f"{trimmed} evidence",
        f"{trimmed} source data",
    ]


def _short_headline(text: str, *, fallback: str) -> str:
    cleaned = text.replace(":", " ").replace(";", " ")
    words = [word for word in cleaned.split() if word]
    return " ".join(words[:8]) or fallback


def _speaker_notes(primary: str, secondary: str) -> str:
    first = _sentence_case(_trim_words(primary, 18).rstrip("."))
    second = _sentence_case(_trim_words(secondary, 18).rstrip("."))
    return f"{first}. {second}."


def _block_lines(block: PresentationBlock) -> list[str]:
    content = block.content if isinstance(block.content, dict) else {}
    items = content.get("items")
    if isinstance(items, list):
        return [str(item).strip() for item in items if str(item).strip()]
    cards = content.get("cards")
    if isinstance(cards, list):
        lines = []
        for card in cards:
            if isinstance(card, dict):
                title = str(card.get("title") or "").strip()
                text = str(card.get("text") or card.get("description") or card.get("value") or "").strip()
                combined = " ".join(part for part in (title, text) if part).strip()
                if combined:
                    lines.append(combined)
        return lines
    text = content.get("text")
    if isinstance(text, str) and text.strip():
        parsed = _parse_serialized_card_text(text)
        if parsed:
            return [f"{card.get('title', '')} {card.get('value', '')} {card.get('description', '')}".strip() for card in parsed]
        return [text.strip()]
    return []


def _bullets_from_chunks(chunks: list[RetrievedChunk], *, fallback: str) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()
    fallback_norm = _normalize_phrase(fallback)
    for chunk in chunks:
        for candidate in _candidate_phrases(chunk.text):
            normalized = _normalize_phrase(candidate)
            if not normalized or normalized == fallback_norm or normalized in seen:
                continue
            bullets.append(candidate)
            seen.add(normalized)
            if len(bullets) == 3:
                return bullets
    if not bullets:
        # Avoid repeating the headline — produce distinct sub-points from the fallback
        words = [w for w in str(fallback).split() if w]
        if len(words) >= 6:
            mid = len(words) // 2
            bullets.append(" ".join(words[:mid]).rstrip(",:;"))
            bullets.append(" ".join(words[mid:]).rstrip(",:;"))
        else:
            bullets.append(" ".join(words).rstrip(",:;"))
    return bullets[:3]


def _callout_from_chunks(chunks: list[RetrievedChunk], *, fallback: str, tone_label: str) -> str:
    for chunk in chunks:
        for candidate in _candidate_phrases(chunk.text):
            if _normalize_phrase(candidate) != _normalize_phrase(fallback):
                return f"{_trim_words(candidate, 4)} | {tone_label}"
    return f"Supported evidence | {tone_label}"


def _citations_from_chunks(chunks: list[RetrievedChunk]) -> list[SourceCitation]:
    citations: list[SourceCitation] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        key = (chunk.source_id, chunk.locator)
        if key in seen:
            continue
        citations.append(SourceCitation(source_id=chunk.source_id, locator=chunk.locator))
        seen.add(key)
    return citations


def _fallback_citation(source_ids: list[str]) -> list[SourceCitation]:
    source_id = source_ids[0] if source_ids else "source"
    return [SourceCitation(source_id=source_id, locator=f"{source_id}:page1")]


def _serialize_retrieved_chunks(retrieved_chunks_by_slide: dict[str, list[RetrievedChunk]]) -> str:
    payload = {slide_id: [chunk.model_dump() for chunk in chunks] for slide_id, chunks in retrieved_chunks_by_slide.items()}
    import json

    return json.dumps(payload, indent=2)


def _trim_words(text: str, max_words: int) -> str:
    words = [word for word in str(text).replace("\n", " ").split() if word]
    return " ".join(words[:max_words])


def _first_sentence(text: str) -> str:
    return str(text).split(".")[0].replace("\n", " ").strip()


def _sentence_case(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return stripped[0].upper() + stripped[1:]


def _tone_label(tone: str) -> str:
    normalized = tone.strip().lower()
    if normalized in {"bold", "assertive"}:
        return "Bold framing"
    if normalized in {"analytical", "precise"}:
        return "Analytical framing"
    return "Balanced framing"


def _candidate_phrases(text: str) -> list[str]:
    candidates: list[str] = []
    for raw_line in str(text).splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        for part in re.split(r"(?<=[.!?;:])\s+", line):
            cleaned = _clean_candidate_phrase(part)
            if cleaned:
                candidates.append(cleaned)
    return candidates


def _clean_candidate_phrase(text: str) -> str:
    cleaned = str(text).replace("AI- generated", "AI-generated").strip(" -\t")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if "[redacted" in lowered or "contact me" in lowered:
        return ""
    words = cleaned.split()
    if len(words) < 4:
        return ""
    if cleaned.endswith(":"):
        return ""
    # Trim to 12 words to avoid mid-phrase truncation at conjunctions/prepositions
    trimmed = _trim_words(cleaned.rstrip(".;:"), 12)
    # Discard if still ends with a dangling conjunction or preposition
    last_word = trimmed.rsplit(" ", 1)[-1].lower().rstrip(".,;:")
    if last_word in {"and", "or", "but", "the", "a", "an", "of", "in", "on", "at", "by", "for", "with", "to", "let"}:
        # Try dropping just the trailing word
        trimmed = trimmed.rsplit(" ", 1)[0].rstrip(".;:,")
        if len(trimmed.split()) < 4:
            return ""
    return trimmed


def _normalize_phrase(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()
