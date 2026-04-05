## Step 3 — Retrieval Planning

Your task is to generate a structured retrieval plan: for each slide in the outline that
requires evidence, produce up to 5 search queries and any metadata filters that should
be applied when querying the vector index.

This step makes retrieval auditable and controllable. Good queries are specific, varied,
and target different facets of the evidence a slide needs. Poor queries are vague or
redundant with each other.

## Input

Slide outline (JSON):
{outline_json}

Available source document IDs:
{source_ids}

Active date filter (ISO date string or null):
{min_date}

## Instructions

1. Only generate retrieval entries for slides with purpose "content" or "appendix".
   Skip title, agenda, section, and summary slides — leave them out of the output entirely.

2. For each content/appendix slide, generate up to 5 queries. Each query should target a
   different piece of evidence the slide needs:
   - If a slide needs a statistic, write one query targeting that number
   - If a slide needs a comparison, write queries for each side of the comparison
   - If a slide needs a trend, write queries targeting the trend data and its time period
   - Avoid restating the headline as a query — queries should be more specific

3. Populate filters.doc_ids when the brief or user request specifies that a particular
   document should be prioritized for a slide. If no preference was stated, use the full
   source_ids list.

4. Set filters.min_date to the {min_date} value if provided, otherwise null. This filters
   out chunks from documents older than the cutoff.

## Output schema

Return exactly this JSON object and nothing else:

{
  "retrieval_plan": [
    {
      "slide_id": "<string: matches slide_id from outline>",
      "queries": [
        "<string: specific retrieval query 1>",
        "<string: specific retrieval query 2>"
      ],
      "filters": {
        "doc_ids": ["<string: source doc id>"],
        "min_date": "<ISO date string or null>"
      }
    }
  ]
}

## Query writing guidelines

GOOD queries (specific, targeted):
- "Q1 2026 revenue growth percentage year over year"
- "customer churn rate enterprise segment 2025"
- "infrastructure cost reduction after platform migration"
- "NPS score improvement following onboarding redesign"

BAD queries (vague, redundant, or just the headline restated):
- "revenue"
- "Q1 business review highlights"
- "key metrics"
- "what happened in Q1"

## Quality checklist (verify before returning)

- [ ] Only slides with purpose "content" or "appendix" appear in retrieval_plan
- [ ] Each slide has between 2 and 5 queries
- [ ] No two queries for the same slide are near-duplicates of each other
- [ ] All slide_id values match exactly the slide_ids in the outline
- [ ] filters.doc_ids contains only IDs from the provided source_ids list