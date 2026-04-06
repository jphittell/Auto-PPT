---
name: pptx-indexing
description: Encode chunks and manage retrieval metadata for this repo's vector layer. Use when editing `pptx_gen/indexing`, changing embedding behavior, updating Chroma query/upsert logic, or refining retrieval payloads consumed by planning and tested by ingestion or pipeline flows.
---

# PPTX Indexing

Read `AGENTS.md`, [embedder.py](C:/Users/jphit/.codex/Projects/Auto-PPT/pptx_gen/indexing/embedder.py), [vector_store.py](C:/Users/jphit/.codex/Projects/Auto-PPT/pptx_gen/indexing/vector_store.py), and the ingestion/planning schemas before editing this area.

## Preserve

- Keep embeddings deterministic at the interface boundary: `encode(texts) -> list[list[float]]`.
- Preserve metadata round-trips for `chunk_id`, `source_id`, `locator`, `element_id`, `element_type`, and `page`.
- Keep vector-store behavior separate from parsing and planning logic.
- Return retrieval payloads in shapes that planning can validate directly, especially `RetrievedChunk`.

## Avoid

- Do not hide missing metadata in retrieval results.
- Do not move citation logic into the vector store.
- Do not make indexing code depend on prompt files or renderer contracts.
- Update indexing or pipeline tests whenever embedding or query result shape changes.
