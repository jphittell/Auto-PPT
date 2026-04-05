---
name: pptx-renderer
description: Render deterministic slide layouts into `.pptx` artifacts and enforce QA for this repo. Use when working in `pptx_gen/renderer` or asset-to-render boundaries, implementing PPTX export, validating local assets, or tightening QA behavior and renderer tests.
---

# PPTX Renderer

Read `AGENTS.md`, [pptx_exporter.py](C:/Users/jphit/OneDrive/Desktop/Codex/Projects/Auto%20PPT/pptx_gen/renderer/pptx_exporter.py), [qa.py](C:/Users/jphit/OneDrive/Desktop/Codex/Projects/Auto%20PPT/pptx_gen/renderer/qa.py), and the layout schemas before editing this area.

## Preserve

- Keep rendering deterministic and local-only. Do not embed remote image URLs.
- Treat charts as pre-rendered images unless the renderer contract changes deliberately.
- Keep speaker notes separate from visible slide content.
- Preserve the separation between layout, asset resolution, rendering, and QA responsibilities.
- Keep `QAReport` and related models strict with `ConfigDict(extra="forbid")`.

## Avoid

- Do not move or resize elements in the renderer to fix layout mistakes.
- Do not suppress QA failures silently.
- Update renderer and QA tests whenever validation thresholds, asset handling, or export semantics change.
