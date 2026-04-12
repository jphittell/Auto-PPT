"""Five-step planning orchestration with schema-validated fallbacks."""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from pptx_gen.indexing.embedder import SupportsEmbedding
from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.ingestion.schemas import ContentClassification
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
from pptx_gen.renderer.markdown_strip import strip_markdown


class StructuredLLMClient(Protocol):
    """Model-agnostic structured-output boundary for later implementation."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
        """Return schema-valid JSON for the requested contract."""


# Chroma distances in this repo's deterministic tests map to very small scores,
# so keep the gate conservative enough to trim only pathological near-zero hits.
MIN_RETRIEVAL_SCORE = 0.0001
PPTX_BLUEPRINT_VARIETY_TEMPLATES: tuple[str, ...] = (
    "headline.evidence",
    "compare.2col",
    "exec.summary",
    "kpi.big",
    "chart.takeaway",
)
PPTX_BLUEPRINT_GENERIC_ROTATION: tuple[str, ...] = (
    "headline.evidence",
    "compare.2col",
    "exec.summary",
)
PLANNING_LANGUAGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:codex|claude|llm|model)\s+should\b", re.IGNORECASE),
    re.compile(r"\b(?:should implement|must ensure|needs to|todo|fixme|hack|note:)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:upsert|idempotent|sha-256|faiss|qdrant|function signature|"
        r"(?:implement|wire up|hook up|configure)\s+(?:endpoint|api call))\b",
        re.IGNORECASE,
    ),
)
SECTION_LABEL_PREFIX_PATTERN = re.compile(
    r"^(?:(?:business content(?:\s+executive [Oo]verview)?|"
    r"planning notes(?:\s+executive [Oo]verview)?|implementation [Nn]otes|"
    r"technical [Dd]etails|key [Ff]indings|background|introduction|appendix)\s+)+",
    re.IGNORECASE,
)
TITLE_SUBTITLE_GENERIC_PATTERN = re.compile(
    r"^(?:update|overview|summary|introduction|deck overview|presentation|status update)$",
    re.IGNORECASE,
)
TITLE_SUBTITLE_CODELIKE_PATTERN = re.compile(r"(?:[`{}\[\]()_/\\]|\.md\b|\.py\b|::|->|==)")
TITLE_SUBTITLE_CAMELCASE_PATTERN = re.compile(r"\b(?=\w*[a-z])(?=\w*[A-Z])\w+\b")
TITLE_SUBTITLE_HIGH_LEVEL_TERMS = {
    "adoption",
    "approach",
    "capability",
    "capabilities",
    "decision",
    "delivery",
    "direction",
    "framing",
    "impact",
    "leadership",
    "next step",
    "next steps",
    "operating",
    "orchestrator",
    "outcome",
    "outcomes",
    "overview",
    "productivity",
    "quality",
    "roadmap",
    "strategy",
    "tool",
    "tools",
    "workflow",
}
TITLE_SUBTITLE_TECHNICAL_TERMS = {
    "api",
    "chunk",
    "chunks",
    "cli",
    "embedding",
    "embeddings",
    "json",
    "llm",
    "markdown",
    "ooxml",
    "pdf",
    "pptx",
    "prompt",
    "prompts",
    "rag",
    "renderer",
    "schema",
    "schemas",
    "slidespec",
    "token",
    "tokens",
    "uvicorn",
    "validator",
    "vector",
}


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
    source_metadata: dict[str, Any] | None = None,
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
            source_metadata=source_metadata,
            user_request=user_request,
            goal=goal,
        )

    brief = DeckBrief(
        audience=audience,
        goal=goal,
        tone=tone,
        slide_count_target=max(1, min(40, slide_count_target)),
        source_corpus_ids=source_corpus_ids,
        questions_for_user=[],
    )
    return _augment_brief(
        brief,
        document_title=document_title,
        source_texts=source_texts,
        source_metadata=source_metadata,
        user_request=user_request,
        goal=goal,
    )


def generate_outline(
    brief: DeckBrief,
    *,
    llm_client: StructuredLLMClient | None = None,
) -> OutlineSpec:
    pptx_outline = _outline_from_source_blueprint(brief)
    if pptx_outline is not None:
        return pptx_outline

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
    include_closing = brief.slide_count_target >= 5
    reserved = 2
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
            template_key="title.cover",
        )
    ]
    seen_headlines: set[str] = {_normalize_phrase(outline[0].headline)}

    used_templates: dict[str, int] = {}
    next_index = 2
    for content_index, message in enumerate(content_messages):
        archetype = SlideArchetype.GENERIC
        headline = _short_headline(message, fallback=f"Slide {next_index}")
        template_key = _score_content_template(
            message,
            brief.goal,
            brief.audience,
            str((brief.extensions or {}).get("document_title", "")),
            used_templates=used_templates,
        )
        used_templates[template_key] = used_templates.get(template_key, 0) + 1
        if content_index == 0 and content_count >= 3:
            archetype = SlideArchetype.EXECUTIVE_SUMMARY
            headline = "Executive Overview"
            message = overview_message
            template_key = "exec.summary"
            evidence_queries = _evidence_queries_for_message(overview_message)
        else:
            evidence_queries = _evidence_queries_for_message(message)
        normalized_headline = _normalize_phrase(headline)
        if normalized_headline in seen_headlines:
            headline = _short_headline(message, fallback=f"Slide {next_index}")
            normalized_headline = _normalize_phrase(headline)
            if normalized_headline in seen_headlines:
                headline = f"{headline} (continued)"
                normalized_headline = _normalize_phrase(headline)
        seen_headlines.add(normalized_headline)
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

    closing_purpose = SlidePurpose.CLOSING if include_closing else SlidePurpose.SUMMARY
    outline.append(
        OutlineItem(
            slide_id=f"s{next_index}",
            purpose=closing_purpose,
            archetype=SlideArchetype.GENERIC,
            headline="Next Steps" if include_closing else "Key Takeaways",
            message="Summarize the strongest supported points and actions.",
            evidence_queries=[],
            template_key="closing.actions",
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
        if item.purpose not in {SlidePurpose.CONTENT, SlidePurpose.CLOSING}:
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
    max_results_per_query: int = 4,
    max_chunks_per_slide: int = 10,
) -> dict[str, list[RetrievedChunk]]:
    slide_hits: dict[str, list[RetrievedChunk]] = {}
    for item in retrieval_plan.retrieval_plan:
        seen_chunk_ids: set[str] = set()
        hits: list[RetrievedChunk] = []
        for query in item.queries:
            embedding = embedder.encode([query.query])[0]
            for hit in vector_store.query(
                query_embedding=embedding,
                n_results=max_results_per_query,
                exclude_classifications=[
                    ContentClassification.META_PLANNING,
                    ContentClassification.BOILERPLATE,
                ],
            ):
                if query.doc_ids and hit.source_id not in query.doc_ids:
                    continue
                if hit.score is not None and hit.score < MIN_RETRIEVAL_SCORE:
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
        spec = _deduplicate_slide_blocks(spec, retrieved_chunks_by_slide)
        spec = _inject_missing_citations(spec, retrieved_chunks_by_slide, brief)
        return _upgrade_visual_templates(spec, retrieved_chunks_by_slide, brief)

    slides: list[SlideSpec] = []
    summary_citations: list[SourceCitation] = []
    takeaways = list((brief.extensions or {}).get("key_takeaways", []))

    for item in outline.outline:
        slide_chunks = retrieved_chunks_by_slide.get(item.slide_id, [])
        if item.purpose is SlidePurpose.TITLE:
            # Gather all chunks for a richer title subtitle
            all_chunks = [c for cs in retrieved_chunks_by_slide.values() for c in cs]
            slides.append(_build_title_slide(item=item, brief=brief, tone_label=tone_label, chunks=all_chunks[:10]))
            continue

        if item.purpose is SlidePurpose.CLOSING:
            slides.append(_build_closing_slide(item=item, outline=outline))
            continue

        if item.purpose is SlidePurpose.SUMMARY:
            # Derive takeaways from all accumulated chunks if none were provided
            if takeaways:
                summary_items = [_trim_words(text, 20) for text in takeaways][:6]
            else:
                all_chunk_texts = [
                    chunk.text
                    for chunks in retrieved_chunks_by_slide.values()
                    for chunk in chunks
                    if not _is_planning_language(chunk.text)
                ]
                derived = _derive_takeaways(all_chunk_texts, brief.goal)
                summary_items = [_trim_words(text, 20) for text in derived][:6]
            summary_block_citations = summary_citations[:1] or _citations_from_chunks(slide_chunks)[:1] or _fallback_citation(brief.source_corpus_ids)
            summary_template = item.template_key or "closing.actions"
            if summary_template == "exec.summary" or item.archetype is SlideArchetype.EXECUTIVE_SUMMARY:
                slides.append(
                    _exec_summary_slide(
                        item=item,
                        brief=brief,
                        tone_label=tone_label,
                        slide_chunks=slide_chunks,
                        citations=summary_block_citations,
                        summary_items=summary_items,
                    )
                )
                continue
            if summary_template == "kpi.big":
                slides.append(
                    SlideSpec(
                        slide_id=item.slide_id,
                        purpose=item.purpose,
                        archetype=SlideArchetype.METRICS,
                        layout_intent=LayoutIntent(template_key="kpi.big", strict_template=True),
                        headline=item.headline,
                        speaker_notes=_speaker_notes(item.message, "Close on supported actions."),
                        blocks=[
                            PresentationBlock(
                                block_id=f"b{index + 1}",
                                kind=PresentationBlockKind.TEXT,
                                content={"text": value},
                                source_citations=summary_block_citations,
                            )
                            for index, value in enumerate(_kpi_points_from_bullets(summary_items))
                        ],
                    )
                )
                continue
            if summary_template == "closing.actions":
                slides.append(_build_closing_slide(item=item, outline=outline))
                continue
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
                    archetype=item.archetype,
                    layout_intent=LayoutIntent(template_key="headline.evidence", strict_template=True),
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
                            content={
                                "text": _callout_from_chunks(
                                    slide_chunks,
                                    fallback=brief.goal,
                                    used=_UsedPhrases.from_phrases(summary_items),
                                ),
                                "tone_hint": tone_label,
                            },
                            source_citations=summary_block_citations,
                        ),
                    ],
                )
            )
            continue

        used_phrases = _UsedPhrases()
        bullets = _bullets_from_chunks(slide_chunks, fallback=item.message, used=used_phrases)
        citations = _citations_from_chunks(slide_chunks)[:2]
        if citations:
            summary_citations.extend(citations)
        template_key = item.template_key or "headline.evidence"
        if template_key == "exec.summary" or item.archetype is SlideArchetype.EXECUTIVE_SUMMARY:
            slides.append(
                _exec_summary_slide(
                    item=item,
                    brief=brief,
                    tone_label=tone_label,
                    slide_chunks=slide_chunks,
                    citations=citations or _fallback_citation(brief.source_corpus_ids),
                    summary_items=bullets,
                )
            )
            continue
        if template_key == "compare.2col":
            if not _supports_comparison_layout(item.headline, item.message, bullets):
                template_key = "headline.evidence"
            else:
                midpoint = max(1, (len(bullets) + 1) // 2)
                slides.append(
                    SlideSpec(
                        slide_id=item.slide_id,
                        purpose=item.purpose,
                        archetype=SlideArchetype.COMPARISON,
                        layout_intent=LayoutIntent(template_key="compare.2col", strict_template=True),
                        headline=item.headline,
                        speaker_notes=_speaker_notes(item.message, "Reference cited source material while presenting."),
                        blocks=[
                            PresentationBlock(
                                block_id="b1",
                                kind=PresentationBlockKind.BULLETS,
                                content={"items": bullets[:midpoint]},
                                source_citations=citations or _fallback_citation(brief.source_corpus_ids),
                            ),
                            PresentationBlock(
                                block_id="b2",
                                kind=PresentationBlockKind.BULLETS,
                                content={"items": bullets[midpoint:]},
                                source_citations=citations or _fallback_citation(brief.source_corpus_ids),
                            ),
                        ],
                    )
                )
                continue
        if template_key == "chart.takeaway":
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
                    archetype=SlideArchetype.CHART,
                    layout_intent=LayoutIntent(template_key=template_key, strict_template=True),
                    headline=item.headline,
                    speaker_notes=_speaker_notes(item.message, "Reference cited source material while presenting."),
                    blocks=[
                        PresentationBlock(
                            block_id="b1",
                            kind=PresentationBlockKind.CHART,
                            content={"chart_type": "bar", "data": [{"label": f"Point {index + 1}", "value": index + 1} for index, _ in enumerate(bullets[:3])]},
                            source_citations=citations or _fallback_citation(brief.source_corpus_ids),
                        ),
                        PresentationBlock(
                            block_id="b2",
                            kind=PresentationBlockKind.CALLOUT,
                            content={"text": _callout_from_chunks(slide_chunks, fallback=item.message, used=used_phrases), "tone_hint": tone_label},
                            source_citations=citations or _fallback_citation(brief.source_corpus_ids),
                        ),
                    ],
                )
            )
            continue
        if template_key == "kpi.big":
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
                    archetype=SlideArchetype.METRICS,
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
        if template_key == "closing.actions":
            slides.append(_build_closing_slide(item=item, outline=outline))
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
                        content={
                            "text": _callout_from_chunks(slide_chunks, fallback=item.message, used=used_phrases),
                            "tone_hint": tone_label,
                        },
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
    citation_required_purposes = {SlidePurpose.CONTENT, SlidePurpose.SUMMARY, SlidePurpose.CLOSING}
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
    # Build positional fallback: when the LLM generates different slide IDs
    # than the outline, match by position to preserve content
    outline_by_index: dict[int, OutlineItem] = {i: item for i, item in enumerate(outline.outline)}
    slides = []
    for slide_index, slide in enumerate(spec.slides):
        outline_item = outline_items.get(slide.slide_id)
        if outline_item is None and slide_index in outline_by_index:
            outline_item = outline_by_index[slide_index]
            # Rewrite slide_id to match the outline so downstream lookups work
            slide = slide.model_copy(update={"slide_id": outline_item.slide_id})
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
            all_chunks = [c for cs in retrieved_chunks_by_slide.values() for c in cs]
            slides.append(_build_title_slide(item=outline_item, brief=brief, tone_label=tone_label, chunks=all_chunks[:10]))
            continue
        if outline_item is not None and slide.purpose is SlidePurpose.CLOSING:
            slides.append(_build_closing_slide(item=outline_item, outline=outline))
            continue
        if outline_item is not None and (
            outline_item.template_key == "exec.summary"
            or (
                outline_item.archetype is SlideArchetype.EXECUTIVE_SUMMARY
                and outline_item.template_key != "compare.2col"
            )
        ):
            slides.append(
                _exec_summary_slide(
                    item=outline_item,
                    brief=brief,
                    tone_label=tone_label,
                    slide_chunks=slide_chunks,
                    citations=_slide_citations(slide, slide_chunks, brief),
                    summary_items=_slide_summary_points(slide, slide_chunks, fallback=outline_item.message, limit=6),
                )
            )
            continue
        if outline_item is not None and outline_item.template_key == "compare.2col" and not _slide_has_cards(slide):
            summary_points = _slide_summary_points(slide, slide_chunks, fallback=outline_item.message, limit=3)
            comparison_points = [
                point for point in summary_points if _normalize_phrase(point) != _normalize_phrase(slide.headline)
            ]
            if slide.layout_intent.template_key != "compare.2col" and not _supports_comparison_layout(slide.headline, outline_item.message, comparison_points):
                pass
            elif not _supports_comparison_layout(slide.headline, outline_item.message, comparison_points):
                slide = slide.model_copy(
                    update={
                        "layout_intent": LayoutIntent(template_key="headline.evidence", strict_template=True),
                        "blocks": [
                            PresentationBlock(
                                block_id=slide.blocks[0].block_id if slide.blocks else "b1",
                                kind=PresentationBlockKind.BULLETS,
                                content={"items": comparison_points or summary_points or [_trim_words(outline_item.message, 12)]},
                                source_citations=_slide_citations(slide, slide_chunks, brief),
                            )
                        ],
                    }
                )
            else:
                cards = _cards_for_slide(slide, slide_chunks, title_prefix="Capability", desired_count=3) or _cards_from_points(
                    comparison_points,
                    title_prefix="Capability",
                )
                slide = slide.model_copy(
                    update={
                        "layout_intent": LayoutIntent(template_key="compare.2col", strict_template=True),
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
                    slide = slide.model_copy(update={"layout_intent": LayoutIntent(template_key="compare.2col", strict_template=True)})
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
                        slide = slide.model_copy(update={"layout_intent": LayoutIntent(template_key="headline.evidence", strict_template=True)})
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
        if _is_planning_language(text):
            continue
        for candidate in _candidate_phrases(text):
            normalized = _normalize_phrase(candidate)
            if not normalized or normalized in seen:
                continue
            if _is_planning_language(candidate):
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
    source_metadata: dict[str, Any] | None,
    user_request: str,
    goal: str,
) -> DeckBrief:
    from pptx_gen.planning.schemas import DeckBriefExtensions

    takeaways = _derive_takeaways(source_texts, goal)
    thesis = _trim_words(document_title or goal or user_request, 12)
    # Build extensions dict, preserving any LLM-populated values
    ext = brief.extensions.model_dump() if brief.extensions else {}
    if not ext.get("document_title"):
        ext["document_title"] = document_title or "Generated Presentation"
    if not ext.get("one_sentence_thesis"):
        ext["one_sentence_thesis"] = thesis
    if not ext.get("key_takeaways"):
        ext["key_takeaways"] = takeaways
    if not ext.get("user_request"):
        ext["user_request"] = user_request
    if not ext.get("deck_archetype"):
        ext["deck_archetype"] = _infer_deck_archetype(document_title, goal, user_request, source_texts)
    if not ext.get("audience_focus"):
        ext["audience_focus"] = _audience_focus_label(brief.audience)
    if not ext.get("source_preview"):
        ext["source_preview"] = _source_preview(source_texts)
    source_metadata = source_metadata or {}
    if not ext.get("source_format") and source_metadata.get("source_format"):
        ext["source_format"] = str(source_metadata["source_format"])
    if not ext.get("source_slide_count") and source_metadata.get("slide_count"):
        ext["source_slide_count"] = int(source_metadata["slide_count"])
    if not ext.get("source_slide_types") and isinstance(source_metadata.get("slide_types"), dict):
        ext["source_slide_types"] = dict(source_metadata["slide_types"])
    if not ext.get("source_slide_blueprint") and isinstance(source_metadata.get("slide_blueprint"), list):
        ext["source_slide_blueprint"] = list(source_metadata["slide_blueprint"])
    return brief.model_copy(update={"extensions": DeckBriefExtensions(**ext)})


def _outline_from_source_blueprint(brief: DeckBrief) -> OutlineSpec | None:
    extensions = brief.extensions or {}
    if str(extensions.get("source_format", "")).lower() != "pptx":
        return None

    blueprint = extensions.get("source_slide_blueprint") or []
    if not isinstance(blueprint, list) or not blueprint:
        return None

    target_count = max(1, brief.slide_count_target)
    selected_blueprint = blueprint[:target_count]
    if len(selected_blueprint) < target_count:
        for index in range(len(selected_blueprint) + 1, target_count + 1):
            selected_blueprint.append(
                {
                    "slide_number": index,
                    "title": f"Slide {index}",
                    "slide_type": "content",
                    "purpose_hint": "content",
                    "template_hint": "headline.evidence",
                    "text_preview": brief.goal,
                }
            )

    items: list[OutlineItem] = []
    used_templates: dict[str, int] = {}
    for index, slide in enumerate(selected_blueprint, start=1):
        title = str(slide.get("title") or f"Slide {index}").strip() or f"Slide {index}"
        text_preview = str(slide.get("text_preview") or "").strip()
        slide_type = str(slide.get("slide_type") or "content").strip().lower()
        purpose_hint = str(slide.get("purpose_hint") or "content").strip().lower()
        template_hint = str(slide.get("template_hint") or "headline.evidence").strip() or "headline.evidence"

        if purpose_hint == "title" or index == 1:
            purpose = SlidePurpose.TITLE
            archetype = None
            template_key = "title.cover"
            message = _trim_words(text_preview or brief.goal or title, 18) or title
            evidence_queries: list[str] = []
        elif purpose_hint == "closing" or slide_type == "closing":
            purpose = SlidePurpose.CLOSING
            archetype = None
            template_key = "closing.actions"
            message = _trim_words(text_preview or title or brief.goal, 18) or "Summarize supported next steps."
            evidence_queries = _evidence_queries_for_message(f"{title} {message}".strip())
        else:
            purpose = SlidePurpose.CONTENT
            template_key = _template_from_blueprint_slide(slide_type, template_hint)
            if template_key == "headline.evidence":
                template_key = _select_blueprint_content_template(
                    slide=slide,
                    brief=brief,
                    title=title,
                    text_preview=text_preview,
                    used_templates=used_templates,
                )
            archetype = _archetype_for_template(template_key)
            message = _trim_words(text_preview or title or brief.goal, 18) or title
            evidence_queries = _evidence_queries_for_message(f"{title} {message}".strip())
            used_templates[template_key] = used_templates.get(template_key, 0) + 1

        items.append(
            OutlineItem(
                slide_id=f"s{index}",
                purpose=purpose,
                archetype=archetype,
                headline=_short_headline(title, fallback=f"Slide {index}"),
                message=message,
                evidence_queries=evidence_queries,
                template_key=template_key,
            )
        )

    return OutlineSpec(outline=items, questions_for_user=[])


def _template_from_blueprint_slide(slide_type: str, template_hint: str) -> str:
    normalized_hint = (template_hint or "").strip().lower()
    if normalized_hint in {"exec.summary", "compare.2col", "chart.takeaway", "kpi.big", "headline.evidence"}:
        return normalized_hint
    if slide_type == "summary":
        return "exec.summary"
    if slide_type in {"chart"}:
        return "chart.takeaway"
    if slide_type in {"table", "matrix"}:
        return "compare.2col"
    if slide_type in {"three_point"}:
        return "exec.summary"
    return "headline.evidence"


def _select_blueprint_content_template(
    *,
    slide: dict[str, Any],
    brief: DeckBrief,
    title: str,
    text_preview: str,
    used_templates: dict[str, int],
) -> str:
    bullet_count = int(slide.get("bullet_count") or 0)
    text_count = int(slide.get("text_count") or 0)
    table_count = int(slide.get("table_count") or 0)
    picture_count = int(slide.get("picture_count") or 0)
    chart_count = int(slide.get("chart_count") or 0)
    document_title = str((brief.extensions or {}).get("document_title", ""))
    signal_text = f"{title} {text_preview}".strip()
    numeric_signal = bool(re.search(r"\b[\d,.]+[%$]?\b", signal_text))

    hint_terms: list[str] = []
    if chart_count:
        hint_terms.append("chart trend data series")
    if table_count:
        hint_terms.append("comparison matrix table")
    elif bullet_count >= 4:
        hint_terms.append("compare options tradeoff")
    elif bullet_count == 3:
        hint_terms.append("executive summary overview")
    if numeric_signal:
        hint_terms.append("kpi metric performance growth")
    if picture_count and text_count <= 2 and bullet_count <= 2 and not hint_terms:
        hint_terms.append("headline evidence visual")
    if picture_count and text_count <= 2 and bullet_count <= 2 and not any((table_count, chart_count, numeric_signal)):
        return _least_used_template(("headline.evidence", "exec.summary", "compare.2col"), used_templates)

    candidate = _score_content_template(
        " ".join(part for part in [signal_text, *hint_terms] if part),
        brief.goal,
        brief.audience,
        document_title,
        used_templates=used_templates,
        candidates=PPTX_BLUEPRINT_VARIETY_TEMPLATES,
    )

    if candidate == "chart.takeaway" and not chart_count:
        return _least_used_template(PPTX_BLUEPRINT_GENERIC_ROTATION, used_templates)
    if candidate == "kpi.big" and not numeric_signal:
        return _least_used_template(PPTX_BLUEPRINT_GENERIC_ROTATION, used_templates)
    return candidate


def _least_used_template(candidates: tuple[str, ...], used_templates: dict[str, int] | None = None) -> str:
    usage = used_templates or {}
    return min(candidates, key=lambda template: (usage.get(template, 0), candidates.index(template)))


def _archetype_for_template(template_key: str) -> SlideArchetype | None:
    if template_key == "exec.summary":
        return SlideArchetype.EXECUTIVE_SUMMARY
    if template_key == "compare.2col":
        return SlideArchetype.COMPARISON
    if template_key == "chart.takeaway":
        return SlideArchetype.CHART
    if template_key == "kpi.big":
        return SlideArchetype.METRICS
    return None


def _archetype_from_blueprint_slide(slide_type: str, template_hint: str) -> SlideArchetype | None:
    return _archetype_for_template(_template_from_blueprint_slide(slide_type, template_hint))


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
    limit = 6000
    for chunk in chunks[:25]:
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
    seen: set[str] = set()
    for item in base:
        normalized = _normalize_phrase(item)
        if not normalized or normalized in seen:
            continue
        messages.append(item)
        seen.add(normalized)
        if len(messages) >= count:
            return messages[:count]
    goal_focus = _trim_words(goal, 8)
    framings = [
        f"Key drivers behind {goal_focus}",
        f"Impact and outcomes of {goal_focus}",
        f"Implementation roadmap for {goal_focus}",
        f"Risk factors and mitigations for {goal_focus}",
        f"Operating requirements for {goal_focus}",
        f"Decision criteria for {goal_focus}",
    ]
    for framing in framings:
        normalized = _normalize_phrase(framing)
        if not normalized or normalized in seen:
            continue
        messages.append(framing)
        seen.add(normalized)
        if len(messages) >= count:
            break
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
        if _is_planning_language(trimmed):
            continue
        if len(trimmed.split()) < 5:
            continue
        filtered.append(trimmed.rstrip(".,;:"))
        seen.add(normalized)
    return filtered


def _plan_content_messages(brief: DeckBrief, takeaways: list[str], count: int) -> list[str]:
    return _expand_content_messages(takeaways, brief.goal, count)


def _overview_message(brief: DeckBrief, takeaways: list[str]) -> str:
    thesis = str((brief.extensions or {}).get("one_sentence_thesis", brief.goal))
    supporting = takeaways[0] if takeaways else brief.goal
    return _trim_words(f"{thesis}. {supporting}.", 18)


def _score_content_template(
    message: str,
    goal: str,
    audience: str = "",
    document_title: str = "",
    *,
    used_templates: dict[str, int] | None = None,
    candidates: tuple[str, ...] | None = None,
) -> str:
    """Score all eligible templates and return the best fit with diversity awareness."""
    haystack = f"{message} {goal} {audience} {document_title}".lower()
    word_count = len(re.findall(r"\b\w+\b", haystack))
    numeric_density = len(re.findall(r"\b[\d,.]+[%$]?\b", haystack))
    bullet_count = haystack.count("\n") + 1

    # Content-eligible templates (exclude title.cover and section.divider)
    candidate_templates = list(candidates) if candidates else [
        "headline.evidence", "kpi.big", "compare.2col", "chart.takeaway",
        "exec.summary", "closing.actions", "content.3col", "content.4col",
        "icons.3", "icons.4", "impact.statement", "split.content",
        "quote.texture", "agenda.table",
    ]

    content_scores: dict[str, float] = {t: 0.0 for t in candidate_templates}
    purpose_scores: dict[str, float] = {t: 0.0 for t in candidate_templates}

    def _bump(scores: dict[str, float], template: str, amount: float) -> None:
        if template in scores:
            scores[template] += amount

    # --- Content structure signals ---
    if numeric_density >= 2:
        _bump(content_scores, "kpi.big", 0.8)
        _bump(content_scores, "chart.takeaway", 0.4)
    if any(t in haystack for t in ("compare", "comparison", "option", "versus", "tradeoff", "pros", "cons")):
        _bump(content_scores, "compare.2col", 0.8)
    if any(t in haystack for t in ("quote", "said", "according to", '"')):
        _bump(content_scores, "quote.texture", 0.7)
    if any(t in haystack for t in ("schedule", "agenda", "timeline", "matrix", "table")):
        _bump(content_scores, "agenda.table", 0.7)
    if word_count < 15:
        _bump(content_scores, "impact.statement", 0.7)
        _bump(content_scores, "quote.texture", 0.4)
    if word_count > 40:
        _bump(content_scores, "headline.evidence", 0.4)
        _bump(content_scores, "split.content", 0.3)
    if bullet_count == 3:
        _bump(content_scores, "content.3col", 0.6)
        _bump(content_scores, "icons.3", 0.5)
    elif bullet_count == 4:
        _bump(content_scores, "content.4col", 0.6)
        _bump(content_scores, "icons.4", 0.5)
    elif bullet_count >= 5:
        _bump(content_scores, "headline.evidence", 0.5)
    # General content gets a small baseline for variety candidates
    if any(t in haystack for t in ("capability", "feature", "pillar", "strategy", "benefit")):
        _bump(content_scores, "icons.3", 0.4)
        _bump(content_scores, "icons.4", 0.3)
        _bump(content_scores, "content.3col", 0.3)

    # --- Purpose signals ---
    if any(t in haystack for t in ("next step", "action", "closing", "recommendation", "call to action")):
        _bump(purpose_scores, "closing.actions", 0.8)
    if any(t in haystack for t in ("overview", "summary", "executive", "landscape")):
        _bump(purpose_scores, "exec.summary", 0.7)
    if any(t in haystack for t in ("chart", "trend", "graph", "data series", "plot", "visualization")):
        _bump(purpose_scores, "chart.takeaway", 0.8)
    if any(t in haystack for t in ("metric", "kpi", "score", "rate", "roi", "growth", "performance")):
        _bump(purpose_scores, "kpi.big", 0.6)

    # --- Diversity penalty ---
    best_score = -1.0
    best_template = "headline.evidence"
    for template in candidate_templates:
        diversity_score = 1.0
        if used_templates and template in used_templates:
            diversity_score = max(0.0, 1.0 - used_templates[template] * 0.3)
        if template == "headline.evidence":
            diversity_score -= 0.15

        final = (content_scores[template] * 0.4) + (purpose_scores[template] * 0.3) + (diversity_score * 0.3)
        if final > best_score or (final == best_score and (used_templates or {}).get(template, 0) < (used_templates or {}).get(best_template, 0)):
            best_score = final
            best_template = template

    return best_template


def _cards_from_points(items: list[str], *, title_prefix: str) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for index, item in enumerate(items[:3], start=1):
        title = _card_title_from_point(item, fallback=f"{title_prefix} {index}")
        cards.append({"title": title, "text": _trim_words(item, 20)})
    return cards


def _build_title_slide(
    *,
    item: OutlineItem,
    brief: DeckBrief,
    tone_label: str,
    chunks: list[RetrievedChunk] | None = None,
) -> SlideSpec:
    subtitle = _title_subtitle_from_content(brief, item, chunks or [])
    return SlideSpec(
        slide_id=item.slide_id,
        purpose=item.purpose,
        layout_intent=LayoutIntent(template_key="title.cover", strict_template=True),
        headline=item.headline,
        speaker_notes=_speaker_notes(item.message, brief.goal),
        blocks=[
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.TEXT,
                content={
                    "subtitle": subtitle,
                    "presenter": _trim_words(brief.audience, 6),
                    "date": date.today().isoformat(),
                    "tagline": tone_label,
                },
            )
        ],
    )


def _build_closing_slide(*, item: OutlineItem, outline: OutlineSpec) -> SlideSpec:
    action_items: list[str] = []
    seen: set[str] = set()
    for outline_item in outline.outline:
        if outline_item.purpose not in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}:
            continue
        trimmed = _trim_words(outline_item.headline, 10)
        normalized = _normalize_phrase(trimmed)
        if normalized in seen:
            continue
        seen.add(normalized)
        action_items.append(trimmed)
        if len(action_items) >= 6:
            break
    return SlideSpec(
        slide_id=item.slide_id,
        purpose=SlidePurpose.CLOSING,
        layout_intent=LayoutIntent(template_key="closing.actions", strict_template=True),
        headline=item.headline,
        speaker_notes=_speaker_notes(item.message, "Close with the recommended actions and final takeaway."),
        blocks=[
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.BULLETS,
                content={"items": action_items or ["Review priorities", "Align owners", "Confirm next step"]},
            ),
            PresentationBlock(
                block_id="b2",
                kind=PresentationBlockKind.CALLOUT,
                content={"text": _trim_words(item.message or "Drive alignment on the next decisions and actions.", 20)},
            ),
        ],
    )


def _build_agenda_slide(*, item: OutlineItem, outline: OutlineSpec) -> SlideSpec:
    return _build_closing_slide(item=item, outline=outline)


def _title_subtitle_from_content(
    brief: DeckBrief,
    item: OutlineItem,
    chunks: list[RetrievedChunk],
) -> str:
    """Build a meaningful subtitle from document content, not internal metadata."""
    extensions = brief.extensions or {}

    for candidate in [
        extensions.get("one_sentence_thesis"),
        *((extensions.get("key_takeaways") or [])[:2]),
        item.message,
        brief.goal,
    ]:
        subtitle = _prepare_title_subtitle_candidate(candidate)
        if subtitle:
            return _apply_audience_specific_subtitle(subtitle, brief)

    subtitle = _best_chunk_subtitle_candidate(chunks)
    if subtitle:
        return _apply_audience_specific_subtitle(subtitle, brief)

    subtitle = _trim_words(brief.goal or item.message or "Executive overview", 20)
    return _apply_audience_specific_subtitle(subtitle, brief)


def _apply_audience_specific_subtitle(subtitle: str, brief: DeckBrief) -> str:
    normalized_audience = brief.audience.lower()
    if "oracle" in normalized_audience and "oracle" not in subtitle.lower():
        return _trim_words(f"{subtitle} For {brief.audience}.", 25)
    return subtitle


def _prepare_title_subtitle_candidate(value: object) -> str:
    cleaned = _clean_candidate_phrase(str(value or "").strip())
    if not cleaned:
        return ""
    trimmed = _trim_words(cleaned, 25)
    if len(trimmed.split()) < 4:
        return ""
    if TITLE_SUBTITLE_GENERIC_PATTERN.fullmatch(trimmed):
        return ""
    return trimmed


def _best_chunk_subtitle_candidate(chunks: list[RetrievedChunk]) -> str:
    ranked: list[tuple[int, str]] = []
    for chunk_index, chunk in enumerate(chunks[:6]):
        for phrase_index, candidate in enumerate(_candidate_phrases(chunk.text)):
            prepared = _prepare_title_subtitle_candidate(candidate)
            if not prepared:
                continue
            score = _score_title_subtitle_candidate(prepared, chunk_index=chunk_index, phrase_index=phrase_index)
            ranked.append((score, prepared))
    if not ranked:
        return ""
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _score_title_subtitle_candidate(candidate: str, *, chunk_index: int, phrase_index: int) -> int:
    lowered = candidate.lower()
    words = candidate.split()
    score = max(0, 10 - (chunk_index * 2))
    score += max(0, 4 - phrase_index)
    if 4 <= len(words) <= 12:
        score += 6
    elif len(words) <= 18:
        score += 3
    if any(term in lowered for term in TITLE_SUBTITLE_HIGH_LEVEL_TERMS):
        score += 5
    score -= _subtitle_jargon_penalty(candidate)
    return score


def _subtitle_jargon_penalty(candidate: str) -> int:
    lowered = candidate.lower()
    penalty = 0
    if TITLE_SUBTITLE_CODELIKE_PATTERN.search(candidate):
        penalty += 8
    upper_tokens = len(re.findall(r"\b[A-Z]{2,}\b", candidate))
    if upper_tokens >= 2:
        penalty += 4
    camelcase_tokens = len(TITLE_SUBTITLE_CAMELCASE_PATTERN.findall(candidate))
    if camelcase_tokens:
        penalty += 4
    technical_hits = sum(1 for term in TITLE_SUBTITLE_TECHNICAL_TERMS if term in lowered)
    if technical_hits >= 3:
        penalty += 8
    elif technical_hits == 2:
        penalty += 4
    elif technical_hits == 1:
        penalty += 1
    return penalty


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
    title = " ".join(words[:6]).strip()
    return title or fallback


def _kpi_points_from_bullets(items: list[str]) -> list[str]:
    values = [_trim_words(item, 8) for item in items[:3]]
    return values


def _exec_summary_slide(
    *,
    item: OutlineItem,
    brief: DeckBrief,
    tone_label: str,
    slide_chunks: list[RetrievedChunk],
    citations: list[SourceCitation],
    summary_items: list[str],
) -> SlideSpec:
    used = _UsedPhrases.from_phrases(summary_items)
    summary_points = _bullets_from_chunks(slide_chunks, fallback=item.message, used=used)[:5]
    if not summary_points:
        summary_points = summary_items[:5] or [_trim_words(brief.goal, 12)]
    callout_text = _specialist_callout(brief, slide_chunks, fallback=item.message, used=used)
    summary_signature = _normalize_phrase(" ".join(summary_points))
    if _phrases_are_near_duplicate(summary_signature, _normalize_phrase(callout_text)):
        callout_text = _trim_words(item.message, 20) if item.message else "Key insight"
    cards = _overview_cards(slide_chunks, summary_items, used=used)[:3]
    return SlideSpec(
        slide_id=item.slide_id,
        purpose=item.purpose,
        archetype=SlideArchetype.EXECUTIVE_SUMMARY,
        layout_intent=LayoutIntent(template_key="exec.summary", strict_template=True),
        headline=item.headline,
        speaker_notes=_speaker_notes(item.message, "Lead with the architecture and why it matters."),
        blocks=[
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.BULLETS,
                content={"items": summary_points},
                source_citations=citations,
            ),
            PresentationBlock(
                block_id="b2",
                kind=PresentationBlockKind.CALLOUT,
                content={
                    "text": callout_text,
                    "tone_hint": tone_label,
                },
                source_citations=citations,
            ),
            PresentationBlock(
                block_id="b3",
                kind=PresentationBlockKind.CALLOUT,
                content={"cards": cards},
                source_citations=citations,
            ),
        ],
    )


def _executive_overview_slide(
    *,
    item: OutlineItem,
    brief: DeckBrief,
    tone_label: str,
    slide_chunks: list[RetrievedChunk],
    citations: list[SourceCitation],
    summary_items: list[str],
) -> SlideSpec:
    return _exec_summary_slide(
        item=item,
        brief=brief,
        tone_label=tone_label,
        slide_chunks=slide_chunks,
        citations=citations,
        summary_items=summary_items,
    )


def _executive_summary_slide(
    *,
    item: OutlineItem,
    brief: DeckBrief,
    tone_label: str,
    slide_chunks: list[RetrievedChunk],
    citations: list[SourceCitation],
    summary_items: list[str],
) -> SlideSpec:
    return _exec_summary_slide(
        item=item,
        brief=brief,
        tone_label=tone_label,
        slide_chunks=slide_chunks,
        citations=citations,
        summary_items=summary_items,
    )


def _architecture_grid_slide(
    *,
    item: OutlineItem,
    brief: DeckBrief,
    slide_chunks: list[RetrievedChunk],
    citations: list[SourceCitation],
    summary_items: list[str],
) -> SlideSpec:
    return _exec_summary_slide(
        item=item,
        brief=brief,
        tone_label=_tone_label(brief.tone),
        slide_chunks=slide_chunks,
        citations=citations,
        summary_items=summary_items,
    )


def _overview_summary_text(
    item: OutlineItem,
    brief: DeckBrief,
    slide_chunks: list[RetrievedChunk],
    *,
    used: "_UsedPhrases | None" = None,
) -> str:
    sentences: list[str] = []
    for chunk in slide_chunks:
        for sentence in re.split(r"(?<=[.!?])\s+", chunk.text):
            stripped_sentence = sentence.strip()
            if not stripped_sentence.endswith((".", "!", "?")):
                continue
            cleaned = _clean_candidate_phrase(stripped_sentence)
            if not cleaned or len(cleaned.split()) < 8:
                continue
            if used is not None and used.is_used(cleaned):
                continue
            summary_sentence = _trim_words(cleaned, 25)
            sentences.append(summary_sentence)
            if used is not None:
                used.mark(cleaned)
            if len(sentences) >= 2:
                break
        if len(sentences) >= 2:
            break
    if sentences:
        return " ".join(sentences)
    thesis = str((brief.extensions or {}).get("one_sentence_thesis", brief.goal))
    summary = _trim_words(thesis, 30)
    if used is not None:
        used.mark(summary)
    return summary


def _overview_cards(
    slide_chunks: list[RetrievedChunk],
    summary_items: list[str],
    *,
    used: "_UsedPhrases | None" = None,
) -> list[dict[str, str]]:
    semantic_cards = _semantic_cards_from_chunks(slide_chunks, desired_count=6, mode="overview", used=used)
    if semantic_cards:
        return semantic_cards
    points: list[str] = []
    for item in summary_items:
        if used is not None and used.is_used(item):
            continue
        if item not in points:
            points.append(item)
            if used is not None:
                used.mark(item)
    for chunk in slide_chunks:
        for phrase in _candidate_phrases(chunk.text):
            if used is not None and used.is_used(phrase):
                continue
            if phrase not in points:
                points.append(phrase)
                if used is not None:
                    used.mark(phrase)
            if len(points) >= 6:
                return _compact_cards(points[:6], title_prefix="Capability")
    return _compact_cards(points[:6], title_prefix="Capability")


def _architecture_summary_text(
    item: OutlineItem,
    brief: DeckBrief,
    slide_chunks: list[RetrievedChunk],
    *,
    used: "_UsedPhrases | None" = None,
) -> str:
    phrases = []
    for chunk in slide_chunks:
        for phrase in _candidate_phrases(chunk.text):
            if used is not None and used.is_used(phrase):
                continue
            phrases.append(phrase)
            if len(phrases) >= 2:
                break
        if len(phrases) >= 2:
            break
    if phrases:
        if used is not None:
            used.mark_all(phrases[:2])
        return _trim_words(". ".join(phrases[:2]), 30)
    thesis = str((brief.extensions or {}).get("one_sentence_thesis", brief.goal))
    summary = _trim_words(thesis, 25)
    if used is not None:
        used.mark(summary)
    return summary


def _architecture_cards(
    slide_chunks: list[RetrievedChunk],
    summary_items: list[str],
    *,
    used: "_UsedPhrases | None" = None,
) -> list[dict[str, str]]:
    semantic_cards = _semantic_cards_from_chunks(slide_chunks, desired_count=6, mode="architecture", used=used)
    if semantic_cards:
        return semantic_cards
    components: list[str] = []
    for chunk in slide_chunks:
        for phrase in _candidate_phrases(chunk.text):
            if used is not None and used.is_used(phrase):
                continue
            if phrase not in components:
                components.append(phrase)
                if used is not None:
                    used.mark(phrase)
            if len(components) >= 6:
                return _compact_cards(components[:6], title_prefix="Component")
    for item in summary_items:
        if used is not None and used.is_used(item):
            continue
        if item not in components:
            components.append(item)
            if used is not None:
                used.mark(item)
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
    used: "_UsedPhrases | None" = None,
) -> str:
    # Extract a real insight from chunks rather than returning metadata labels.
    for chunk in slide_chunks:
        for candidate in _candidate_phrases(chunk.text):
            if used is not None and used.is_used(candidate):
                continue
            if _normalize_phrase(candidate) != _normalize_phrase(fallback):
                if used is not None:
                    used.mark(candidate)
                return _trim_words(candidate, 20)
    audience_label = _trim_words(brief.audience, 4)
    goal_label = _trim_words(brief.goal, 12)
    insight = f"{goal_label} framed for {audience_label}".strip()
    if used is not None:
        used.mark(insight)
    return insight


def _compact_cards(items: list[str], *, title_prefix: str, desired_count: int = 3) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for index, item in enumerate(items[:desired_count], start=1):
        words = [word.strip(",.:;") for word in str(item).split() if word]
        title = " ".join(words[:5]).strip() or _trim_words(str(item), 5) or f"{title_prefix} {index}"
        cards.append({"title": title, "text": _trim_words(item, 20)})
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
    if slide.purpose not in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY, SlidePurpose.CLOSING}:
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
            "layout_intent": LayoutIntent(template_key="headline.evidence", strict_template=True),
            "blocks": [table_block],
        }
    )


def _maybe_upgrade_slide_to_cards(slide: SlideSpec, chunks: list[RetrievedChunk], brief: DeckBrief) -> SlideSpec:
    if slide.purpose not in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY, SlidePurpose.CLOSING}:
        return slide
    if slide.layout_intent.template_key in {"exec.summary", "chart.takeaway"}:
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
            "layout_intent": LayoutIntent(template_key="headline.evidence", strict_template=True),
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


def _supports_comparison_layout(headline: str, message: str, points: list[str]) -> bool:
    if len(points) >= 3:
        return True
    normalized = f"{headline} {message}".lower()
    comparison_terms = (
        "compare",
        "comparison",
        "vs",
        "versus",
        "option",
        "options",
        "alternative",
        "alternatives",
        "tradeoff",
        "trade-off",
        "before",
        "after",
        "pros",
        "cons",
        "current state",
        "future state",
    )
    return len(points) >= 2 and any(term in normalized for term in comparison_terms)


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
            text = _trim_words(" ".join(text_parts) or title, 25)
            cards.append({"title": title, "text": text})
        elif record is not None:
            cards.append({"title": f"{title_prefix} {index}", "text": _trim_words(str(record), 25)})
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
    used: "_UsedPhrases | None" = None,
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
                "Uses fixed, pre-designed layouts to ensure visual consistency and professional formatting across all slides.",
            ),
            (
                ("rule-based", "auto-layout", "auto layout", "constraint"),
                "Rule-Based Layout",
                "Applies constraint-based rules to automatically resize and reposition elements within the slide canvas.",
            ),
            (
                ("free-form", "free form", "generated from scratch"),
                "Free-Form Generation",
                "The model proposes structure and layout from scratch when no template constraint is specified.",
            ),
            (
                ("qa", "validation", "overlap", "contrast"),
                "QA and Validation",
                "Automated checks catch text overflow, element overlap, and color contrast issues before export.",
            ),
        ]
    else:
        definitions = [
            (
                ("structured data", "connector", "connectors", "records"),
                "Structured Data Ingestion",
                "Parses structured documents and records into a normalized format for downstream slide generation.",
            ),
            (
                ("document upload", "uploads", "drive", "cloud file", "word/docs", "pdf"),
                "Document and Cloud Inputs",
                "Accepts uploads from local files, cloud drives, and enterprise content management systems.",
            ),
            (
                ("retrieval", "rag", "vector", "embedding", "vectorization"),
                "RAG-style Retrieval",
                "Grounds slide content in source material using vector-based retrieval to surface relevant evidence.",
            ),
            (
                ("planning", "outline", "brief", "intent"),
                "Outline-first Planning",
                "Generates a structured brief and slide outline before producing any content, ensuring narrative coherence.",
            ),
            (
                ("template", "layout", "constraint", "alignment"),
                "Template-driven Layout",
                "Maps each slide to a deterministic template for consistent composition and element alignment.",
            ),
            (
                ("asset", "chart", "icon", "visual"),
                "Asset Generation",
                "Produces charts, icons, and visual assets from data and style tokens embedded in the slide spec.",
            ),
            (
                ("export", "pptx", "ooxml", "renderer", "render"),
                "Deterministic Export",
                "Renders the final spec into editable PPTX output with full OOXML fidelity for downstream editing.",
            ),
            (
                ("qa", "validation", "overlap", "consistency"),
                "QA and Validation",
                "Runs overlap detection, contrast checks, and consistency validation across the full presentation.",
            ),
        ]

    # Try to extract real descriptions from chunks for each matched definition
    cards: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    seen_descriptions: set[str] = set()
    for keywords, title, fallback_text in definitions:
        if any(keyword in lower for keyword in keywords):
            if title in seen_titles:
                continue
            # Search chunks for a sentence containing the keyword to use as description
            description = fallback_text
            for chunk in chunks:
                for keyword in keywords:
                    if keyword in chunk.text.lower():
                        for sentence in re.split(r'(?<=[.!?])\s+', chunk.text):
                            if keyword in sentence.lower() and len(sentence.split()) >= 6:
                                if _is_planning_language(sentence):
                                    continue
                                cleaned_sentence = _clean_candidate_phrase(sentence.strip())
                                if not cleaned_sentence:
                                    continue
                                candidate_description = _trim_words(cleaned_sentence, 25)
                                if used is not None and used.is_used(candidate_description):
                                    continue
                                if _normalize_phrase(candidate_description) in seen_descriptions:
                                    continue
                                description = candidate_description
                                if used is not None:
                                    used.mark(candidate_description)
                                break
                        if description != fallback_text:
                            break
                if description != fallback_text:
                    break
            normalized_description = _normalize_phrase(description)
            if normalized_description in seen_descriptions:
                description = fallback_text
                normalized_description = _normalize_phrase(fallback_text)
            if normalized_description in seen_descriptions:
                continue
            cards.append({"title": title, "text": description})
            seen_titles.add(title)
            seen_descriptions.add(normalized_description)
            if len(cards) >= desired_count:
                return cards[:desired_count]
    for _, title, fallback_text in definitions:
        if title in seen_titles:
            continue
        normalized_description = _normalize_phrase(fallback_text)
        if normalized_description in seen_descriptions:
            continue
        cards.append({"title": title, "text": fallback_text})
        seen_titles.add(title)
        seen_descriptions.add(normalized_description)
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


def _is_planning_language(text: str) -> bool:
    normalized = str(text).strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in PLANNING_LANGUAGE_PATTERNS)


class _UsedPhrases:
    """Tracks normalized phrases already assigned to blocks on a slide."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    @classmethod
    def from_phrases(cls, phrases: list[str]) -> "_UsedPhrases":
        tracker = cls()
        tracker.mark_all(phrases)
        return tracker

    def is_used(self, phrase: str) -> bool:
        return _normalize_phrase(phrase) in self._seen

    def mark(self, phrase: str) -> None:
        normalized = _normalize_phrase(phrase)
        if normalized:
            self._seen.add(normalized)

    def mark_all(self, phrases: list[str]) -> None:
        for phrase in phrases:
            self.mark(phrase)


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


def _deduplicate_slide_blocks(
    spec: PresentationSpec,
    retrieved_chunks_by_slide: dict[str, list[RetrievedChunk]],
) -> PresentationSpec:
    updated_slides: list[SlideSpec] = []
    changed = False
    for slide in spec.slides:
        updated_blocks = _deduplicate_blocks_for_slide(slide.blocks, retrieved_chunks_by_slide.get(slide.slide_id, []))
        if len(updated_blocks) != len(slide.blocks) or any(new is not old for new, old in zip(updated_blocks, slide.blocks)):
            slide = slide.model_copy(update={"blocks": updated_blocks})
            changed = True
        updated_slides.append(slide)
    if not changed:
        return spec
    return spec.model_copy(update={"slides": updated_slides})


def _deduplicate_blocks_for_slide(
    blocks: list[PresentationBlock],
    chunks: list[RetrievedChunk],
) -> list[PresentationBlock]:
    if len(blocks) <= 1:
        return blocks

    result: list[PresentationBlock] = []
    seen_texts: list[str] = []
    used = _UsedPhrases()

    for block in blocks:
        block_text = _normalize_phrase(" ".join(_block_lines(block)))
        is_duplicate = any(_phrases_are_near_duplicate(block_text, existing) for existing in seen_texts if block_text)
        if not is_duplicate:
            result.append(block)
            if block_text:
                seen_texts.append(block_text)
            used.mark_all(_block_lines(block))
            continue

        replacement = _next_distinct_phrase(chunks, used=used)
        if replacement:
            result.append(_replace_block_content(block, replacement))
            replacement_text = _normalize_phrase(replacement)
            if replacement_text:
                seen_texts.append(replacement_text)
            used.mark(replacement)
        elif result:
            # Keep the first duplicate-equivalence class member already in `result`
            # when no distinct replacement exists. This is order-dependent by design
            # and avoids dropping every block in an all-duplicate slide.
            continue
        else:
            result.append(block)
            if block_text:
                seen_texts.append(block_text)

    return result or blocks[:1]


def _phrases_are_near_duplicate(left: str, right: str, *, threshold: float = 0.7) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    left_words = set(left.split())
    right_words = set(right.split())
    if not left_words or not right_words:
        return False
    overlap = left_words & right_words
    union = left_words | right_words
    return len(overlap) / len(union) >= threshold


def _next_distinct_phrase(chunks: list[RetrievedChunk], *, used: _UsedPhrases) -> str | None:
    for chunk in chunks:
        for candidate in _candidate_phrases(chunk.text):
            if used.is_used(candidate):
                continue
            return candidate
    return None


def _replace_block_content(block: PresentationBlock, replacement: str) -> PresentationBlock:
    if block.kind is PresentationBlockKind.BULLETS:
        content = {"items": [replacement]}
    elif block.kind is PresentationBlockKind.CALLOUT and isinstance(block.content.get("cards"), list):
        content = {"cards": [{"title": _card_title_from_point(replacement, fallback="Detail"), "text": _trim_words(replacement, 25)}]}
    elif block.kind is PresentationBlockKind.KPI_CARDS:
        content = {"items": [{"value": _trim_words(replacement, 3), "label": _trim_words(replacement, 8)}]}
    else:
        content = dict(block.content)
        content["text"] = _trim_words(replacement, 25)
    return block.model_copy(update={"content": content})


def _bullets_from_chunks(chunks: list[RetrievedChunk], *, fallback: str, used: "_UsedPhrases | None" = None) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()
    fallback_norm = _normalize_phrase(fallback)
    for chunk in chunks:
        for candidate in _candidate_phrases(chunk.text):
            normalized = _normalize_phrase(candidate)
            if not normalized or normalized == fallback_norm or normalized in seen:
                continue
            if used is not None and used.is_used(candidate):
                continue
            bullets.append(candidate)
            seen.add(normalized)
            if used is not None:
                used.mark(candidate)
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
        if used is not None:
            used.mark_all(bullets)
    return bullets[:3]


def _callout_from_chunks(chunks: list[RetrievedChunk], *, fallback: str, used: "_UsedPhrases | None" = None) -> str:
    for chunk in chunks:
        for candidate in _candidate_phrases(chunk.text):
            if used is not None and used.is_used(candidate):
                continue
            if _normalize_phrase(candidate) != _normalize_phrase(fallback):
                if used is not None:
                    used.mark(candidate)
                return _trim_words(candidate, 15)
    if used is not None:
        used.mark("Supported evidence")
    return "Supported evidence"


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
    cleaned = strip_markdown(str(text).replace("AI- generated", "AI-generated")).strip(" -\t")
    cleaned = SECTION_LABEL_PREFIX_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    if _is_planning_language(cleaned):
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
    trimmed = _trim_words(cleaned.rstrip(".;:"), 25)
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
