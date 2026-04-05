## Step 4 - PresentationSpec

Produce a schema-valid `PresentationSpec` JSON object.

## Inputs

Deck brief:
{deck_brief_json}

Outline:
{outline_json}

Retrieved chunks by slide:
{retrieved_chunks_json}

Style tokens:
{style_tokens_json}

## Instructions

- Return only valid JSON for the `PresentationSpec` schema.
- Preserve all `slide_id` values and slide order from the outline.
- Use only canonical template keys from the repo layout registry:
    - "title.hero", "agenda.list", "section.header"
    - "content.1col", "content.2col.text_image", "content.3col.cards"
    - "kpi.3up", "chart.full", "table.full", "appendix.details"
  Default to "content.1col". No other values are valid.
- Block kind must be one of: text | bullets | image | table | chart | quote | callout | kpi_cards
  Do not use "icon_row" — it is not in the schema.
- Keep all non-appendix slides within the 40-word body-text cap. The cap applies
  recursively to ALL string content in ALL block content fields (not just text/bullets).
- Every factual block (text, bullets, table, chart, quote, callout, kpi_cards) on
  `content`, `summary`, or `appendix` slides must carry at least one citation.
- Use only citations present in the retrieved chunks.
- The theme field must use "style_tokens" (not "tokens") as the key.
- Include `schema_version` and `questions_for_user` at the top level.
- Do not add unsupported fields.
