# PPTX Export Readability and Template Variety Fixes

Date: 2026-04-11

## Summary

Two visual defects in exported PPTX decks were identified and fixed: (1) white text rendered on
white card backgrounds making content invisible, and (2) all content slides receiving the same
layout template, producing a monotonous deck with no structural variety.

## Issue 1: White Text on White Card Backgrounds

**Symptom:** Card shapes (rounded rectangles) on content slides had white text on a near-white
`#F8FAFC` fill, making all card content completely unreadable in the exported `.pptx`.

**Root cause:** In `pptx_gen/renderer/slide_ops.py`, the `style_profile()` function handled the
`"card"` style reference like this:

```python
"fill_color": "#F8FAFC",        # near-white card background
"text_color": colors.text,      # resolves to "#FFFFFF" on ONAC theme
```

The ONAC theme defines `colors.text = "#FFFFFF"` because the slide background is dark (`#2A2F2F`).
Body text on the dark background is correctly white — but card shapes have their own light fill,
so inheriting the theme's white text color produces white-on-white.

**Fix:** Card text now uses a hardcoded dark color (`#1E293B`, slate-800) instead of inheriting the
theme text color:

```python
"text_color": "#FFFFFF" if style_ref == "takeaway" else "#1E293B",
```

The `"takeaway"` style (accent-colored bar) correctly keeps white text since its fill is the dark
accent color.

**Design lesson:** Any style with a light fill must not inherit text color from a dark-background
theme. When adding new styles with custom fills, always verify the text/fill contrast pair.

## Issue 2: All Content Slides Use the Same Template

**Symptom:** A 6-slide deck used `headline.evidence` for slides 2 through 6, producing five
identical layouts with no visual variety despite varied content.

**Root cause:** The function `_apply_global_template_default()` in `pptx_gen/api.py` was designed
to let users pick a "deck default template" in the wizard. However, it applied this single template
to **every** content and summary slide, overriding the per-slide template choices that the outline
planning stage (`_score_content_template` in `prompt_chain.py`) had carefully assigned with
diversity-aware scoring.

The original logic:

```python
chosen_template = (
    explicit_template_by_slide_id[slide.slide_id]   # user explicitly changed
    if slide.slide_id in explicit_template_by_slide_id
    else current_template
    if current_template in SPECIALIST_TEMPLATE_IDS   # e.g., exec.summary
    else selected_template_id                        # BLANKET OVERRIDE
)
```

The third branch replaced every non-specialist content slide with the single deck-level selection,
wiping out templates like `compare.2col`, `kpi.big`, `impact.statement`, and `agenda.table` that
the outline heuristic had assigned.

**Fix:** The function now preserves outline-assigned templates when they differ from the generic
default (`headline.evidence`). The deck-level selection only applies as a fallback for slides that
received the generic default:

```python
if slide.slide_id in explicit_template_by_slide_id:
    chosen_template = explicit_template_by_slide_id[slide.slide_id]
elif current_template in SPECIALIST_TEMPLATE_IDS:
    chosen_template = current_template
elif current_template in DECK_DEFAULT_TEMPLATE_IDS and current_template != "headline.evidence":
    # Outline heuristic chose a specific layout — preserve the variety.
    chosen_template = current_template
else:
    # Generic fallback — apply the user's deck-level selection.
    chosen_template = selected_template_id
```

**Result:** A 6-slide deck now produces varied layouts — e.g., `title.cover`, `exec.summary`,
`impact.statement`, `agenda.table`, `compare.2col`, `closing.actions` — instead of repeating a
single template.

**Design lesson:** Deck-level defaults should be fallbacks, not overrides. When an upstream stage
makes a content-aware decision (like template scoring with diversity penalties), downstream stages
should respect that decision unless the user explicitly overrode it.

## Additional Fixes in This Session

- **DOCX parser crash:** `_partition_docx` incorrectly called `_pptx_source_extensions()` on
  `.docx` files, opening them with `python-pptx` and crashing. Fixed to return plain elements.

- **PPTX title detection:** Slides with titles in textboxes (not formal title placeholders) got
  generic "Slide N" names. Added `_find_pptx_slide_title()` fallback that finds the topmost short
  text shape.

- **Generate endpoint slide count mismatch:** `/api/generate` rejected outlines that didn't match
  the original planned count, blocking the new outline review step where users can add/remove
  slides. Now dynamically updates the draft.

## Files Changed

- `pptx_gen/renderer/slide_ops.py` — card text color fix
- `pptx_gen/api.py` — template variety preservation, slide count flexibility
- `pptx_gen/ingestion/parser.py` — DOCX fix, PPTX title fallback, partition return type
- `tests/test_api.py` — updated assertions for template variety, added `_infer_chat_brief` tests
