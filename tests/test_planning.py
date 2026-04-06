from __future__ import annotations

from pathlib import Path

import pytest

from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.ingestion.chunker import chunk_document
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
    OutlineItem,
    OutlineSpec,
    PresentationSpec,
    RetrievedChunk,
    SlidePurpose,
)


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
    assert outline.outline[1].purpose.value == "agenda"
    assert outline.outline[2].archetype.value == "executive_overview"
    assert outline.outline[2].template_key == "executive.overview"
    assert any(item.template_key in {"architecture.grid", "content.3col.cards"} for item in outline.outline[2:])
    assert outline.outline[-1].purpose.value == "summary"
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
    assert spec.slides[0].layout_intent.template_key == "title.hero"
    assert any(block.source_citations for slide in spec.slides if slide.purpose.value in {"content", "summary"} for block in slide.blocks)
    content_slide = next(slide for slide in spec.slides if slide.purpose.value == "content")
    if content_slide.archetype and content_slide.archetype.value == "executive_overview":
        assert content_slide.layout_intent.template_key == "executive.overview"
        assert len(content_slide.blocks[2].content["cards"]) == 6
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
                template_key="title.hero",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                headline="Compare the options",
                message="Compare integration options across core criteria.",
                evidence_queries=["comparative summary integration options"],
                template_key="content.1col",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.SUMMARY,
                headline="Recommendation",
                message="Recommend the preferred path.",
                evidence_queries=[],
                template_key="content.1col",
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
    assert comparison_slide.layout_intent.template_key == "table.full"
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
                template_key="title.hero",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                headline="Core Architecture",
                message="Architecture pipeline components and workflow",
                evidence_queries=["architecture pipeline components workflow"],
                template_key="content.3col.cards",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.SUMMARY,
                headline="Takeaways",
                message="Summarize the design.",
                evidence_queries=[],
                template_key="content.3col.cards",
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
    assert content_slide.layout_intent.template_key == "content.3col.cards"
    assert content_slide.blocks[0].kind.value == "callout"
    assert len(content_slide.blocks[0].content["cards"]) == 3
    assert summary_slide.layout_intent.template_key == "content.3col.cards"
    assert summary_slide.blocks[0].kind.value == "callout"


def test_generate_presentation_spec_builds_executive_overview_slide(style_tokens_payload) -> None:
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
                template_key="title.hero",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                archetype="executive_overview",
                headline="Executive Overview",
                message="Hybrid pipeline with six components",
                evidence_queries=["hybrid pipeline six components"],
                template_key="executive.overview",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.SUMMARY,
                headline="Takeaways",
                message="Summarize the design.",
                evidence_queries=[],
                template_key="content.3col.cards",
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
    assert overview.archetype.value == "executive_overview"
    assert overview.layout_intent.template_key == "executive.overview"
    assert len(overview.blocks) == 4
    assert overview.blocks[2].kind.value == "callout"
    assert len(overview.blocks[2].content["cards"]) == 6


def test_generate_presentation_spec_builds_architecture_grid_slide(style_tokens_payload) -> None:
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
                template_key="title.hero",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                archetype="architecture_grid",
                headline="Architecture Components",
                message="Six component pipeline",
                evidence_queries=["ingestion retrieval layout assets export validation"],
                template_key="architecture.grid",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.SUMMARY,
                headline="Takeaways",
                message="Summarize the design.",
                evidence_queries=[],
                template_key="content.3col.cards",
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
    assert architecture_slide.archetype.value == "architecture_grid"
    assert architecture_slide.layout_intent.template_key == "architecture.grid"
    assert len(architecture_slide.blocks) == 3
    assert architecture_slide.blocks[1].kind.value == "callout"
    assert len(architecture_slide.blocks[1].content["cards"]) == 6


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
                template_key="title.hero",
            ),
            OutlineItem(
                slide_id="s2",
                purpose=SlidePurpose.CONTENT,
                archetype="executive_overview",
                headline="Executive Overview",
                message="Hybrid pipeline with six components",
                evidence_queries=["hybrid pipeline six components"],
                template_key="executive.overview",
            ),
            OutlineItem(
                slide_id="s3",
                purpose=SlidePurpose.CONTENT,
                headline="Design Quality Strategies",
                message="Compare the main design quality strategies",
                evidence_queries=["template first rule based free form design quality strategies"],
                template_key="content.3col.cards",
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
                        "layout_intent": {"template_key": "content.1col", "strict_template": True},
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
                        "layout_intent": {"template_key": "content.1col", "strict_template": True},
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
                        "layout_intent": {"template_key": "content.1col", "strict_template": True},
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

    assert title_slide.layout_intent.template_key == "title.hero"
    assert title_slide.blocks[0].content["subtitle"]
    assert "Oracle" in title_slide.blocks[0].content["subtitle"]
    assert title_slide.blocks[0].content["presenter"] == "Oracle consultants"
    assert overview_slide.layout_intent.template_key == "executive.overview"
    assert overview_slide.archetype.value == "executive_overview"
    assert len(overview_slide.blocks[2].content["cards"]) == 6
    assert strategies_slide.layout_intent.template_key == "content.3col.cards"
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
