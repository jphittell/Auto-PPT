## Step 4b — Slide Quality Remediation

One or more slides have been flagged because all their blocks contain the same text, repeat the
deck title, or repeat the slide headline — none of which provides value to the audience.

Return a `SlideRemediationSpec` that replaces ONLY the blocks for the flagged slides with
distinct, substantive content drawn from the retrieved chunks and deck context.

## Deck context

Deck brief:
{deck_brief_json}

Outline:
{outline_json}

## Flagged slides

{flagged_slides_json}

## Retrieved chunks for flagged slides

{retrieved_chunks_json}

## Rules

- Return ONLY a `SlideRemediationSpec` — never return the full deck.
- `remediations` must contain exactly one entry per flagged slide_id.
- Each `RemediatedSlide.blocks` must contain the same number of blocks as the original
  (or one fewer if the original had a callout that added no value).
- Every block must carry real content from the retrieved chunks. Do NOT repeat the headline,
  deck title, or any phrase already used by another block on the same slide.
- Each bullet item: 10-25 words, a distinct insight.
- Each text block: 1-3 sentences, substantive and specific.
- `source_citations` — every block must include at least one citation using locators from the
  retrieved chunks. `source_citations` is a list, never omit it.
- ALL text must be plain text — no markdown formatting.
- Hard cap: 150 words per block.
- Preserve the original `block_id` values — do not rename them.
- Do NOT change `layout_intent`, `headline`, `purpose`, or `slide_id`.
- `schema_version` must be "1.0.0".
