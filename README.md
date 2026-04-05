# Auto-PPT

Schema-first AI presentation generation pipeline for building `.pptx` decks without requiring PowerPoint.

## Current Local Truth

The local repo currently supports a real end-to-end path:

1. Ingest PDF or plain text into typed content elements.
2. Chunk, redact, deduplicate, embed, and index content in an in-memory Chroma store.
3. Build a schema-validated planning chain into `PresentationSpec`.
4. Resolve deterministic slide templates into absolute layout coordinates.
5. Resolve local image assets and render chart specs to cached PNG files.
6. Render a `.pptx`, run structured QA, and optionally perform one design-only refinement round.

The main remaining gaps are:

- no stock-image or external asset sourcing yet
- deterministic planning fallback is intentionally simple and conservative

The planning stage now supports a real Anthropic-backed structured client when
`ANTHROPIC_API_KEY` is available. Without that key, the repo falls back to its
deterministic schema-valid planner.

If `ANTHROPIC_API_KEY` is set, the pipeline will prefer the Anthropic client automatically.
To force deterministic planning, unset `ANTHROPIC_API_KEY` before running the generator.

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

Generate a deck from a local source document:

```bash
pptx-gen generate path/to/document.txt \
  --output out/deck.pptx \
  --audience "Executive leadership" \
  --goal "Summarize the quarter" \
  --slide-count 6
```

Optional flags:

- `--tone executive|technical|narrative|instructional|persuasive`
- `--title "Custom Deck Title"`
- `--theme-name "Auto PPT"`
- `--refine`

To enable model-authored planning content, set:

```powershell
$env:ANTHROPIC_API_KEY="your-key"
```

Optional model override:

```powershell
$env:PPTX_GEN_ANTHROPIC_MODEL="claude-opus-4-6"
```

You can also place these in a local repo `.env` file instead of exporting them in the shell.
Start from [`.env.example`](C:/Users/jphit/OneDrive/Desktop/Codex/Projects/Auto%20PPT/.env.example), copy it to `.env`,
and fill in your real values. `.env` is gitignored.

Generation writes:

- the final `.pptx`
- a sibling `<name>_artifacts/` directory containing intermediate JSON artifacts
- a sibling cached asset directory under the artifacts folder

## Architecture

The intended pipeline remains:

1. Ingestion
2. Indexing
3. Planning
4. Layout
5. Assets
6. Renderer

Every boundary stays schema-first with Pydantic models and deterministic handoffs between stages.

## Tests

Run the full suite with the local virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Useful targeted runs:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ingestion.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_assets.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_planning.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_pipeline.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_renderer.py -q
```

## Skills

Repo skills are centralized under `Skills/`, not inside each service directory.
