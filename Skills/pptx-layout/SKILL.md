---
name: pptx-layout
description: Resolve `PresentationSpec` into deterministic slide geometry for this repo. Use when editing `pptx_gen/layout`, changing template slots or aliases, implementing block-to-slot mapping, or tightening layout constraints and tests.
---

# PPTX Layout

Read `AGENTS.md`, [schemas.py](C:/Users/jphit/.codex/Projects/Auto-PPT/pptx_gen/layout/schemas.py), [templates.py](C:/Users/jphit/.codex/Projects/Auto-PPT/pptx_gen/layout/templates.py), and [resolver.py](C:/Users/jphit/.codex/Projects/Auto-PPT/pptx_gen/layout/resolver.py) before editing this area.

## Preserve

- Keep layout deterministic and rule-based. Do not add LLM-driven placement.
- Maintain `layout/templates.py` as the home for both canonical template keys and aliases.
- Keep all geometry in inches and aligned with the current `16:9` / `4:3` page-size contract in `schemas.py`.
- Preserve `style_ref` passthrough and block-to-layout traceability through `data_ref`.
- Raise explicit errors for unknown template keys, slot mismatches, and layout constraint failures instead of silently adjusting output.

## Avoid

- Do not let the renderer make layout decisions.
- Do not invent template keys on the fly.
- Update layout tests whenever template behavior or geometry constraints change.
