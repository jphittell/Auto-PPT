## Step 5 — Design Revision

Your task is to improve the visual clarity and design quality of the PresentationSpec
produced in Step 4. This step is about aesthetics and scannability only.

## Strict constraint: facts and citations are frozen

You must NOT:
- Change any factual claim, statistic, name, or date
- Remove any source_citation entry from any block
- Change any slide_id, purpose, headline meaning, or speaker_notes content
- Add new content slides or remove existing ones
- Change template_key unless the current key is clearly wrong for the content type

You MAY:
- Reduce text density (shorten bullet text, remove redundant phrases)
- Change a generic "text" block to a more specific kind ("callout", "icon_row", "quote")
  when the content naturally fits that kind
- Add source_citations if a retrieved chunk clearly supports an existing claim
- Change style_overrides (emphasis, color_role) to improve visual hierarchy
- Reorder blocks within a slide if a different order is more scannable
- Switch template_key to a better-fitting one (e.g., "bullets.5" → "kpi.3up" if the
  slide has exactly 3 KPI callout blocks)
- Add an "image" or "chart" block to a slide that currently has none, if the content
  would benefit from a visual — but only if you can supply a meaningful image query or
  chart data

## Input

PresentationSpec from Step 4 (JSON):
{presentation_spec_json}

Style tokens (JSON):
{style_tokens_json}

## Design principles to apply

### Text density
- Target: each bullet point is one complete thought in 10 words or fewer
- If a bullet exceeds 15 words, split it into two bullets or convert the block to a "text"
  block with a callout
- Remove filler phrases: "It is important to note that", "As we can see", "In conclusion"

### Visual specificity
- A slide with only text blocks and no visual is a missed opportunity if the content
  involves data, a process, or a comparison
- If 3 or more numeric values appear in bullets on the same slide, consider converting
  them to a "kpi.3up" template with "callout" blocks — one per metric
- If a before/after or two-option comparison appears, consider "2col.text_text"
- If a step-by-step process appears, consider "icon_row" blocks with one icon per step

### Style consistency
- All image blocks on the same slide should share the same color_role
- Callout blocks on KPI slides should all use emphasis: "high" and color_role: "accent"
- Muted color_role should be used for supplementary context, not primary claims
- Ensure heading blocks use color_role: "primary" and body blocks use "secondary" or "primary"

### Scannability
- The most important piece of information on each slide should be in the first block
- If a slide has a headline that already states the conclusion, the first block should
  support or quantify it — not restate it
- Prefer one strong callout or data point over three weak ones

## Output schema

Return the complete, updated PresentationSpec JSON with the exact same top-level structure
as the input. Do not omit any slides or fields. The schema is identical to Step 4's output:

{
  "title": "<string>",
  "audience": "<string>",
  "language": "en-US",
  "theme": { ... },
  "slides": [ ... ]
}

## Quality checklist (verify before returning)

- [ ] Total citation count is greater than or equal to the input citation count
- [ ] No factual claims, statistics, or dates were changed
- [ ] All slide_id values are unchanged
- [ ] No slides were added or removed
- [ ] All block kind and template_key values are from the allowed enums
- [ ] No headline was changed in meaning (rewording for brevity is acceptable)
- [ ] Every content slide still has speaker_notes
- [ ] No content slide now exceeds 40 words of body text