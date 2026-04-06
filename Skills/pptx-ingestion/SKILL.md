---
name: pptx-ingestion
description: Parse PDFs and text into typed `ContentObject` elements and deterministic chunk metadata for this repo. Use when editing `pptx_gen/ingestion`, changing parser fallback behavior, adjusting provenance or PII-redaction rules, or updating ingestion schemas and tests.
---

# PPTX Ingestion

Read `AGENTS.md`, [schemas.py](C:/Users/jphit/.codex/Projects/Auto-PPT/pptx_gen/ingestion/schemas.py), [parser.py](C:/Users/jphit/.codex/Projects/Auto-PPT/pptx_gen/ingestion/parser.py), and [chunker.py](C:/Users/jphit/.codex/Projects/Auto-PPT/pptx_gen/ingestion/chunker.py) before editing this area.

## Preserve

- Deterministic parsing only. Do not add any LLM calls here.
- Prefer Unstructured for structure-first parsing, but preserve the current lightweight PDF fallback in `parser.py` so tests can run without the full inference stack.
- Keep `chunk_id` in the format `{doc_id}:{element_id}:{chunk_index}` and `locator` in the format `{doc_id}:page{page}`.
- Preserve the current normalized element types: `title`, `heading`, `paragraph`, `list_item`, `table`, `figure`, `caption`.
- Keep `IngestionRequest` and nested models strict with `ConfigDict(extra="forbid")`.
- Update [test_ingestion.py](C:/Users/jphit/.codex/Projects/Auto-PPT/tests/test_ingestion.py) and [conftest.py](C:/Users/jphit/.codex/Projects/Auto-PPT/tests/conftest.py) whenever parser, chunking, or provenance behavior changes.

## Avoid

- Do not index vectors from this skill; hand off clean chunks to the indexing layer.
- Do not drop parseable content silently. Map unknown element types to `paragraph`.
- Do not remove PII redaction defaults unless the contract changes everywhere that consumes these chunks.
