# Code Review and Bug Fix Session

Date: 2026-04-11

## Summary

Full code review of the API, pipeline, frontend, and export paths identified 9 issues ranging from
data-loss bugs to UX inconsistencies. All high-severity issues were fixed, along with a critical
regression that caused generated slides to display only headline text with no document content.

## Critical Fix: Slide ID Mismatch (content regression)

**Symptom:** Every content slide showed only the headline repeated as a bullet and callout — no
actual document content despite successful retrieval of 272 chunks.

**Root cause:** Two functions used exact `slide_id` matching between the LLM-generated
`PresentationSpec` and the pipeline's canonical outline (`s1`, `s2`, ...):

1. `_enforce_authoritative_fields` (prompt_chain.py) — enriches LLM slides with outline metadata
   and retrieval chunks. When IDs didn't match, slides lost purpose overrides, headline corrections,
   and chunk-based content enrichment.

2. `_enforce_outline_authority` (api.py) — final alignment gate. When IDs didn't match, it replaced
   every content-rich LLM slide with a stub containing only `{"text": item.message}`.

The LLM frequently generates its own slide IDs (e.g., `slide-1`, `slide_overview`) instead of the
outline's canonical `s1`, `s2` format. This caused 100% of content slides to be replaced with stubs.

**Fix:** Both functions now fall back to positional matching when ID lookup fails. Slide IDs are
rewritten to match the outline so all downstream lookups (headline, chunks, template) work correctly.

**Lesson:** Any function that joins LLM output to pipeline state by ID must have a positional
fallback. LLMs do not reliably preserve identifier formats across generation boundaries.

## Brand Kit Color Swap (Bug #3)

**Problem:** `_style_tokens_from_brand_kit` mapped `brand_kit.accent_color` to `style_tokens.bg`
and `brand_kit.primary_color` to `style_tokens.accent`. The response serializer
(`_to_api_presentation_spec`) then mapped `style_tokens.bg` back to `theme.accent_color`, creating
a double-swap that partially masked the bug for default values but broke any user customization.

**Fix:** `primary_color` maps to `accent` (the dominant brand color), `accent_color` maps to
`muted` (the secondary color). Background is no longer overridden by user brand colors. Response
serializer reads `accent_color` from `muted` instead of `bg`.

## Export Data Staleness (Bug #7)

**Problem:** `_ui_block_content` unconditionally preferred the `data` dict over the `content`
string. When a user edited slide content in the editor (updating `content`), the stale `data` dict
won, silently discarding edits on export.

**Fix:** Reversed priority — `content` string (which reflects user edits) is now preferred. `data`
is only used as fallback when `content` is empty.

## Word Cap Too Restrictive (70 -> 150)

**Problem:** The `PresentationSpec` Pydantic validator enforced a 70-word per-block content cap.
This recursively counted words across all nested content (bullet items, table cells, card text).
A 5-bullet slide with 15 words per bullet already hits 75 words. Real consulting slides routinely
contain 100-120 words of body text.

**Fix:** Raised the hard cap to 150 words per block. Updated the LLM prompt to guide toward 60-80
words (soft target) with a 150-word hard cap. The prompt still encourages conciseness — the
validator just stops rejecting valid content.

## Accessibility Preflight Removal

**Problem:** The `ExportPreflightModal` had a fake "Auto-generate alt text" button that was a
1-second `setTimeout` flipping a boolean — no actual API call or alt text generation. PDF export
was gated behind this modal, while PPTX export bypassed it entirely.

**Decision:** User opted to remove all accessibility features for now rather than ship misleading
UX. Both export buttons now trigger directly. Deleted `ExportPreflightModal.tsx`, cleaned
`preflightModalOpen` from `uiStore`.

## Double Embedding Elimination

**Problem:** Each `ingest_document` call created a throwaway `InMemoryVectorStore`. During
generation, `_build_vector_store` re-embedded all chunks from scratch — doubling the embedding
compute for every deck.

**Fix:** Added `_INGESTED_VECTOR_STORES` cache. Ingest stores the vector store; generation reuses
it. Added `InMemoryVectorStore.merge()` method for multi-document decks.

## Architectural Notes

- The join between LLM output and pipeline state is a fragile boundary. Every function that
  touches both must handle ID mismatches gracefully.
- The `_enforce_outline_authority` / `_enforce_authoritative_fields` split across api.py and
  prompt_chain.py is confusing — both do similar slide-level normalization. Consider unifying.
- The `content` vs `data` duality on `ContentBlock` (string for display, dict for structure) is
  a recurring source of staleness bugs. A single source of truth would be cleaner.
