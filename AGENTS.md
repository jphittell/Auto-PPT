# AGENTS.md - AI PPTX Generation System

## Project overview

This repo is building a six-stage, schema-driven pipeline for generating `.pptx` presentations
from raw source material such as PDFs, text, URLs, and structured data.

Treat this file as:

- the policy layer for how the repo should evolve
- the target architecture for the full system

Do not treat it as proof that every described module already exists.

## Ground truth first

Before editing:

1. Inspect the real repository tree.
2. Align your work to the files that actually exist today.
3. Only create missing modules when the task clearly requires them.

Current implementation is partial and scaffolded. Some files described below are planned targets,
not guaranteed present.

## Centralized skills

Repo skills are centralized under the repo `Skills/` directory, not inside each service folder.

Current centralized skills:

- `Skills/pptx-ingestion`
- `Skills/pptx-indexing`
- `Skills/pptx-planning`
- `Skills/pptx-layout`
- `Skills/pptx-renderer`
- `Skills/pptx-tests`

Before changing ingestion, indexing, planning, layout, renderer, or tests:

1. Read the matching centralized skill in `Skills/`.
2. Follow that skill's repo-specific guidance.
3. Do not assume a `SKILL.md` exists inside the code directory you are editing.

Keep repo-wide policy here in `AGENTS.md`. Do not duplicate broad global rules across skills
unless the repetition is necessary for correct triggering.

## Architecture target

The intended pipeline is:

1. Ingestion
2. Indexing
3. Planning
4. Layout
5. Assets
6. Renderer

Each stage should consume validated output from the previous stage. No stage should bypass another
stage's schema boundary.

## Absolute rules

1. Schema-first.
   Every inter-service boundary should use a Pydantic v2 model with `ConfigDict(extra="forbid")`.
   Do not silently pass raw dicts between services once a typed model exists.

2. No remote URLs in the PPTX.
   External image assets must be downloaded and cached locally before rendering.

3. JSON-only planning boundaries.
   Planning-stage model calls must return structured JSON matching the declared contracts.

4. Citations are preserved.
   Design-revision steps may add citations but must not remove valid existing citations.

5. Renderer is deterministic.
   Layout decisions belong in layout resolution, not in export.

## Current repo shape

The current repo already contains a working subset, including:

- `pptx_gen/ingestion/`
- `pptx_gen/indexing/`
- `pptx_gen/planning/`
- `pptx_gen/layout/`
- `pptx_gen/assets/`
- `pptx_gen/renderer/`
- `pptx_gen/pipeline.py`
- `pptx_gen/cli.py`
- `tests/conftest.py`
- `tests/test_ingestion.py`
- `tests/test_schemas.py`
- `.venv/`
- `pyproject.toml`

Some architecture documents may mention files not yet implemented, such as broader schema modules
or fuller service test coverage. Create those only when the task actually needs them.

## Working conventions by area

- Ingestion:
  Preserve provenance, deterministic chunk ids, PII redaction defaults, and the lightweight PDF
  fallback unless deliberately replacing it.

- Indexing:
  Preserve metadata round-trips for retrieval and keep vector-store concerns separate from parsing
  and citation logic.

- Planning:
  Keep the five-step chain explicit, schema-first, and JSON-only.

- Layout:
  Keep template resolution deterministic and geometry expressed in inches.

- Renderer:
  Export from resolved layouts and local assets only. Do not "fix" layout mistakes during render.

- Tests:
  Keep tests local, deterministic, and focused on public contracts and service boundaries.

## Verification requirements

After any code change, run the repo's real verification commands before concluding work.

Use the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

When the change is scoped, also run the most relevant targeted tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ingestion.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_schemas.py -q
```

When touching CLI-facing ingestion behavior, run a smoke command if the change warrants it:

```powershell
.\.venv\Scripts\python.exe -m pptx_gen.cli ingest tests\fixtures\sample_ingestion.pdf
```

Do not mark work complete until:

- the affected tests pass, or
- you clearly state which command failed, why it failed, and what remains blocked

If you changed code but did not run verification, say so explicitly and explain why.

## Practical editing rule

Prefer small, verified changes over aspirational scaffolding.

If `AGENTS.md` and the real repo disagree:

1. trust the real repo for what exists now
2. use `AGENTS.md` to guide the intended direction
3. avoid creating speculative modules unless they are needed for the task at hand
