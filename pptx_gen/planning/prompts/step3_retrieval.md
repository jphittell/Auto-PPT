## Step 3 - Retrieval Plan

Produce a schema-valid `RetrievalPlan` JSON object.

## Input

Outline:
{outline_json}

Source IDs:
{source_ids}

Minimum date:
{min_date}

## Instructions

- Return only valid JSON for the `RetrievalPlan` schema.
- Include entries only for `content` or `appendix` slides.
- Each retrieval entry must include 2 to 5 `RetrievalQuery` objects.
- Each `RetrievalQuery` object has three fields:
    - `query`: specific natural-language search string (not a restatement of the headline)
    - `doc_ids`: list of source IDs to restrict search to; use the full source_ids list
      if no preference is stated
    - `min_date`: the {min_date} value if provided, otherwise null
- Use only the provided source ids in `doc_ids`.
- Preserve query specificity and avoid near-duplicate queries within the same slide.
- Include `schema_version` and `questions_for_user` at the top level.

## Output shape

```json
{
  "schema_version": "1.0.0",
  "retrieval_plan": [
    {
      "slide_id": "s3",
      "queries": [
        {
          "query": "Q1 2026 revenue growth percentage year over year",
          "doc_ids": ["doc_q1_pdf"],
          "min_date": null
        },
        {
          "query": "Q1 revenue versus annual plan target",
          "doc_ids": ["doc_q1_pdf", "doc_finance_model_xlsx"],
          "min_date": null
        }
      ]
    }
  ],
  "questions_for_user": []
}
```
