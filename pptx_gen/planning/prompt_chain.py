"""Five-step planning orchestration with schema-validated fallbacks."""

from __future__ import annotations

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
        slide_count_target=max(3, min(12, slide_count_target)),
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

    takeaways = list((brief.extensions or {}).get("key_takeaways", []))
    deck_title = str((brief.extensions or {}).get("document_title", brief.goal))
    include_agenda = brief.slide_count_target >= 5
    reserved = 3 if include_agenda else 2
    content_count = max(1, brief.slide_count_target - reserved)
    content_messages = _expand_content_messages(takeaways, brief.goal, content_count)

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

    for message in content_messages:
        outline.append(
            OutlineItem(
                slide_id=f"s{next_index}",
                purpose=SlidePurpose.CONTENT,
                headline=_short_headline(message, fallback=f"Slide {next_index}"),
                message=_trim_words(message, 18),
                evidence_queries=_evidence_queries_for_message(message),
                template_key="content.1col",
            )
        )
        next_index += 1

    outline.append(
        OutlineItem(
            slide_id=f"s{next_index}",
            purpose=SlidePurpose.SUMMARY,
            headline="Key Takeaways",
            message="Summarize the strongest supported points and actions.",
            evidence_queries=[],
            template_key="content.1col",
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
        return _upgrade_visual_templates(spec, retrieved_chunks_by_slide)

    slides: list[SlideSpec] = []
    summary_citations: list[SourceCitation] = []
    takeaways = list((brief.extensions or {}).get("key_takeaways", []))

    for item in outline.outline:
        slide_chunks = retrieved_chunks_by_slide.get(item.slide_id, [])
        if item.purpose is SlidePurpose.TITLE:
            slides.append(
                SlideSpec(
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
                                "subtitle": _trim_words(brief.goal, 8),
                                "presenter": _trim_words(brief.audience, 4),
                                "date": date.today().isoformat(),
                            },
                        )
                    ],
                )
            )
            continue

        if item.purpose is SlidePurpose.AGENDA:
            agenda_items = [
                _trim_words(outline_item.headline, 4)
                for outline_item in outline.outline
                if outline_item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}
            ][:4]
            slides.append(
                SlideSpec(
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
            )
            continue

        if item.purpose is SlidePurpose.SUMMARY:
            summary_items = [_trim_words(text, 6) for text in (takeaways or [brief.goal])][:3]
            summary_block_citations = summary_citations[:1] or _citations_from_chunks(slide_chunks)[:1] or _fallback_citation(brief.source_corpus_ids)
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
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
                            content={"text": _trim_words(brief.goal, 6)},
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
        slides.append(
            SlideSpec(
                slide_id=item.slide_id,
                purpose=item.purpose,
                layout_intent=LayoutIntent(template_key=item.template_key or "content.1col", strict_template=True),
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
                        content={"text": _trim_words(item.message, 5)},
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
    return _upgrade_visual_templates(spec, retrieved_chunks_by_slide)


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
    for text in source_texts:
        candidate = _trim_words(_first_sentence(text), 8)
        if candidate and candidate not in takeaways:
            takeaways.append(candidate)
        if len(takeaways) == 4:
            break
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
    preview_items = _derive_takeaways(source_texts, goal="summarize source")
    return "\n".join(f"- {item}" for item in preview_items[:4])


def _expand_content_messages(takeaways: list[str], goal: str, count: int) -> list[str]:
    base = takeaways or [_trim_words(goal, 10)]
    messages: list[str] = []
    for index in range(count):
        source = base[index % len(base)]
        if index < len(base):
            messages.append(source)
        else:
            messages.append(f"{source} evidence")
    return messages


def _upgrade_visual_templates(
    spec: PresentationSpec,
    retrieved_chunks_by_slide: dict[str, list[RetrievedChunk]],
) -> PresentationSpec:
    updated_slides: list[SlideSpec] = []
    changed = False

    for slide in spec.slides:
        upgraded = _maybe_upgrade_slide_to_table(slide, retrieved_chunks_by_slide.get(slide.slide_id, []))
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


def _bullets_from_chunks(chunks: list[RetrievedChunk], *, fallback: str) -> list[str]:
    bullets: list[str] = []
    for chunk in chunks[:3]:
        bullet = _trim_words(_first_sentence(chunk.text), 8)
        if bullet and bullet not in bullets:
            bullets.append(bullet)
    if not bullets:
        bullets.append(_trim_words(fallback, 8))
    return bullets[:3]


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
