# Template Selection Rules — Auto PPT v1

**Version:** 1.0.0
**Status:** Authoritative for v1
**Scope:** Maps slide intent to a canonical `template_key` from the template registry.

---

## 1. Purpose

The planning stage must assign a `template_key` to every slide in the outline. This document
defines the product rules that govern that assignment. The LLM should follow these rules; the
layout resolver enforces them via `allowed_purposes` on each template definition.

---

## 2. Primary Selection Rules

These rules are ordered by specificity. Apply the first matching rule.

### Title and structural slides

| Slide intent | template_key | When to use |
|---|---|---|
| Opening title slide | `title.hero` | Always the first slide. Contains deck title, subtitle, presenter, date, logo. |
| Agenda / table of contents | `agenda.list` | Lists 3-6 topics the deck will cover. Always the second slide. |
| Section divider | `section.header` | Signals a new major section. Use when the deck has 3+ sections and needs visual breaks. |

### Content slides — text-dominant

| Slide intent | template_key | When to use |
|---|---|---|
| Single narrative or bullet list | `content.1col` | Default for any content slide with one text block and an optional takeaway. |
| Text + supporting visual | `content.2col.text_image` | Left column is bullets or narrative; right column is a photo, screenshot, or chart. |
| Compare 3 concepts/options | `content.3col.cards` | Three self-contained cards, each with a heading and 2-3 bullets. |

### Content slides — data-dominant

| Slide intent | template_key | When to use |
|---|---|---|
| 2-4 key metrics | `kpi.3up` | Each block is a single metric with value, delta, and context. Use for executive dashboards. |
| Chart as primary evidence | `chart.full` | Full-width chart with headline and citation footer. Use when the data IS the message. |
| Tabular data | `table.full` | Structured rows and columns. Use for budgets, feature comparisons, timelines with >4 items. |

### Special-purpose slides

| Slide intent | template_key | When to use |
|---|---|---|
| Executive overview with cards | `executive.overview` | Summary + insight + 4-6 capability cards + footer metrics. Use for "state of the business" slides. |
| Architecture or system diagram | `architecture.grid` | Summary + 6 component cards in a 2x3 grid + footer note. Use for system overviews. |
| Summary / closing slide | `content.1col` | Reuse 1col for closing slides. 3 bullets max: what happened, what to do, when. |
| Appendix / backup detail | `appendix.details` | Dense text with thin margins. Exempt from word-count caps. |

---

## 3. Decision Tiebreakers

When multiple templates could work, use these tiebreakers:

1. **Data over narrative.** If the slide's message is primarily a number or trend, prefer
   `kpi.3up` or `chart.full` over `content.1col`.

2. **Visual evidence wins.** If a supporting image or chart exists and is relevant, prefer
   `content.2col.text_image` over `content.1col`.

3. **Cards for comparison only.** Use `content.3col.cards` only when comparing 3 distinct
   items. Do not use it for a single list of 3 points — that's `content.1col` with bullets.

4. **Tables for structured data.** If the content has 4+ rows of structured columns, use
   `table.full`. Do not force tabular data into bullets.

5. **One chart per slide.** Never put two charts on the same slide. If two charts are needed,
   create two slides.

6. **KPIs need numbers.** Only use `kpi.3up` when you have 2-3 actual numeric metrics with
   deltas. Do not use it for qualitative takeaways.

---

## 4. Purpose-to-Template Compatibility Matrix

This matrix reflects the `allowed_purposes` field on each `TemplateDefinition` in the registry.

| template_key | title | agenda | section | content | summary | appendix |
|---|---|---|---|---|---|---|
| `title.hero` | yes | — | — | — | — | — |
| `agenda.list` | — | yes | — | — | — | — |
| `section.header` | — | — | yes | — | — | — |
| `content.1col` | — | — | — | yes | yes | — |
| `content.2col.text_image` | — | — | — | yes | — | — |
| `content.3col.cards` | — | — | — | yes | — | — |
| `kpi.3up` | — | — | — | yes | yes | — |
| `chart.full` | — | — | — | yes | yes | — |
| `table.full` | — | — | — | yes | — | yes |
| `executive.overview` | — | — | — | yes | yes | — |
| `architecture.grid` | — | — | — | yes | yes | — |
| `appendix.details` | — | — | — | — | — | yes |

If the planning stage assigns a template_key whose `allowed_purposes` does not include the
slide's `purpose`, the layout resolver must reject the slide with a validation error.

---

## 5. Archetype Affinity

When an `OutlineItem` carries an `archetype`, it provides an additional signal:

| archetype | Preferred template_key | Fallback |
|---|---|---|
| `executive_overview` | `executive.overview` | `content.1col` |
| `architecture_grid` | `architecture.grid` | `content.3col.cards` |
| `comparison` | `content.3col.cards` | `content.2col.text_image` |
| `metrics` | `kpi.3up` | `chart.full` |
| `generic` | Use the primary selection rules above | — |

---

## 6. Slide Count Guidance

| Deck size | Structural slides | Content slides |
|---|---|---|
| 3-5 slides | title + 1-3 content + summary | No agenda or section headers |
| 6-8 slides | title + agenda + 4-6 content + summary | Section headers optional |
| 9-12 slides | title + agenda + 6-9 content + summary | Section headers recommended every 3-4 content slides |
| 12+ slides | title + agenda + content + summary | Section headers required; consider appendix slides |
