# Auto-PPT

Phase 1 bootstrap for an AI presentation generation pipeline that:

- ingests PDF and plain-text content into normalized typed elements,
- chunks and indexes those elements with provenance-preserving metadata,
- defines strict JSON contracts for planning, layout, assets, rendering, and QA,
- prepares deterministic PPTX rendering boundaries without requiring PowerPoint.

## Current scope

The implemented path in this phase is:

1. Parse a local PDF or plain-text file.
2. Normalize content into `ContentObject` elements.
3. Redact common PII patterns and deduplicate repeated elements.
4. Chunk by element with deterministic chunk ids and locators.
5. Embed chunks with Sentence Transformers.
6. Upsert chunks into an in-memory Chroma collection.

Downstream planning, layout, assets, rendering, and QA entrypoints are scaffolded with typed TODO boundaries so later sessions can continue from stable interfaces.

## Installation

Base install:

```bash
pip install -e .
```

PDF support:

```bash
pip install -e ".[pdf]"
```

Full local-inference extras for heavier PDF parsing:

```bash
pip install -e ".[full]"
```

## CLI

Ingest and index a local document:

```bash
pptx-gen ingest path/to/document.pdf
```

The `generate` command is intentionally stubbed in Phase 1.
