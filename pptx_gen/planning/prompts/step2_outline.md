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
- Keep headlines short and scannable (5–8 words max).
- The `message` field for each slide must be a distinct, concrete statement of what that slide will communicate — NOT a copy of the headline and NOT a generic phrase like "provide evidence". Use the key_takeaways and thesis from the brief as the basis for actual content.
- Use `template_key` values that match the repo's canonical layout registry.
- If `extensions.deck_archetype` indicates a release-readiness document, favor a flow like:
  what changed -> impact/risk -> known issues -> required actions.
- If `extensions.deck_archetype` indicates a decision guide, favor a flow like:
  model overview -> tradeoffs -> implementation guidance -> recommendation.
- If `extensions.deck_archetype` indicates an options analysis, include at least one comparison-oriented slide
  that can use `content.3col.cards` or `table.full`, plus a recommendation slide.
