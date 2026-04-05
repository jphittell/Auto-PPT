# AGENTS.md — AI PPTX Generation System

## Project overview

This repo implements a six-stage, schema-driven pipeline for generating visually polished `.pptx`
presentations from raw source material (PDFs, text, URLs, structured data). It is modeled after
the hybrid architectures used by production AI presentation tools (Gamma, Beautiful.ai, Microsoft
Copilot in PowerPoint).

The pipeline is **not** a single LLM call that emits slide content. It is a sequence of discrete
services, each with strict JSON input/output contracts defined as Pydantic v2 models.

---

## Pipeline stages (in order)

| # | Service | Input | Output |
|---|---------|-------|--------|
| 1 | **Ingestion** | Raw files / URLs / records | `IngestionRequest` + `ContentObject[]` |
| 2 | **Indexing** | `ContentObject[]` | Vector index + metadata store |
| 3 | **Planning** | User brief + vector index | `PresentationSpec` (SlideSpec JSON) |
| 4 | **Layout** | `PresentationSpec` | `ResolvedDeckLayout` |
| 5 | **Assets** | Block `data_ref` fields | Cached local image/chart paths |
| 6 | **Renderer** | `ResolvedDeckLayout` + assets | `.pptx` file + `QAReport` |

Each stage reads the previous stage's schema output. **No stage may reach into another stage's
internal logic or bypass its schema boundary.**

---

## Absolute rules — always follow these

1. **Schema-first.** Every inter-service boundary uses a Pydantic v2 model defined in that
   service's `schemas.py`. All models use `model_config = ConfigDict(extra='forbid')`. Do not
   pass raw dicts between services.

2. **No remote URLs in the PPTX.** All external image assets must be downloaded and cached
   locally by the Asset service before the Renderer runs. Image URLs expire; embedding them
   directly causes broken presentations.

3. **JSON mode for all LLM calls.** Every call to the LLM in the Planning service must use
   structured output / JSON mode. The LLM must never return free-form text where a schema is
   expected.

4. **Citations are immutable after Step 4.** The Step 5 design revision prompt may add citations
   but must never remove them. Citation coverage is a QA gate.

5. **QA before artifact delivery.** `renderer/qa.py` validators (overflow, overlap, alignment,
   contrast, citation coverage, asset accessibility) must all pass before the `.pptx` is returned.
   A failing QA check raises, it does not warn.

6. **Outline-first, always.** The Planning service runs the full five-step chain in order. Do not
   skip or merge steps. Step 2 (outline) must complete and be validated before Step 3 (retrieval
   planning) begins.

---

## Project structure

```
pptx_gen/
  ingestion/
    parser.py          # structure-first parsing via unstructured
    chunker.py         # element chunking + PII redaction
    schemas.py         # IngestionRequest, ContentObject
  indexing/
    embedder.py        # SBERT encoding
    vector_store.py    # faiss/chromadb wrapper
    schemas.py         # ChunkRecord, RetrievalResult
  planning/
    prompt_chain.py    # five-step orchestration loop
    prompts/           # one .txt or .py file per step
    schemas.py         # DeckBrief, Outline, RetrievalPlan, PresentationSpec
  layout/
    resolver.py        # template_key → geometry → ResolvedDeckLayout
    templates.py       # named template registry
    schemas.py         # ResolvedDeckLayout, LayoutElement, StyleTokens
  assets/
    resolver.py        # image/chart download + local caching
    chart_renderer.py  # matplotlib/plotly → PNG
  renderer/
    pptx_exporter.py   # python-pptx render loop
    qa.py              # QAReport validators
    schemas.py         # QAReport, QAIssue
  pipeline.py          # orchestrates all six services end-to-end
  cli.py               # Click CLI: `ingest` and `generate` commands
tests/
  test_ingestion.py
  test_indexing.py
  test_planning.py
  test_layout.py
  test_renderer.py
  test_pipeline.py     # only end-to-end tests live here
```

---

## Tech stack

| Purpose | Library |
|---------|---------|
| Schema validation | `pydantic` v2 |
| Document parsing | `unstructured` |
| Embeddings | `sentence-transformers` (SBERT bi-encoder) |
| Vector index | `faiss-cpu` or `chromadb` |
| LLM calls | `openai` with JSON mode, or `litellm` for model-agnostic use |
| PPTX generation | `python-pptx` |
| Chart rendering | `matplotlib` or `plotly` |
| CLI | `click` |
| Tests | `pytest` |

---

## Key schema files (read these before editing any service)

- `ingestion/schemas.py` — `IngestionRequest`, `ContentObject`, `IngestionOptions`
- `planning/schemas.py` — `DeckBrief`, `SlideOutline`, `RetrievalPlan`, `PresentationSpec`,
  `SlideSpec`, `Block`, `SourceCitation`, `StyleTokens`
- `layout/schemas.py` — `ResolvedDeckLayout`, `ResolvedSlide`, `LayoutElement`, `StyleTokens`
- `renderer/schemas.py` — `QAReport`, `QAIssue`

---

## Service-specific instructions

Each service directory contains a `SKILL.md` with rules specific to that service. Read the
relevant `SKILL.md` before making changes inside that directory.