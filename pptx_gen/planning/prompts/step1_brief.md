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

## Instructions

- Return only valid JSON for the `DeckBrief` schema.
- If audience, goal, or source ids are missing, populate `questions_for_user`.
- Keep `tone` to one concise descriptor such as `executive`, `technical`, `narrative`, `instructional`, or `persuasive`.
- Set `slide_count_target` to a practical number between 3 and 12.
- Use `extensions` only for optional supporting metadata.
