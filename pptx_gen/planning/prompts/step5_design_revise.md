## Step 5 - Design Revision

Improve design quality only and return a schema-valid `DesignRefinement` JSON object.

## Inputs

PresentationSpec:
{presentation_spec_json}

Style tokens:
{style_tokens_json}

QA report:
{qa_report_json}

Rendered artifact path:
{render_artifact_path}

User brief:
{user_brief}

## Hard constraints

- Preserve every `slide_id` and `block_id`.
- Preserve all existing citations exactly.
- Do not invent unsupported fields or template keys.
- Do not remove slides.
- Do not bypass the layout registry.

## Allowed changes

- Reduce text density
- Improve scannability
- Reorder blocks within a slide
- Adjust style overrides
- Switch to a better-fitting canonical template key when justified

Return:

{
  "schema_version": "1.0.0",
  "applied": true,
  "rationale": ["short explanation"],
  "presentation_spec": { ... full PresentationSpec ... }
}
