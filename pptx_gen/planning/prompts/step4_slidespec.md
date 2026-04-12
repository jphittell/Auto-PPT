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
- REQUIRED top-level fields — every response must include ALL of these:
    - `schema_version` (always "1.0.0")
    - `title` — set to `extensions.document_title` from the deck brief. Never omit; never use "Generated Presentation" or any placeholder.
    - `audience` — copy verbatim from the deck brief. Never omit.
    - `language` — copy from the deck brief (default "en-US"). Never omit.
    - `theme` — must include both `name` and `style_tokens`. Never omit either sub-field.
    - `slides` — the full list of slide objects.
    - `questions_for_user` — required even if empty (`[]`).
- Preserve all `slide_id` values and slide order from the outline.
- ALL text content must be plain text. Do NOT use markdown formatting (`**bold**`, `*italic*`, `` `code` ``, `# headings`, `[links](url)`). The renderer applies its own styling.
- For each slide, use the `headline` from the corresponding outline item verbatim - do NOT replace it with "Slide 1", "Slide 2", or any other placeholder.
- CRITICAL: bullet items, text blocks, and callout text must contain real synthesized content from the retrieved chunks - not the slide headline, not the outline message repeated verbatim, and not placeholder phrases. Each bullet must be a distinct insight (10-25 words). Card descriptions should be substantive sentences that convey real meaning, not terse fragments.
- CRITICAL: No two blocks on the same slide may repeat the same information. Each block must contribute a distinct piece of content drawn from different parts of the retrieved evidence.
- CRITICAL: If the retrieved chunks for a slide contain only the slide headline or only a single short phrase, do NOT repeat that phrase in the blocks. Instead, synthesize context from the broader deck brief and surrounding slides, or omit the callout block entirely. A slide with one substantive bullet is better than three blocks all saying the same thing.
- If any retrieved chunk contains internal planning language (for example, "should implement", "TODO", or "the model needs to"), do not use that chunk's text as slide content. Rephrase it into audience-facing language or skip it entirely.

## Valid template keys

Use ONLY these exact values for `layout_intent.template_key`. Any other value will cause a pipeline error.

  "title.cover", "section.divider", "exec.summary",
  "headline.evidence", "kpi.big", "compare.2col",
  "chart.takeaway", "closing.actions", "quote.photo", "quote.texture",
  "impact.statement", "content.3col", "icons.3", "icons.4",
  "content.photo", "agenda.table", "screenshot",
  "timeline.roadmap", "matrix.2x2", "team.grid",
  "process.steps", "dashboard.kpi", "financial.table", "status.rag"

Default to "headline.evidence" when no other template fits. Do NOT use "content.4col", "bold.photo", or "split.content" — they are deprecated.

## Per-template block requirements (CRITICAL — violating these causes a pipeline error)

- `kpi.big`: requires EXACTLY 3 blocks, each with `"kind": "kpi_cards"` or `"kind": "text"`. If you have fewer than 3 metrics, use `headline.evidence` instead.
- `compare.2col`: requires EXACTLY 2 blocks. If you have only 1 block, use `headline.evidence` instead.
- `chart.takeaway`: requires at least 1 block with `"kind": "chart"`. Only use this template when the retrieved evidence contains numeric series that can be plotted. If no chart data is available, use `headline.evidence` instead.
- `content.3col`: requires EXACTLY 3 blocks.
- `icons.3`: requires EXACTLY 3 blocks.
- `icons.4`: requires EXACTLY 4 blocks.

## Block kinds

Block `kind` must be one of: `text` | `bullets` | `image` | `table` | `chart` | `quote` | `callout` | `kpi_cards`
Do not use "icon_row" — it is not in the schema.

## Citations (CRITICAL — omitting citations causes a pipeline error)

- Every block on any `content`, `summary`, or `closing` slide MUST include `source_citations`.
- `source_citations` is a list — it must be present even if it contains only one entry.
- Never emit an empty `source_citations: []` for a factual block. Use the locators from the retrieved chunks provided.
- `source_citations` entries require BOTH `source_id` AND `locator`. Do not omit either sub-field.

## Other constraints

- Keep all non-closing slides concise — aim for 60-80 words per block, hard cap at 150 words. The cap applies recursively to ALL string content in ALL block content fields.
- The theme field must use "style_tokens" (not "tokens") as the key.
- Do not add unsupported fields.

## Template selection guide

- `compare.2col` — side-by-side comparisons or decision criteria (must have 2 blocks)
- `kpi.big` — exactly 3 key metrics or performance indicators
- `chart.takeaway` — only when numeric series exist in retrieved evidence
- `exec.summary` — dense multi-point content with a key insight
- `closing.actions` — recommendations, next steps, or action items
- `quote.photo` — quote or testimonial with an accompanying image
- `quote.texture` — standalone quote with minimal supporting content
- `impact.statement` — bold single-message slide
- `content.3col` — three clearly separable parallel points (must have 3 blocks)
- `icons.3` / `icons.4` — card-like capability summaries with short headings and brief body text
- `content.photo` — explanatory content paired with a supporting image
- `agenda.table` — structured agendas, matrices, or row/column schedules
- `screenshot` — UI walkthroughs, product captures, or dashboard showcases
- `timeline.roadmap` — sequential milestones or phased roadmaps
- `matrix.2x2` — two-axis analysis or competitive positioning
- `team.grid` — team member or stakeholder profiles
- `process.steps` — numbered sequential process or workflow
- `dashboard.kpi` — 4-6 tile KPI grid (use `kpi.big` for exactly 3 metrics)
- `financial.table` — P&L, budget, or financial comparison tables
- `status.rag` — red/amber/green project status reports

- For release-note or readiness material, emphasize what is new, what changes operationally, known issues, and what action leaders should take.
- For decision guides and options analyses, prefer tradeoff framing, side-by-side comparison, and a final recommendation.
