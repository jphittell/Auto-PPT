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
    assert outline.outline[-1].purpose.value == "summary"
    assert all(item.slide_id.startswith("s") for item in outline.outline)
    assert all(item.queries for item in retrieval_plan.retrieval_plan)


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
