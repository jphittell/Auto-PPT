# Slide Writing Rubric — Auto PPT v1

**Version:** 1.0.0
**Status:** Authoritative for v1
**Scope:** Text density, content rules, and quality criteria per slide type.

---

## 1. Universal Rules

These apply to every slide regardless of template.

| Rule | Constraint | Enforcement |
|---|---|---|
| Headline word limit | 10 words max | Planning stage; validated in `PresentationSpec` |
| On-slide word cap (non-appendix) | 70 words max | `PresentationSpec.validate_slides()` |
| No orphan bullets | Min 2 bullets if using a bullet block | Planning stage |
| Speaker notes required | Every content/summary slide must have notes | Planning stage |
| Speaker notes length | 20-80 words | Advisory; not hard-enforced in v1 |
| Citation coverage | Every content/summary/appendix block needs `source_citations` | `PresentationSpec.validate_slides()` |
| No raw URLs on-slide | URLs go in speaker notes, not in block content | Planning stage |

---

## 2. Per-Template Rubric

### title.hero

| Dimension | Rule |
|---|---|
| Headline | 3-8 words. The deck title. No verbs unless it's a call to action. |
| Subtitle (block field) | 5-12 words. Date, meeting context, or one-line framing. |
| Presenter (block field) | Name and title, or omit. |
| Image/chart | Never. Title slides do not carry visual evidence. |
| Speaker notes | Welcome framing. Set the stage for the deck's narrative arc. 20-40 words. |

### agenda.list

| Dimension | Rule |
|---|---|
| Headline | "Agenda" or a short variant ("What We'll Cover"). 1-4 words. |
| Bullet count | 3-6 items. Each item is a section name, not a sentence. |
| Bullet length | 3-8 words per item. No sub-bullets. |
| Image/chart | Never. |
| Speaker notes | Optional. If used, preview what's most important or time-sensitive. |

### section.header

| Dimension | Rule |
|---|---|
| Headline | 2-6 words. The section name. |
| Tagline (block field) | 6-15 words. One sentence framing what this section covers. |
| Image/chart | Never. |
| Speaker notes | Optional. Transition language: "Moving on to..." or "Now let's look at..." |

### content.1col

| Dimension | Rule |
|---|---|
| Headline | 5-10 words. Must convey the slide's takeaway, not just the topic. Bad: "Revenue Performance." Good: "Revenue Hit $29M, Up 18% YoY." |
| Body block | 3-5 bullets, 8-15 words each. Or 2-3 short paragraphs totaling 40-60 words. |
| Takeaway block | 1-2 sentences. The "so what" — what the audience should remember or do. |
| Image/chart | Not in this template. Use `content.2col.text_image` if visual evidence is needed. |
| Speaker notes | Expand on the data. Include context the audience needs but the slide shouldn't show. 30-60 words. |

### content.2col.text_image

| Dimension | Rule |
|---|---|
| Headline | 5-10 words. Takeaway-driven. |
| Text column (block 0) | 3-4 bullets, 8-12 words each. Must stand alone without the image. |
| Image column (block 1) | One image or chart. Must directly support the text column's argument. |
| When to use image vs chart | Image: when showing a product, process, or real-world context. Chart: when the visual is data-driven. |
| Speaker notes | Explain what the image shows and why it matters. 30-50 words. |

### content.3col.cards

| Dimension | Rule |
|---|---|
| Headline | 5-10 words. Frames the comparison or trio. |
| Card count | Exactly 3. |
| Card content | Each card: 2-4 word heading + 2-3 bullets of 5-10 words each. |
| When to use | Comparing options, showing a 3-step process, or presenting 3 pillars/themes. |
| Speaker notes | Explain the comparison logic or recommend one option. 30-50 words. |

### kpi.3up

| Dimension | Rule |
|---|---|
| Headline | 5-10 words. Frames the metrics set: "Q1 Key Metrics" or "Performance at a Glance." |
| KPI count | 2-3. Each KPI block has: label (1-3 words), value (number + unit), delta (change + direction). |
| Delta format | "+18% YoY", "-0.6 pts", "+$2.1M QoQ". Always include the comparison basis. |
| Image/chart | Never in this template. If you need a sparkline, use `chart.full`. |
| Speaker notes | Explain what drove each metric. Call out anything surprising. 30-60 words. |

### chart.full

| Dimension | Rule |
|---|---|
| Headline | 5-10 words. States what the chart shows AND what the takeaway is. Bad: "Revenue Chart." Good: "Revenue Accelerated Every Quarter." |
| Chart block | One chart spec. The chart IS the content. |
| Citation footer | Source attribution for the underlying data. Required. |
| Body text | None. Do not add bullets alongside a full-width chart. |
| Speaker notes | Walk through the chart: what's on each axis, what the trend shows, what's notable. 40-70 words. |

### table.full

| Dimension | Rule |
|---|---|
| Headline | 5-10 words. Frames the table's purpose. |
| Table dimensions | 3-6 columns, 3-8 rows. More than 8 rows: split across slides or move to appendix. |
| Cell content | Numbers, short labels, or status indicators. No sentences in table cells. |
| Header row | Always present. Bold or accent-colored. Column names are 1-3 words. |
| Speaker notes | Highlight the 1-2 most important rows or columns. 30-50 words. |

### executive.overview

| Dimension | Rule |
|---|---|
| Headline | 5-10 words. High-level positioning statement. |
| Summary block | 2-3 sentences totaling 25-40 words. Sets the strategic context. |
| Insight block | 1-2 sentences. The single most important takeaway. |
| Cards | 4-6 cards, each with a 2-3 word title and 1 sentence (8-15 words). |
| Footer metrics | One line of 2-3 metrics with labels. |
| Speaker notes | Provide strategic framing that connects the overview to the rest of the deck. 40-60 words. |

### architecture.grid

| Dimension | Rule |
|---|---|
| Headline | 5-10 words. Names the system or architecture. |
| Summary block | 1-2 sentences framing the architecture's purpose. 15-25 words. |
| Cards | Exactly 6 component cards in a 2x3 grid. Each: 2-3 word title + 1 sentence (8-12 words). |
| Footer note | Technical note or version reference. 1 sentence. |
| Speaker notes | Explain how the components interact. 40-60 words. |

### appendix.details

| Dimension | Rule |
|---|---|
| Headline | 3-8 words. "Appendix: [Topic]" format preferred. |
| Body | No word cap. Dense text is acceptable. Use full paragraphs or detailed bullet lists. |
| Citations | Required. Every claim in appendix must be sourced. |
| Speaker notes | Optional. Appendix slides are often not presented live. |

---

## 3. What Counts as "Too Dense"

A slide is too dense when any of the following are true:

1. **Body text exceeds 70 words** (hard cap, enforced by schema validator).
2. **More than 5 bullets** on a single-column slide.
3. **Bullet text averages more than 15 words** per bullet.
4. **Two or more content blocks compete for attention** (e.g., a bullet list AND a callout AND a table on one slide).
5. **The headline is a full sentence** instead of a takeaway phrase.

When a slide is too dense, the correct action is to **split it into two slides**, not to shrink fonts or add more whitespace.

---

## 4. What Belongs in Speaker Notes vs On-Slide

| On-slide | Speaker notes |
|---|---|
| The takeaway (headline) | The narrative context |
| Key numbers and deltas | How the numbers were calculated |
| 3-5 supporting bullets | The story connecting the bullets |
| Chart or image | What to point out in the chart |
| Source citation (footer) | Full source details if abbreviated |
| — | Transition language to the next slide |
| — | Objection handling or FAQ for Q&A |
| — | Raw URLs or document links |

---

## 5. Quality Scoring Dimensions

Based on the paper's evaluation framework, slide quality is assessed on four axes:

| Dimension | Weight | What it measures |
|---|---|---|
| Text concision | 30% | Are headlines takeaway-driven? Is body text within limits? Are bullets crisp? |
| Layout quality | 25% | Does the template match the content? Are slots filled correctly? No overlap or overflow? |
| Visual quality | 25% | Are images/charts relevant, correctly sized, and high-resolution? Is whitespace balanced? |
| Color/readability | 20% | Do colors follow the theme tokens? Is contrast sufficient? Are fonts consistent? |
