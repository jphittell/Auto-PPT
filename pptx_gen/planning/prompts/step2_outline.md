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
- Use `template_key` values from the table below. Vary templates across the deck for visual interest — do not repeat the same template_key on more than 2 consecutive content slides.

## Available Templates

| template_key | Best for |
|---|---|
| headline.evidence | Default: headline + evidence bullets + takeaway |
| kpi.big | 2-4 numeric KPIs with values and labels |
| compare.2col | Side-by-side comparison of two options |
| chart.takeaway | Data chart + insight callout |
| exec.summary | Executive overview with key points + cards |
| closing.actions | Final slide: action items and next steps |
| content.3col | Three parallel categories or points |
| content.4col | Four parallel categories or points |
| icons.3 | Three icon-style cards with subheads |
| icons.4 | Four icon-style cards with subheads |
| impact.statement | Single bold executive message |
| split.content | Two-sided content with divider |
| quote.texture | Standalone quote on textured background |
| agenda.table | Structured table, matrix, or schedule |
- If `extensions.deck_archetype` indicates a release-readiness document, favor a flow like:
  what changed -> impact/risk -> known issues -> required actions.
- If `extensions.deck_archetype` indicates a decision guide, favor a flow like:
  model overview -> tradeoffs -> implementation guidance -> recommendation.
- If `extensions.deck_archetype` indicates an options analysis, include at least one comparison-oriented slide
  that can use `compare.2col` or `headline.evidence`, plus a closing slide.
