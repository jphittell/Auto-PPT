from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import pptx_gen.planning.prompt_chain as prompt_chain_module
from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.ingestion.chunker import chunk_document
from pptx_gen.ingestion.schemas import ContentElementType, ContentObject, DocumentInfo, IngestionOptions, IngestionRequest, SourceInfo, SourceType
from pptx_gen.layout.schemas import StyleTokens
from pptx_gen.planning.prompt_chain import (
    build_retrieval_plan,
    collect_deck_brief,
    execute_retrieval_plan,
    generate_outline,
    generate_presentation_spec,
    revise_for_design_quality,
)
from pptx_gen.planning.schemas import (
    DeckBrief,
    DeckTheme,
    OutlineItem,
    OutlineSpec,
    PresentationBlock,
    PresentationBlockKind,
    PresentationSpec,
    RetrievalPlan,
    RetrievedChunk,
    SlideSpec,
    SlidePurpose,
    LayoutIntent,
)


GOLD_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gold"


def _load_gold_fixture(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {key: value for key, value in payload.items() if not key.startswith("$_")}


def test_collect_brief_outline_and_retrieval_plan_deterministic(sample_ingestion_request) -> None:
    chunks = chunk_document(sample_ingestion_request)
    brief = collect_deck_brief(
        user_request="Create an executive summary",
        audience="Leadership team",
        goal="Summarize the report",
        source_corpus_ids=[sample_ingestion_request.source.id],
        document_title=sample_ingestion_request.document.title,
        source_texts=[chunk.text for chunk in chunks],
    )
    outline = generate_outline(brief)
    retrieval_plan = build_retrieval_plan(brief, outline)

    assert brief.audience == "Leadership team"
    assert outline.outline[0].purpose.value == "title"
    assert outline.outline[1].purpose.value == "content"
    assert outline.outline[1].archetype.value == "executive_summary"
    assert outline.outline[1].template_key == "exec.summary"
    assert any(item.template_key in {"exec.summary", "compare.2col", "headline.evidence", "closing.actions"} for item in outline.outline[1:])
    assert outline.outline[-1].purpose.value in {"summary", "closing"}
    assert all(item.slide_id.startswith("s") for item in outline.outline)
    assert all(item.queries for item in retrieval_plan.retrieval_plan)


def test_collect_brief_preserves_requested_slide_count_above_12(sample_ingestion_request) -> None:
    chunks = chunk_document(sample_ingestion_request)
    brief = collect_deck_brief(
        user_request="Create a detailed appendix-heavy deck",
        audience="Leadership team",
        goal="Summarize the report",
        slide_count_target=18,
        source_corpus_ids=[sample_ingestion_request.source.id],
        document_title=sample_ingestion_request.document.title,
        source_texts=[chunk.text for chunk in chunks],
    )

    assert brief.slide_count_target == 18


def test_generate_outline_avoids_duplicate_headlines_for_pipeline_story() -> None:
    brief = DeckBrief(
        audience="Executive leadership",
        goal="Explain the platform architecture with ingestion retrieval and layout details",
        tone="executive",
        slide_count_target=6,
        source_corpus_ids=["src-arch"],
        questions_for_user=[],
        extensions={
            "document_title": "Architecture Review",
            "key_takeaways": [
                "The platform supports real-time data ingestion from multiple sources.",
                "Template-driven layout improves consistency and reliability.",
                "Automated QA catches overflow and overlap issues before export.",
            ],
            "source_preview": "ingestion retrieval layout assets export architecture pipeline",
        },
    )

    outline = generate_outline(brief)
    content_and_summary = [item.headline for item in outline.outline if item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY, SlidePurpose.CLOSING}]

    assert len(content_and_summary) == len({headline.lower() for headline in content_and_summary})


def test_expand_content_messages_derives_distinct_framings_when_takeaways_are_short() -> None:
    messages = prompt_chain_module._expand_content_messages(
        [
            "Revenue grew 15% year-over-year driven by cloud adoption",
            "Margin improved through automation and better delivery governance",
        ],
        "Improve delivery quality and commercial performance",
        5,
    )

    assert len(messages) == 5
    assert all(" evidence" not in message.lower() for message in messages)
    assert all(" implications" not in message.lower() for message in messages)
    headlines = [prompt_chain_module._short_headline(message, fallback=f"Slide {index}") for index, message in enumerate(messages, start=1)]
    assert len({headline.lower() for headline in headlines}) == len(headlines)


def test_collect_brief_augments_llm_output_with_repo_extensions() -> None:
    class FakeClient:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
            assert schema_name == "DeckBrief"
            return {
                "schema_version": "1.0.0",
                "audience": "HR Leadership",
                "goal": "Prepare for the 26B release",
                "tone": "executive",
                "slide_count_target": 6,
                "source_corpus_ids": ["oracle-release"],
                "questions_for_user": [],
            }

    brief = collect_deck_brief(
        user_request="Create a release readiness briefing",
        audience="HR Leadership",
        goal="Prepare for the 26B release",
        source_corpus_ids=["oracle-release"],
        document_title="Oracle HCM Cloud 26B Release Notes",
        source_texts=[
            "Known Issues. Position Synchronization with Job Profile does not propagate changes to open requisitions.",
            "Upgrade Considerations. Customers upgrading from 25B or earlier should review configuration.",
        ],
        llm_client=FakeClient(),
    )

    assert brief.extensions is not None
    assert brief.extensions["document_title"] == "Oracle HCM Cloud 26B Release Notes"
    assert brief.extensions["deck_archetype"] == "release_readiness"
    assert brief.extensions["key_takeaways"]


def test_execute_retrieval_plan_returns_real_chunk_metadata(sample_ingestion_request, deterministic_embedder) -> None:
    chunks = chunk_document(sample_ingestion_request)
    vector_store = InMemoryVectorStore()
    vector_store.upsert_chunks(chunks, deterministic_embedder.encode([chunk.text for chunk in chunks]))

    brief = collect_deck_brief(
        user_request="Create an executive summary",
        audience="Leadership team",
        goal="Summarize the report",
        source_corpus_ids=[sample_ingestion_request.source.id],
        document_title=sample_ingestion_request.document.title,
        source_texts=[chunk.text for chunk in chunks],
    )
    outline = generate_outline(brief)
    retrieval_plan = build_retrieval_plan(brief, outline)
    results = execute_retrieval_plan(retrieval_plan, vector_store=vector_store, embedder=deterministic_embedder)

    assert results
    first_slide_id, first_hits = next(iter(results.items()))
    assert first_slide_id.startswith("s")
    assert first_hits
    assert first_hits[0].chunk_id in {chunk.chunk_id for chunk in chunks}
    assert first_hits[0].locator


def test_execute_retrieval_plan_excludes_meta_planning_chunks(deterministic_embedder) -> None:
    request = IngestionRequest(
        source=SourceInfo(type=SourceType.UPLOAD, id="src-mixed", uri="/tmp/mixed.md"),
        document=DocumentInfo(
            title="Mixed Notes",
            mime_type="text/markdown",
            language="en",
            elements=[
                ContentObject(
                    doc_id="mixed-doc",
                    element_id="e1",
                    page=1,
                    type=ContentElementType.PARAGRAPH,
                    text="Codex should implement deterministic chunk IDs for asset lookups and endpoint wiring.",
                ),
                ContentObject(
                    doc_id="mixed-doc",
                    element_id="e2",
                    page=1,
                    type=ContentElementType.PARAGRAPH,
                    text="Revenue grew 15% year-over-year as cloud adoption accelerated across enterprise customers.",
                ),
            ],
        ),
        options=IngestionOptions(max_chunk_chars=1200),
    )
    chunks = chunk_document(request)
    vector_store = InMemoryVectorStore()
    vector_store.upsert_chunks(chunks, deterministic_embedder.encode([chunk.text for chunk in chunks]))

    retrieval_plan = RetrievalPlan(
        retrieval_plan=[
            {
                "slide_id": "s1",
                "queries": [
                    {
                        "query": "deterministic chunk ids revenue cloud adoption",
                        "doc_ids": ["src-mixed"],
                        "min_date": None,
                    }
                ],
            }
        ]
    )
    results = execute_retrieval_plan(retrieval_plan, vector_store=vector_store, embedder=deterministic_embedder)

    assert "s1" in results
    assert results["s1"]
    assert all("should implement" not in hit.text.lower() for hit in results["s1"])
    assert all(hit.metadata.get("classification") == "audience_content" for hit in results["s1"])


def test_planning_language_patterns_allow_endpoint_and_api_call_business_content() -> None:
    assert not prompt_chain_module._is_planning_language(
        "Endpoint security adoption expanded across managed devices in the enterprise fleet."
    )
    assert not prompt_chain_module._is_planning_language(
        "API call volume grew 30% after launch as customer usage increased."
    )
    assert prompt_chain_module._is_planning_language(
        "Teams should implement endpoint retries for failed partner requests."
    )
    assert prompt_chain_module._is_planning_language(
        "Platform engineers will configure API call retries for partner integrations."
    )


def test_build_agenda_slide_deduplicates_duplicate_headlines() -> None:
    agenda_item = OutlineItem(
        slide_id="s2",
        purpose=SlidePurpose.CLOSING,
        headline="Agenda",
        message="Review goals, evidence, and next actions.",
        evidence_queries=[],
        template_key="closing.actions",
    )
    outline = OutlineSpec(
        outline=[
            OutlineItem(
                slide_id="s1",
                purpose=SlidePurpose.TITLE,
                headline="Architecture Review",
                message="Introduce the architecture review.",
                evidence_queries=[],
                template_key="title.cover",
            ),
            agenda_item,
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.CONTENT,
                headline="Architecture Components",
                message="Architecture components overview",
                evidence_queries=["architecture components"],
                template_key="exec.summary",
            ),
            OutlineItem(
                slide_id="s4",
                purpose=SlidePurpose.CONTENT,
                headline="Architecture Components",
                message="Another architecture components view",
                evidence_queries=["architecture components detail"],
                template_key="exec.summary",
            ),
            OutlineItem(
                slide_id="s5",
                purpose=SlidePurpose.SUMMARY,
                headline="Key Takeaways",
                message="Summarize the strongest supported points and actions.",
                evidence_queries=[],
                template_key="compare.2col",
            ),
        ]
    )

    slide = prompt_chain_module._build_agenda_slide(item=agenda_item, outline=outline)

    assert slide.blocks[0].content["items"] == ["Architecture Components", "Key Takeaways"]


def test_generate_presentation_spec_is_schema_valid(sample_ingestion_request, deterministic_embedder, style_tokens_payload) -> None:
    chunks = chunk_document(sample_ingestion_request)
    vector_store = InMemoryVectorStore()
    vector_store.upsert_chunks(chunks, deterministic_embedder.encode([chunk.text for chunk in chunks]))
    brief = collect_deck_brief(
        user_request="Create an executive summary",
        audience="Leadership team",
        goal="Summarize the report",
        source_corpus_ids=[sample_ingestion_request.source.id],
        document_title=sample_ingestion_request.document.title,
        source_texts=[chunk.text for chunk in chunks],
    )
    outline = generate_outline(brief)
    retrieval_plan = build_retrieval_plan(brief, outline)
    results = execute_retrieval_plan(retrieval_plan, vector_store=vector_store, embedder=deterministic_embedder)

    spec = generate_presentation_spec(
        brief,
        outline,
        results,
        deck_title=sample_ingestion_request.document.title,
        style_tokens=StyleTokens(**style_tokens_payload),
    )

    assert isinstance(spec, PresentationSpec)
    assert spec.slides
    assert spec.slides[0].layout_intent.template_key == "title.cover"
    assert any(block.source_citations for slide in spec.slides if slide.purpose.value in {"content", "summary"} for block in slide.blocks)
    content_slide = next(slide for slide in spec.slides if slide.purpose.value == "content")
    if content_slide.archetype and content_slide.archetype.value == "executive_summary":
        assert content_slide.layout_intent.template_key == "exec.summary"
        assert content_slide.blocks[2].content["cards"]
    else:
        bullet_block = next(block for block in content_slide.blocks if block.kind.value == "bullets")
        assert bullet_block.content["items"]
        assert len(set(bullet_block.content["items"])) == len(bullet_block.content["items"])
        callout_block = next(block for block in content_slide.blocks if block.kind.value == "callout")
        assert callout_block.content["text"] != f"{content_slide.headline} | Balanced framing"


def test_generate_presentation_spec_upgrades_comparison_slide_to_table(style_tokens_payload) -> None:
    brief = DeckBrief(
        audience="Executive Steering Committee",
        goal="Recommend an integration approach",
        tone="executive",
        slide_count_target=4,
        source_corpus_ids=["oracle-integration"],
        questions_for_user=[],
    )
    outline = OutlineSpec(
        outline=[
            OutlineItem(
                slide_id="s1",
                purpose=SlidePurpose.TITLE,
                headline="Integration Approach",
                message="Introduce the decision.",
                evidence_queries=[],
                template_key="title.cover",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                headline="Compare the options",
                message="Compare integration options across core criteria.",
                evidence_queries=["comparative summary integration options"],
                template_key="headline.evidence",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.SUMMARY,
                headline="Recommendation",
                message="Recommend the preferred path.",
                evidence_queries=[],
                template_key="headline.evidence",
            ),
        ]
    )
    retrieved_chunks = {
        "s2": [
            RetrievedChunk(
                chunk_id="doc:e2:0",
                source_id="oracle-integration",
                locator="oracle-integration:page1",
                text=(
                    "Comparative Summary\n"
                    "Real-Time Delivery\n"
                    "Option 1 (OIC): Supported via event-driven triggers\n"
                    "Option 2 (MuleSoft): Supported via event-driven or polling\n"
                    "Option 3 (File Extract): Not supported, batch only\n\n"
                    "Implementation Complexity\n"
                    "Option 1 (OIC): Medium\n"
                    "Option 2 (MuleSoft): Low to Medium\n"
                    "Option 3 (File Extract): Low\n\n"
                    "Ongoing Maintenance\n"
                    "Option 1 (OIC): Low\n"
                    "Option 2 (MuleSoft): Medium\n"
                    "Option 3 (File Extract): Medium to High\n"
                ),
            )
        ]
    }

    spec = generate_presentation_spec(
        brief,
        outline,
        retrieved_chunks,
        deck_title="Integration Approach",
        style_tokens=StyleTokens(**style_tokens_payload),
    )

    comparison_slide = next(slide for slide in spec.slides if slide.slide_id == "s2")
    assert comparison_slide.layout_intent.template_key == "headline.evidence"
    assert comparison_slide.blocks[0].kind.value == "table"
    assert comparison_slide.blocks[0].content["columns"][0] == "Criterion"
    assert len(comparison_slide.blocks[0].content["rows"]) >= 2


def test_generate_presentation_spec_honors_card_template_with_card_blocks(style_tokens_payload) -> None:
    brief = DeckBrief(
        audience="Oracle consultants",
        goal="Explain the delivery architecture",
        tone="executive",
        slide_count_target=4,
        source_corpus_ids=["oracle-arch"],
        questions_for_user=[],
    )
    outline = OutlineSpec(
        outline=[
            OutlineItem(
                slide_id="s1",
                purpose=SlidePurpose.TITLE,
                headline="Architecture",
                message="Introduce the delivery model.",
                evidence_queries=[],
                template_key="title.cover",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                headline="Core Architecture",
                message="Architecture pipeline components and workflow",
                evidence_queries=["architecture pipeline components workflow"],
                template_key="compare.2col",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.SUMMARY,
                headline="Takeaways",
                message="Summarize the design.",
                evidence_queries=[],
                template_key="compare.2col",
            ),
        ]
    )
    retrieved_chunks = {
        "s2": [
            RetrievedChunk(
                chunk_id="doc:e1:0",
                source_id="oracle-arch",
                locator="oracle-arch:page1",
                text=(
                    "Structured data ingestion accepts documents and records.\n"
                    "RAG-style retrieval grounds each slide in source evidence.\n"
                    "Template-driven layout applies deterministic presentation patterns."
                ),
            )
        ]
    }

    spec = generate_presentation_spec(
        brief,
        outline,
        retrieved_chunks,
        deck_title="Architecture",
        style_tokens=StyleTokens(**style_tokens_payload),
    )

    content_slide = next(slide for slide in spec.slides if slide.slide_id == "s2")
    summary_slide = next(slide for slide in spec.slides if slide.slide_id == "s3")
    assert content_slide.layout_intent.template_key == "compare.2col"
    assert content_slide.blocks[0].kind.value == "bullets"
    assert content_slide.blocks[1].kind.value == "bullets"
    assert summary_slide.layout_intent.template_key in {"compare.2col", "closing.actions", "headline.evidence"}


def test_generate_presentation_spec_builds_executive_summary_slide(style_tokens_payload) -> None:
    brief = DeckBrief(
        audience="Oracle consultants",
        goal="Explain the delivery architecture",
        tone="executive",
        slide_count_target=4,
        source_corpus_ids=["oracle-arch"],
        questions_for_user=[],
        extensions={"one_sentence_thesis": "Hybrid pipelines outperform single-step slide generation."},
    )
    outline = OutlineSpec(
        outline=[
            OutlineItem(
                slide_id="s1",
                purpose=SlidePurpose.TITLE,
                headline="Architecture",
                message="Introduce the delivery model.",
                evidence_queries=[],
                template_key="title.cover",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                archetype="executive_summary",
                headline="Executive Overview",
                message="Hybrid pipeline with six components",
                evidence_queries=["hybrid pipeline six components"],
                template_key="exec.summary",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.SUMMARY,
                headline="Takeaways",
                message="Summarize the design.",
                evidence_queries=[],
                template_key="compare.2col",
            ),
        ]
    )
    retrieved_chunks = {
        "s2": [
            RetrievedChunk(
                chunk_id="doc:e1:0",
                source_id="oracle-arch",
                locator="oracle-arch:page1",
                text=(
                    "Structured data ingestion accepts documents and records.\n"
                    "RAG-style retrieval grounds each slide in source evidence.\n"
                    "Template-driven layout applies deterministic composition.\n"
                    "Asset generation supplies charts and icons.\n"
                    "Deterministic export preserves PPTX fidelity.\n"
                    "Validation catches overlap and consistency issues."
                ),
            )
        ]
    }

    spec = generate_presentation_spec(
        brief,
        outline,
        retrieved_chunks,
        deck_title="Architecture",
        style_tokens=StyleTokens(**style_tokens_payload),
    )

    overview = next(slide for slide in spec.slides if slide.slide_id == "s2")
    assert overview.archetype.value == "executive_summary"
    assert overview.layout_intent.template_key == "exec.summary"
    assert len(overview.blocks) == 3
    assert overview.blocks[2].kind.value == "callout"
    assert len(overview.blocks[2].content["cards"]) == 3
    summary_text = " ".join(overview.blocks[0].content["items"])
    callout_text = overview.blocks[1].content["text"]
    card_texts = [card["text"] for card in overview.blocks[2].content["cards"]]
    assert prompt_chain_module._normalize_phrase(summary_text) != prompt_chain_module._normalize_phrase(callout_text)
    assert all(prompt_chain_module._normalize_phrase(text) != prompt_chain_module._normalize_phrase(summary_text) for text in card_texts)
    assert all(prompt_chain_module._normalize_phrase(text) != prompt_chain_module._normalize_phrase(callout_text) for text in card_texts)


def test_overview_summary_text_falls_back_to_thesis_for_long_prose_fragment() -> None:
    brief = DeckBrief(
        audience="Executive leadership",
        goal="Explain the architecture",
        tone="executive",
        slide_count_target=4,
        source_corpus_ids=["doc"],
        questions_for_user=[],
        extensions={"one_sentence_thesis": "Hybrid pipelines outperform single-step slide generation."},
    )
    item = OutlineItem(
        slide_id="s2",
        purpose=SlidePurpose.CONTENT,
        headline="Executive Overview",
        message="Hybrid pipeline with six components",
        evidence_queries=["hybrid pipeline"],
        template_key="exec.summary",
    )
    slide_chunks = [
        RetrievedChunk(
            chunk_id="doc:e1:0",
            source_id="doc",
            locator="doc:page1",
            text=(
                "Structured data ingestion accepts documents and records, retrieval grounds slide content in source evidence, "
                "template-driven layout applies deterministic composition, asset generation supplies charts and icons, "
                "deterministic export preserves PPTX fidelity, validation catches overlap and consistency issues"
            ),
        )
    ]

    summary = prompt_chain_module._overview_summary_text(item, brief, slide_chunks, used=prompt_chain_module._UsedPhrases())

    assert summary == "Hybrid pipelines outperform single-step slide generation."


def test_overview_summary_text_prefers_two_complete_sentences() -> None:
    brief = DeckBrief(
        audience="Executive leadership",
        goal="Explain the architecture",
        tone="executive",
        slide_count_target=4,
        source_corpus_ids=["doc"],
        questions_for_user=[],
        extensions={"one_sentence_thesis": "Hybrid pipelines outperform single-step slide generation."},
    )
    item = OutlineItem(
        slide_id="s2",
        purpose=SlidePurpose.CONTENT,
        headline="Executive Overview",
        message="Hybrid pipeline with six components",
        evidence_queries=["hybrid pipeline"],
        template_key="exec.summary",
    )
    slide_chunks = [
        RetrievedChunk(
            chunk_id="doc:e1:0",
            source_id="doc",
            locator="doc:page1",
            text=(
                "Structured data ingestion accepts documents and records for downstream generation. "
                "RAG-style retrieval grounds each slide in evidence from the source corpus. "
                "Template-driven layout applies deterministic composition and spacing."
            ),
        )
    ]

    summary = prompt_chain_module._overview_summary_text(item, brief, slide_chunks, used=prompt_chain_module._UsedPhrases())

    assert summary.count(".") <= 2
    assert "Structured data ingestion accepts documents and records for downstream generation" in summary
    assert "RAG-style retrieval grounds each slide in evidence from the source corpus" in summary
    assert "Template-driven layout applies deterministic composition and spacing" not in summary


def test_executive_summary_slide_keeps_body_and_callout_distinct_when_chunks_are_sparse() -> None:
    brief = DeckBrief(
        audience="Executive leadership",
        goal="Explain the platform architecture and business value",
        tone="executive",
        slide_count_target=4,
        source_corpus_ids=["doc"],
        questions_for_user=[],
        extensions={"one_sentence_thesis": "Hybrid pipelines outperform single-step slide generation."},
    )
    item = OutlineItem(
        slide_id="s2",
        purpose=SlidePurpose.CONTENT,
        archetype="executive_summary",
        headline="Executive Overview",
        message="Hybrid pipeline with six components",
        evidence_queries=["hybrid pipeline"],
        template_key="exec.summary",
    )
    slide_chunks = [
        RetrievedChunk(
            chunk_id="doc:e1:0",
            source_id="doc",
            locator="doc:page1",
            text="Structured data ingestion accepts documents and records, retrieval grounds slide content in source evidence, template-driven layout applies deterministic composition",
        )
    ]

    slide = prompt_chain_module._executive_summary_slide(
        item=item,
        brief=brief,
        tone_label="Balanced framing",
        slide_chunks=slide_chunks,
        citations=[{"source_id": "doc", "locator": "doc:page1"}],
        summary_items=["Hybrid pipelines outperform single-step slide generation."],
    )

    summary_text = " ".join(slide.blocks[0].content["items"])
    callout_text = slide.blocks[1].content["text"]

    assert not prompt_chain_module._phrases_are_near_duplicate(
        prompt_chain_module._normalize_phrase(summary_text),
        prompt_chain_module._normalize_phrase(callout_text),
    )


def test_executive_summary_slide_has_no_footer_block() -> None:
    brief = DeckBrief(
        audience="Executive leadership",
        goal="Explain the platform architecture",
        tone="executive",
        slide_count_target=4,
        source_corpus_ids=["doc"],
        questions_for_user=[],
        extensions={"one_sentence_thesis": "Hybrid pipelines outperform single-step slide generation."},
    )
    item = OutlineItem(
        slide_id="s2",
        purpose=SlidePurpose.CONTENT,
        archetype="executive_summary",
        headline="Executive Overview",
        message="Hybrid pipeline with six components",
        evidence_queries=["hybrid pipeline"],
        template_key="exec.summary",
    )
    slide = prompt_chain_module._executive_summary_slide(
        item=item,
        brief=brief,
        tone_label="Balanced framing",
        slide_chunks=[],
        citations=[],
        summary_items=["Hybrid pipelines outperform single-step slide generation."],
    )

    assert len(slide.blocks) == 3
    assert [block.kind.value for block in slide.blocks] == ["bullets", "callout", "callout"]


def test_used_phrases_tracks_normalized_matches() -> None:
    used = prompt_chain_module._UsedPhrases()
    used.mark("RAG-style retrieval grounds each slide in source evidence.")
    assert used.is_used("rag style retrieval grounds each slide in source evidence")
    used.mark_all(["Template-driven layout applies deterministic composition."])
    assert used.is_used("template driven layout applies deterministic composition")


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("# Business content Executive Overview", ""),
        ("Executive Overview of Q3 Results", "Executive Overview of Q3 Results"),
        ("**Revenue** grew 15% year over year", "Revenue grew 15% year over year"),
        ("> Quoted insight about growth", "Quoted insight about growth"),
        ("- Bullet item about strategy", "Bullet item about strategy"),
        (
            "Business content Executive Overview Revenue grew 15% year-over-year driven by cloud adoption",
            "Revenue grew 15% year-over-year driven by cloud adoption",
        ),
        ("Plain text without markdown", "Plain text without markdown"),
    ],
)
def test_clean_candidate_phrase_strips_source_markup(raw_text: str, expected: str) -> None:
    assert prompt_chain_module._clean_candidate_phrase(raw_text) == expected


def test_clean_candidate_phrase_drops_planning_language_after_section_label_strip() -> None:
    assert prompt_chain_module._clean_candidate_phrase("Planning notes Codex should implement deterministic chunk IDs") == ""


def test_derive_takeaways_skips_planning_language_and_section_labels() -> None:
    takeaways = prompt_chain_module._derive_takeaways(
        [
            "Planning notes Codex should implement deterministic chunk IDs for asset lookups.",
            "Business content Executive Overview Revenue grew 15% year-over-year driven by cloud adoption.",
            "The platform supports real-time data ingestion from multiple sources.",
        ],
        "Summarize platform capabilities",
    )

    assert any("Revenue grew 15% year-over-year driven by cloud adoption" == takeaway for takeaway in takeaways)
    assert any("The platform supports real-time data ingestion from multiple sources" == takeaway for takeaway in takeaways)
    assert all("codex should" not in takeaway.lower() for takeaway in takeaways)
    assert all("business content" not in takeaway.lower() for takeaway in takeaways)


def test_semantic_cards_from_chunks_deduplicates_card_descriptions() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id="doc:e1:0",
            source_id="doc",
            locator="doc:page1",
            text="Template-driven layout improves consistency, while retrieval grounds slide content in source evidence.",
        )
    ]

    cards = prompt_chain_module._semantic_cards_from_chunks(chunks, desired_count=3, mode="overview")
    texts = [card["text"] for card in cards]

    assert len(texts) == len(set(texts))
    assert any(
        prompt_chain_module._normalize_phrase(text)
        == prompt_chain_module._normalize_phrase(
            "Template-driven layout improves consistency, while retrieval grounds slide content in source evidence."
        )
        for text in texts
    )


def test_semantic_cards_from_chunks_strip_section_labels_from_card_text() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id="doc:e1:0",
            source_id="doc",
            locator="doc:page1",
            text="# Business content Executive Overview Revenue grew 15% year-over-year, driven by cloud adoption across enterprise customers.",
        )
    ]

    cards = prompt_chain_module._semantic_cards_from_chunks(chunks, desired_count=1, mode="overview")

    assert prompt_chain_module._normalize_phrase(cards[0]["text"]) == prompt_chain_module._normalize_phrase(
        "Revenue grew 15% year-over-year, driven by cloud adoption across enterprise customers."
    )


def test_compact_cards_does_not_pad_placeholder_titles() -> None:
    cards = prompt_chain_module._compact_cards(
        [
            "Revenue growth accelerated through cloud adoption",
            "Margin improved through workflow automation",
        ],
        title_prefix="Capability",
        desired_count=6,
    )

    assert len(cards) == 2
    assert all(not card["title"].startswith("Capability ") for card in cards)


def test_cards_from_points_does_not_pad_placeholder_entries() -> None:
    cards = prompt_chain_module._cards_from_points(
        ["Delivery quality improved through deterministic templates"],
        title_prefix="Capability",
    )

    assert len(cards) == 1
    assert cards[0]["text"] == "Delivery quality improved through deterministic templates"


def test_kpi_points_from_bullets_does_not_pad_placeholder_values() -> None:
    values = prompt_chain_module._kpi_points_from_bullets(["Revenue up 15%", "Margin up 4 points"])

    assert values == ["Revenue up 15%", "Margin up 4 points"]


def test_deduplicate_slide_blocks_replaces_duplicate_text_block(style_tokens_payload) -> None:
    spec = PresentationSpec(
        title="Architecture",
        audience="Oracle consultants",
        language="en-US",
        theme=DeckTheme(name="Auto PPT", style_tokens=StyleTokens(**style_tokens_payload)),
        slides=[
            SlideSpec(
                slide_id="s1",
                purpose=SlidePurpose.CONTENT,
                layout_intent=LayoutIntent(template_key="headline.evidence", strict_template=True),
                headline="Executive Overview",
                blocks=[
                    PresentationBlock(block_id="b1", kind=PresentationBlockKind.TEXT, content={"text": "Repeated architecture summary"}),
                    PresentationBlock(block_id="b2", kind=PresentationBlockKind.TEXT, content={"text": "Repeated architecture summary"}),
                ],
            )
        ],
    )
    retrieved_chunks = {
        "s1": [
            RetrievedChunk(
                chunk_id="doc:e1:0",
                source_id="oracle-arch",
                locator="oracle-arch:page1",
                text=(
                    "Repeated architecture summary.\n"
                    "Deterministic export preserves PPTX fidelity.\n"
                    "Validation catches overlap and consistency issues."
                ),
            )
        ]
    }

    deduped = prompt_chain_module._deduplicate_slide_blocks(spec, retrieved_chunks)
    blocks = deduped.slides[0].blocks
    assert len(blocks) >= 1
    assert prompt_chain_module._normalize_phrase(blocks[0].content["text"]) != prompt_chain_module._normalize_phrase(blocks[-1].content["text"]) or len(blocks) == 1


def test_generate_presentation_spec_builds_executive_summary_slide(style_tokens_payload) -> None:
    brief = DeckBrief(
        audience="Oracle consultants",
        goal="Explain the architecture pipeline",
        tone="executive",
        slide_count_target=5,
        source_corpus_ids=["oracle-arch"],
        questions_for_user=[],
        extensions={"one_sentence_thesis": "A deterministic pipeline improves delivery quality."},
    )
    outline = OutlineSpec(
        outline=[
            OutlineItem(
                slide_id="s1",
                purpose=SlidePurpose.TITLE,
                headline="Architecture",
                message="Introduce the model.",
                evidence_queries=[],
                template_key="title.cover",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                archetype="executive_summary",
                headline="Architecture Components",
                message="Six component pipeline",
                evidence_queries=["ingestion retrieval layout assets export validation"],
                template_key="exec.summary",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.SUMMARY,
                headline="Takeaways",
                message="Summarize the design.",
                evidence_queries=[],
                template_key="compare.2col",
            ),
        ]
    )
    retrieved_chunks = {
        "s2": [
            RetrievedChunk(
                chunk_id="doc:e2:0",
                source_id="oracle-arch",
                locator="oracle-arch:page2",
                text=(
                    "Structured data ingestion normalizes incoming evidence.\n"
                    "RAG-style retrieval grounds slide content.\n"
                    "Multi-step planning shapes messages and outline.\n"
                    "Template-driven layout resolves composition.\n"
                    "Asset generation supplies visuals and charts.\n"
                    "Deterministic export preserves PPTX fidelity."
                ),
            )
        ]
    }

    spec = generate_presentation_spec(
        brief,
        outline,
        retrieved_chunks,
        deck_title="Architecture",
        style_tokens=StyleTokens(**style_tokens_payload),
    )

    architecture_slide = next(slide for slide in spec.slides if slide.slide_id == "s2")
    assert architecture_slide.archetype.value == "executive_summary"
    assert architecture_slide.layout_intent.template_key == "exec.summary"
    assert len(architecture_slide.blocks) == 3
    assert architecture_slide.blocks[0].kind.value == "bullets"
    assert architecture_slide.blocks[1].kind.value == "callout"
    assert len(architecture_slide.blocks[2].content["cards"]) == 3


def test_generate_presentation_spec_llm_branch_rebuilds_opening_and_cards(style_tokens_payload) -> None:
    brief = DeckBrief(
        audience="Oracle consultants",
        goal="Explain how AI presentation systems ingest data and generate polished decks",
        tone="executive",
        slide_count_target=4,
        source_corpus_ids=["oracle-arch"],
        questions_for_user=[],
        extensions={"document_title": "AI Presentation Systems", "one_sentence_thesis": "Hybrid pipelines outperform single-step slide generation."},
    )
    outline = OutlineSpec(
        outline=[
            OutlineItem(
                slide_id="s1",
                purpose=SlidePurpose.TITLE,
                headline="How AI Presentation Systems Work",
                message="Open with the implementation point of view.",
                evidence_queries=[],
                template_key="title.cover",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                archetype="executive_summary",
                headline="Executive Overview",
                message="Hybrid pipeline with six components",
                evidence_queries=["hybrid pipeline six components"],
                template_key="exec.summary",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.CONTENT,
                headline="Design Quality Strategies",
                message="Compare the main design quality strategies",
                evidence_queries=["template first rule based free form design quality strategies"],
                template_key="compare.2col",
            ),
        ]
    )
    retrieved_chunks = {
        "s2": [
            RetrievedChunk(
                chunk_id="doc:e1:0",
                source_id="oracle-arch",
                locator="oracle-arch:page1",
                text=(
                    "Structured data ingestion accepts documents and records.\n"
                    "RAG-style retrieval grounds each slide in source evidence.\n"
                    "Template-driven layout applies deterministic composition.\n"
                    "Asset generation supplies charts and icons.\n"
                    "Deterministic export preserves PPTX fidelity.\n"
                    "Validation catches overlap and consistency issues."
                ),
            )
        ],
        "s3": [
            RetrievedChunk(
                chunk_id="doc:e2:0",
                source_id="oracle-arch",
                locator="oracle-arch:page2",
                text="Template-first layout reduces failures. Rule-based layout improves polish. Free-form generation expands options.",
            )
        ],
    }

    class FakeClient:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
            assert schema_name == "PresentationSpec"
            return {
                "schema_version": "1.0.0",
                "title": "Generated Presentation",
                "audience": "General audience",
                "language": "en-US",
                "theme": {
                    "name": "Auto PPT",
                    "style_tokens": StyleTokens(**style_tokens_payload).model_dump(),
                },
                "slides": [
                    {
                        "slide_id": "s1",
                        "purpose": "title",
                        "layout_intent": {"template_key": "headline.evidence", "strict_template": True},
                        "headline": "Slide 1",
                        "speaker_notes": "",
                        "blocks": [
                            {
                                "block_id": "b1",
                                "kind": "text",
                                "content": {"text": "Introduction"},
                                "source_citations": [],
                                "asset_refs": [],
                            }
                        ],
                    },
                    {
                        "slide_id": "s2",
                        "purpose": "content",
                        "layout_intent": {"template_key": "headline.evidence", "strict_template": True},
                        "headline": "Slide 2",
                        "speaker_notes": "",
                        "blocks": [
                            {
                                "block_id": "b1",
                                "kind": "text",
                                "content": {"text": "Hybrid pipelines improve delivery quality"},
                                "source_citations": [{"source_id": "oracle-arch", "locator": "oracle-arch:page1"}],
                                "asset_refs": [],
                            }
                        ],
                    },
                    {
                        "slide_id": "s3",
                        "purpose": "content",
                        "layout_intent": {"template_key": "headline.evidence", "strict_template": True},
                        "headline": "Design Quality Strategies",
                        "speaker_notes": "",
                        "blocks": [
                            {
                                "block_id": "b1",
                                "kind": "text",
                                "content": {
                                    "text": "[{'title': 'Template-First', 'value': 'Fixed layouts with placeholders', 'description': 'Reduces layout failures.'}, {'title': 'Rule-Based', 'value': 'Auto-resize and align', 'description': 'Enhances visual polish.'}, {'title': 'Free-Form', 'value': 'Proposes structures', 'description': 'Enforces constraints.'}]"
                                },
                                "source_citations": [{"source_id": "oracle-arch", "locator": "oracle-arch:page2"}],
                                "asset_refs": [],
                            }
                        ],
                    },
                ],
                "questions_for_user": [],
            }

    spec = generate_presentation_spec(
        brief,
        outline,
        retrieved_chunks,
        deck_title="How AI Presentation Systems Work",
        style_tokens=StyleTokens(**style_tokens_payload),
        llm_client=FakeClient(),
    )

    title_slide = next(slide for slide in spec.slides if slide.slide_id == "s1")
    overview_slide = next(slide for slide in spec.slides if slide.slide_id == "s2")
    strategies_slide = next(slide for slide in spec.slides if slide.slide_id == "s3")

    assert title_slide.layout_intent.template_key == "title.cover"
    assert title_slide.blocks[0].content["subtitle"]
    assert "Oracle" in title_slide.blocks[0].content["subtitle"]
    assert title_slide.blocks[0].content["presenter"] == "Oracle consultants"
    assert overview_slide.layout_intent.template_key == "exec.summary"
    assert overview_slide.archetype.value == "executive_summary"
    assert len(overview_slide.blocks[2].content["cards"]) == 3
    assert strategies_slide.layout_intent.template_key == "headline.evidence"
    assert strategies_slide.blocks[0].kind.value == "callout"
    assert strategies_slide.blocks[0].content["cards"][0]["title"] == "Template-First"


def test_revise_for_design_quality_preserves_identity_and_rejects_bad_payload(
    tmp_path: Path,
    make_presentation_spec,
    make_slide,
    make_block,
) -> None:
    spec = PresentationSpec(
        **make_presentation_spec(
            slides=[make_slide(blocks=[make_block(content={"text": "Revenue improved this quarter."})])]
        )
    )
    artifact_path = tmp_path / "slide.png"
    artifact_path.write_bytes(b"x")

    class BadClient:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
            revised = spec.model_dump()
            revised["slides"][0]["slide_id"] = "s9"
            return {"schema_version": "1.0.0", "applied": True, "rationale": ["bad"], "presentation_spec": revised}

    with pytest.raises(ValueError, match="preserve slide/block identity"):
        revise_for_design_quality(
            spec,
            qa_report_json="{}",
            render_artifact_path=artifact_path,
            llm_client=BadClient(),
            enabled=True,
        )


@pytest.mark.parametrize(
    ("fixture_name", "model_type"),
    [
        ("brief_product_launch_good.json", DeckBrief),
        ("brief_incident_retro_good.json", DeckBrief),
        ("brief_oracle_hcm_good.json", DeckBrief),
        ("brief_q1_review_good.json", DeckBrief),
        ("outline_oracle_hcm_good.json", OutlineSpec),
        ("outline_q1_review_good.json", OutlineSpec),
        ("outline_bad_topic_headlines.json", OutlineSpec),
        ("retrieval_oracle_hcm_good.json", RetrievalPlan),
        ("retrieval_q1_review_good.json", RetrievalPlan),
        ("retrieval_bad_vague.json", RetrievalPlan),
        ("spec_oracle_hcm_good.json", PresentationSpec),
        ("spec_product_launch_good.json", PresentationSpec),
    ],
)
def test_gold_planning_fixtures_validate_against_declared_models(fixture_name: str, model_type: type) -> None:
    fixture_path = GOLD_FIXTURE_DIR / fixture_name
    payload = _load_gold_fixture(fixture_path)

    parsed = model_type(**payload)

    assert parsed.schema_version == "1.0.0"


def test_dense_bad_spec_fixture_is_rejected_by_presentation_schema() -> None:
    payload = _load_gold_fixture(GOLD_FIXTURE_DIR / "spec_bad_dense.json")

    with pytest.raises(ValidationError, match="requires source_citations|exceeds 70-word content cap"):
        PresentationSpec(**payload)
