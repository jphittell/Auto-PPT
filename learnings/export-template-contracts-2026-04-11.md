# Export Template Contract Learnings

Date: 2026-04-11

## Summary

The export-quality issues were caused by contract drift between UI/generation-shaped slide data and
the template bindings used during PPTX export. The prompt field itself was not part of the bug:
prompt text is intentionally transient until the user clicks Generate.

## Confirmed Learnings

1. Export needs its own canonicalization pass before template resolution.
   - Preview and generation were already tolerating looser block shapes through coercion logic.
   - Export was consuming the UI slide state more literally, which exposed block-index and field
     mismatches in several templates.
   - A single normalization gate in the export path is safer than scattering template-specific
     corrections across multiple branches.

2. `content.3col` and `content.4col` had a real preview/export mismatch.
   - The UI could surface a single `callout.cards` block representing multiple columns.
   - The export templates expected separate text blocks by index.
   - Without canonicalization, exported slides could lose or misplace card text.

3. Several specialized templates were binding the wrong fields for export.
   - `quote.photo` and `quote.texture` needed quote text and attribution to bind from structured quote
     fields instead of mismatched block assumptions.
   - `bold.photo` needed the image binding to come from the actual image block, while preserving the
     text block as the exported headline.
   - `chart.takeaway` needed the takeaway to resolve as text content rather than an image/path slot.
   - `split.content` needed both text blocks to bind explicitly so the right-hand block would not fall
     back to placeholder behavior.
   - `agenda.table` needed the main table to bind to the real table block instead of an incorrect
     offset.

4. Prompt text remaining out of export is expected behavior, not a defect.
   - The prompt only becomes exportable content after the user clicks Generate and the slide state is
     updated.
   - Typing into the prompt without generating should not affect the downloaded PPTX.

5. `content` must remain authoritative for text-native blocks, while structured `data` must still be
   preserved for asset-bearing blocks.
   - A previous fix established that visible `content` should win over stale `data` for text shown in
     the UI.
   - Export normalization must not regress that by reintroducing a blanket data-first path.
   - The correct rule is selective preservation: keep structured `data` for tables, charts,
     quote/callout payloads, and image/file-backed blocks, but let visible `content` drive plain text.

6. `icons.3` and `icons.4` needed explicit regression coverage even though they were not normalized
   into separate text blocks.
   - They share the same card-shaped content pattern as the multi-column templates.
   - The export path must preserve their structured card payloads intact rather than flattening them.

7. The Windows temp-directory failure encountered during testing appears environmental, not a product
   bug in export logic.
   - A bare `TemporaryDirectory()` created in the local repo temp area was not writable in this shell.
   - That failure happens before meaningful export assertions and should not be treated as evidence of
     broken slide-content behavior.

## Changes Applied

1. Added a centralized export canonicalization pass in `pptx_gen/api.py`.
   - `_ui_slide_to_planning_slide(...)` now normalizes blocks through
     `_canonicalize_export_slide(...)` before template resolution.

2. Added targeted export normalization helpers.
   - Single `callout.cards` blocks are expanded into canonical text blocks for
     `content.3col` and `content.4col`.
   - `bold.photo` promotes text into the slide headline while preserving image data.
   - `chart.takeaway` collapses card-like callout payloads into exported takeaway text.

3. Preserved structured payloads only where required.
   - `_ui_block_content(...)` now keeps structured `data` for tables, charts, quotes, callout cards,
     and asset/path-backed blocks.
   - Text-native blocks still prefer current visible `content`.

4. Corrected template bindings in `pptx_gen/layout/templates.py`.
   - Fixed field resolution for `quote.photo`, `quote.texture`, `bold.photo`,
     `chart.takeaway`, `split.content`, and `agenda.table`.

5. Added regression coverage for both normalization and template binding behavior.
   - API tests now cover `content.3col`, `bold.photo`, `chart.takeaway`, `agenda.table`,
     and icon-card preservation for `icons.3` / `icons.4`.
   - Layout-template tests now validate specialized export bindings across the affected templates,
     including `split.content`.

## Final Validation Status

- Targeted export-related pytest coverage passes.
- Python compilation checks pass for the modified backend and test files.
- One broader export test remains blocked in this shell by a non-writable temporary directory, which
  appears to be an environment constraint rather than an export-content regression.

## Recommended Follow-Up

- Run a manual PPTX export smoke test outside this shell to confirm the corrected bindings match the
  visible UI content for the affected templates.
- If more template families are added, treat export contract coverage as mandatory whenever a template
  uses structured block payloads or nontrivial block indexing.
- Keep generation and export normalization behavior aligned so preview parity does not drift again.
