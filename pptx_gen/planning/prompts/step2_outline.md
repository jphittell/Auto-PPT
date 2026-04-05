## Step 2 - Outline

Produce a schema-valid `OutlineSpec` JSON object from the provided `DeckBrief`.

## Input

Deck brief:
{deck_brief_json}

## Instructions

- Return only valid JSON for the `OutlineSpec` schema.
- Use slide ids `s1`, `s2`, and so on.
- Slide 1 must be `title`.
- Use `agenda` only when the deck is long enough to benefit from it.
- End on `summary` unless a clearly justified `appendix` is needed.
- Keep headlines short and scannable.
- Use `template_key` values that match the repo's canonical layout registry.
