---
name: pptx-planning
description: Build and maintain the five-step JSON-only planning and RAG orchestration layer for this repo. Use when editing `pptx_gen/planning`, changing prompt-chain contracts, refining `PresentationSpec` generation rules, or updating planning prompts and tests.
---

# PPTX Planning

Read `AGENTS.md`, [schemas.py](C:/Users/jphit/OneDrive/Desktop/Codex/Projects/Auto%20PPT/pptx_gen/planning/schemas.py), [prompt_chain.py](C:/Users/jphit/OneDrive/Desktop/Codex/Projects/Auto%20PPT/pptx_gen/planning/prompt_chain.py), and [prompts](C:/Users/jphit/OneDrive/Desktop/Codex/Projects/Auto%20PPT/pptx_gen/planning/prompts) before editing this area.

## Preserve

- Keep every planning boundary schema-first and JSON-only.
- Preserve `questions_for_user` as the mechanism for surfacing missing inputs instead of hallucinating.
- Keep `PresentationSpec` as the canonical intermediate representation between planning and layout.
- Preserve block-level `source_citations`; design revision may add citations but must not remove existing ones.
- Keep the non-appendix word cap and other contract validators in `schemas.py`, not just in tests.
- Store prompt text in `planning/prompts/` rather than embedding large prompt strings inline.

## Avoid

- Do not bypass the five-step order by collapsing multiple planning stages into one opaque call.
- Do not introduce free-form model outputs where a typed schema is expected.
- Update schema and prompt-chain tests whenever enum values, block rules, citation handling, or prompt file conventions change.
