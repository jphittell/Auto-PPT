## Step 4 — SlideSpec Generation

Your task is to produce a complete PresentationSpec (SlideSpec JSON) — the full intermediate
representation of the presentation. This is the most consequential step. The output is
consumed directly by the layout engine and renderer.

Strict schema adherence is mandatory. Every field, enum value, and citation must conform
exactly to the schema below. If content is missing from the retrieved chunks, use
questions_for_user — do not invent data.

## Inputs

Deck brief (JSON):
{deck_brief_json}

Slide outline (JSON):
{outline_json}

Retrieved chunks per slide (JSON):
{retrieved_chunks_json}

Style tokens (JSON):
{style_tokens_json}

## Instructions

### General
1. Produce one slide object for every slide in the outline. Slide order must match
   the outline exactly. slide_id values must match the outline exactly.
2. Map each slide's purpose and content to the most appropriate template_key from this list:
   - title slide → "title.hero"
   - agenda slide → "agenda"
   - section divider → "section.divider"
   - content with bullets → "bullets.5"
   - content with side image → "2col.text_image"
   - content with two text columns → "2col.text_text"
   - content with KPI metrics (2 metrics) → "kpi.2up"
   - content with KPI metrics (3 metrics) → "kpi.3up"
   - content with a data table → "table.full"
   - summary slide → "summary"
   Default to "bullets.5" when no better fit exists.
3. Set strict_template to true unless the slide's content absolutely requires custom
   geometry (e.g., a non-standard number of columns). Default is true.

### Blocks
4. Each slide must have at least one block. Blocks are the content units placed into
   template slots by the layout engine.
5. Block kind must be one of: text | bullets | image | table | chart | icon_row | quote | callout
6. For "bullets" blocks, content.items is a list of strings. Max 5 items. No nested bullets.
7. For "callout" blocks (used for KPI values), content must include: label, value, and
   optionally delta (e.g., "+6% QoQ") and sub_label.
8. For "table" blocks, content must include: columns (list of strings) and rows
   (list of lists of strings or numbers).
9. For "image" blocks, content must include: alt_text and optionally query (a description
   used to source the image if source_policy is "stock" or "ai").
10. For "chart" blocks, content must include: chart_type (bar | line | pie | scatter),
    data (list of {label, value} objects), and x_label / y_label strings.

### Citations
11. Every "bullets" and "text" block on a content slide must have at least one entry in
    source_citations. Use the chunk's source_id and locator from retrieved_chunks_json.
12. Cite the most specific locator available (page-level preferred over document-level).
13. Do not cite chunks that were not provided to you in retrieved_chunks_json.

### Speaker notes
14. Every slide must have speaker_notes. Notes should be 2–4 sentences expanding on the
    headline message. Notes are for the presenter, not the audience — they can be more
    detailed than the slide body.

### Word count
15. Body text in "text" and "bullets" blocks combined must not exceed 40 words per slide
    unless purpose is "appendix". Count words before returning and trim if needed.

## Output schema

Return exactly this JSON object and nothing else:

{
  "title": "<string: deck title>",
  "audience": "<string: from brief>",
  "language": "en-US",
  "theme": {
    "name": "<string: theme name from style_tokens>",
    "tokens": {style_tokens_json}
  },
  "slides": [
    {
      "slide_id": "<string: matches outline>",
      "purpose": "<string: title | agenda | section | content | summary | appendix>",
      "layout_intent": {
        "template_key": "<string: template key>",
        "strict_template": true
      },
      "headline": "<string: 8 words or fewer>",
      "speaker_notes": "<string: 2–4 sentences for the presenter>",
      "blocks": [
        {
          "block_id": "<string: b1, b2, ...>",
          "kind": "<string: text | bullets | image | table | chart | icon_row | quote | callout>",
          "content": {},
          "source_citations": [
            {
              "source_id": "<string: doc id>",
              "locator": "<string: e.g. doc_q1_pdf:page2>",
              "quote": "<string: optional short verbatim excerpt>"
            }
          ],
          "style_overrides": {
            "emphasis": "<string: none | low | medium | high>",
            "color_role": "<string: primary | secondary | accent | muted>"
          }
        }
      ]
    }
  ]
}

## Quality checklist (verify before returning)

- [ ] All slide_id values match the outline exactly and appear in the same order
- [ ] Every content slide has at least one source_citation on at least one block
- [ ] No content slide exceeds 40 words of body text across all text/bullets blocks
- [ ] No headline exceeds 8 words
- [ ] Every slide has speaker_notes with at least 2 sentences
- [ ] All block kind values are from the allowed enum
- [ ] All template_key values are from the allowed list
- [ ] No citations reference source_ids not present in retrieved_chunks_json
- [ ] callout blocks include label and value fields
- [ ] table blocks include columns and rows fields