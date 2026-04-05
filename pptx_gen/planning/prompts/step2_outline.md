## Step 2 — Slide Outline

Your task is to produce a slide-by-slide outline from the deck brief. This outline defines
the narrative arc of the presentation. Each slide gets a single clear purpose, a short
headline, a one-sentence message, and a list of evidence queries that will be used to
retrieve supporting content from the source corpus.

## Input

Deck brief (JSON):
{deck_brief_json}

## Instructions

1. Produce exactly {slide_count_target} slides, ±1. Do not significantly over- or under-shoot.
2. Assign each slide a purpose from the allowed enum. Use this structure as a starting point:
   - Slide 1: always "title"
   - Slide 2: "agenda" (optional — omit for decks < 6 slides)
   - Middle slides: "section" headers to group themes, then "content" slides for each point
   - Second-to-last: "summary" (omit for decks < 5 slides)
   - Last: may be "appendix" if supporting detail exists, otherwise repeat "summary" is wrong —
     end on "summary"
3. Headlines must be 8 words or fewer. They should be declarative or interrogative, not vague.
   Prefer: "Revenue Grew 18% QoQ in NA" over "Revenue Overview"
4. The "message" field is a single sentence describing the one thing the audience should take
   away from this slide. It should be specific enough to be falsifiable.
5. "evidence_queries" are retrieval search strings — not headlines. Write them as questions or
   keyword phrases a search engine could use to find supporting data in the source documents.
   - Only populate evidence_queries for slides with purpose "content" or "appendix"
   - Use 2–4 queries per content slide, targeting different facets of the evidence needed
   - Title, agenda, section, and summary slides should have empty evidence_queries arrays

## Output schema

Return exactly this JSON object and nothing else:

{
  "outline": [
    {
      "slide_id": "<string: s1, s2, s3, ...>",
      "purpose": "<string: one of title | agenda | section | content | summary | appendix>",
      "headline": "<string: 8 words or fewer>",
      "message": "<string: one sentence — the single point this slide makes>",
      "evidence_queries": [
        "<string: retrieval query>",
        "<string: retrieval query>"
      ]
    }
  ]
}

## Quality checklist (verify before returning)

- [ ] Slide 1 has purpose "title"
- [ ] No two adjacent slides make the same point
- [ ] Every "content" slide has at least 2 evidence_queries
- [ ] No headline exceeds 8 words
- [ ] Slide count is within ±1 of slide_count_target ({slide_count_target})
- [ ] All slide_id values are unique and follow the pattern s1, s2, s3...
- [ ] No "summary" slide appears before the last two slides