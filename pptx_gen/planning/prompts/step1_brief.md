## Step 1 - Deck Brief

Produce a schema-valid `DeckBrief` JSON object.

## Inputs

User request:
{user_request}

Audience:
{audience}

Goal:
{goal}

Tone:
{style_tokens_summary}

Source corpus IDs:
{source_ids}

Document title:
{document_title}

Source preview:
{source_preview}

## Instructions

- Return only valid JSON for the `DeckBrief` schema.
- If audience, goal, or source ids are missing, populate `questions_for_user`.
- Keep `tone` to one concise descriptor such as `executive`, `technical`, `narrative`, `instructional`, or `persuasive`.
- Set `slide_count_target` to a practical number between 3 and 12.
- In `extensions`, ALWAYS include all of the following:
  - `document_title`: the document's full title (use the Document title field above, not a truncation of it)
  - `one_sentence_thesis`: a complete sentence (15–25 words) that captures the document's central argument or finding
  - `key_takeaways`: a list of 4–6 distinct, actionable insight statements (each 8–15 words) synthesized from the source content — do NOT just repeat section headings
  - `deck_archetype`: one of `executive_summary`, `release_readiness`, `decision_guide`, or `options_analysis`
