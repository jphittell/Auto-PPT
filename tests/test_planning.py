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
from pptx_gen.planning.schemas import PresentationSpec


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
