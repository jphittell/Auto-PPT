---
name: pptx-tests
description: Maintain the service-boundary and pipeline test strategy for this repo. Use when adding or updating tests under `tests/`, tightening schema validation coverage, organizing service-level versus end-to-end tests, or adding deterministic fixtures for ingestion, planning, layout, indexing, and rendering.
---

# PPTX Tests

Read `AGENTS.md`, [conftest.py](C:/Users/jphit/.codex/Projects/Auto-PPT/tests/conftest.py), and the relevant service module before editing tests.

## Preserve

- Test public contracts and service boundaries first.
- Keep schema validation explicit, including extra-field rejection and required-field enforcement.
- Reuse `tests/conftest.py` for shared factories, fixture paths, and deterministic helpers.
- Keep ingestion tests focused on provenance, chunk metadata, redaction, deduplication, and vector-store round trips.
- Keep schema tests focused on validators such as uniqueness, word caps, enum constraints, and export status rules.
- Prefer local fixtures under `tests/fixtures/`; avoid network access in tests.
- Prefer updating the nearest existing service test file first, including the current API, assets, CLI, pipeline, planning, renderer, and schema suites.
- Add new test files by service area only when the implementation genuinely introduces a new boundary that is not already covered.

## Avoid

- Do not rely on external APIs or real model calls in unit tests.
- Do not hide contract changes by weakening assertions.
- Keep tests aligned with the current typed models rather than ad hoc dictionaries wherever practical.
