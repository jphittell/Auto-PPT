from __future__ import annotations

import pytest

from pptx_gen.ingestion.chunker import chunk_document
from pptx_gen.ingestion.parser import PDFDependencyError, parse_source
from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.pipeline import ingest_and_index


def test_parse_pdf_preserves_provenance_and_types(sample_pdf_path) -> None:
    try:
        request = parse_source(sample_pdf_path)
    except PDFDependencyError as exc:
        pytest.skip(str(exc))

    assert request.document.elements
    assert len({element.element_id for element in request.document.elements}) == len(request.document.elements)
    assert all(element.doc_id == request.document.elements[0].doc_id for element in request.document.elements)
    assert any(element.type.value in {"title", "heading", "paragraph"} for element in request.document.elements)


def test_chunker_redacts_pii_and_deduplicates(sample_ingestion_request) -> None:
    chunks = chunk_document(sample_ingestion_request)

    assert len(chunks) == 2
    assert all("sample@example.com" not in chunk.text for chunk in chunks)
    assert any("[REDACTED_EMAIL]" in chunk.text for chunk in chunks)


def test_ingest_and_index_round_trip_with_chroma(sample_pdf_path, deterministic_embedder) -> None:
    try:
        vector_store = InMemoryVectorStore()
        result = ingest_and_index(
            sample_pdf_path,
            embedder=deterministic_embedder,
            vector_store=vector_store,
        )
    except PDFDependencyError as exc:
        pytest.skip(str(exc))

    assert result.n_elements == len(result.ingestion_request.document.elements)
    assert result.n_chunks == len(result.chunks)
    assert result.chunk_ids == [chunk.chunk_id for chunk in result.chunks]

    element_types = {element.element_id: element.type for element in result.ingestion_request.document.elements}
    for chunk in result.chunks:
        doc_id, element_id, chunk_index = chunk.chunk_id.split(":")
        assert doc_id == result.doc_id
        assert element_id == chunk.element_id
        assert int(chunk_index) == chunk.chunk_index
        assert chunk.locator == f"{result.doc_id}:page{chunk.page or 1}"
        assert len(chunk.text) <= result.ingestion_request.options.max_chunk_chars
        assert chunk.element_type == element_types[chunk.element_id]

    query_embedding = deterministic_embedder.encode([result.chunks[0].text])[0]
    hits = vector_store.query(query_embedding=query_embedding, n_results=1)

    assert hits
    assert hits[0].chunk_id == result.chunks[0].chunk_id
    assert hits[0].source_id == result.source_id
    assert hits[0].locator == result.chunks[0].locator

