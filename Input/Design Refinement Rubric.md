# Design Refinement Rubric — Auto PPT v1

**Version:** 1.0.0
**Status:** Authoritative for v1
**Scope:** Rules for the design-only refinement pass (step 5 of the planning chain).

---

## 1. Purpose

After the initial `PresentationSpec` is generated, a design refinement pass reviews the spec
for visual quality issues and applies fixes. This rubric defines what the refinement pass
should optimize for, what it must preserve, and what it must not change.

The refinement pass corresponds to `step5_design_revise.md` in the prompt chain and produces
a `DesignRefinement` object.

---

## 2. Core Principle

**Refinement is design-only.** It adjusts how content is presented, not what content says.
If the content itself is wrong, that's a planning failure — refinement does not fix it.

---

## 3. Refinement Checklist

The refinement pass should evaluate each slide against these criteria, in priority order.

### Priority 1: Hard violations (must fix)

| Check | What to look for | Fix |
|---|---|---|
| **Element overlap** | Two elements share more than 1% of slide area | Resize or reposition the smaller element. If impossible, flag for template change. |
| **Boundary overflow** | An element extends beyond the slide edges (13.333 x 7.5) | Shrink the element to fit within margins. |
| **Missing citations** | Content/summary/appendix block with no `source_citations` | Add citation from the retrieved chunks. If no chunk matches, flag — do not fabricate. |
| **Word count exceeded** | Non-appendix slide exceeds 70-word cap | Cut redundant phrases, merge overlapping bullets, or move detail to speaker notes. |
| **Template-purpose mismatch** | template_key's `allowed_purposes` excludes the slide's `purpose` | Change template_key to a compatible one per Template Selection Rules. |

### Priority 2: Visual quality (should fix)

| Check | What to look for | Fix |
|---|---|---|
| **Text density too high** | More than 5 bullets, or average bullet >15 words | Merge bullets, move detail to speaker notes, or split into two slides. |
| **Poor headline** | Headline describes the topic instead of the takeaway | Rewrite to state the insight: "Revenue Up 18% YoY" not "Revenue Performance." |
| **Empty slots** | Template has a slot that the content doesn't fill (e.g., takeaway in content.1col) | Add a takeaway block, or switch to a simpler template. |
| **Imbalanced columns** | In 2col layout, one column has 3x more content than the other | Redistribute content between columns, or switch to 1col. |
| **Awkward chart placement** | Chart in a text slot, or text in a chart slot | Correct the block kind and slot assignment. |

### Priority 3: Polish (nice to fix)

| Check | What to look for | Fix |
|---|---|---|
| **Inconsistent spacing** | Some slides use different margin assumptions than the template registry | Ensure all coordinates align with the template's declared geometry. |
| **Contrast issues** | Light text on light background, or accent color too similar to background | Use `colors.text` for body, `colors.accent` for highlights. Verify against `colors.bg`. |
| **Speaker notes missing** | Content/summary slide has empty `speaker_notes` | Add 20-40 words of narrative context. |
| **Redundant slides** | Two adjacent slides make the same point | Merge into one slide with the stronger framing. |
| **Citation format** | `locator` field is vague (e.g., "page1" without doc context) | Expand to `doc_id:page_N` format. |

---

## 4. What Refinement Must Preserve

These elements must NOT be modified during refinement:

1. **Existing valid citations.** Refinement may add citations but must never remove or weaken
   a citation that correctly links a claim to a source.

2. **Slide order and count.** Refinement does not reorder, add, or remove slides. If a slide
   is genuinely broken, it should be flagged in `rationale`, not silently dropped.

3. **Factual content.** Numbers, dates, names, and quoted text must remain unchanged. If a
   number appears wrong, flag it — do not "correct" it during refinement.

4. **Schema version.** The `schema_version` field on the `PresentationSpec` must not change.

5. **Theme and style tokens.** Refinement does not change fonts, colors, spacing, or
   `source_policy`. Those are set in the brief and are immutable for the deck.

---

## 5. What Refinement Must Not Do

| Forbidden action | Why |
|---|---|
| Re-plan the deck narrative | Refinement is design-only. Narrative changes require re-running steps 1-4. |
| Add new slides | Slide count is set in the outline. Splitting a slide requires outline revision. |
| Remove slides | Even a bad slide should be flagged, not deleted silently. |
| Change the audience or goal | These are brief-level decisions, not refinement-level. |
| Fabricate citations | If no source chunk supports a claim, flag it. Never invent a `source_id`. |
| Override template geometry | Refinement works within the template's declared slots. It does not create custom coordinates. |
| Reduce font sizes below minimum | If content doesn't fit, cut words — don't shrink text below 18pt body / 28pt headline. |

---

## 6. Refinement Output

The refinement pass produces a `DesignRefinement` object:

```json
{
  "schema_version": "1.0.0",
  "applied": true,
  "rationale": [
    "Slide s3: reduced headline from 14 words to 9 by removing redundant qualifier",
    "Slide s5: moved 2 bullets to speaker_notes to stay under 70-word cap",
    "Slide s7: changed template from content.1col to table.full — content is tabular"
  ],
  "presentation_spec": { ... }
}
```

Rules for `rationale`:
- One entry per change made.
- Each entry names the slide_id and describes what changed and why.
- If `applied` is `false`, `rationale` should explain why no changes were needed.
- Maximum 15 rationale entries. If more changes are needed, the spec should be re-planned.

---

## 7. Scoring Guide for Automated Evaluation

When building an automated judge for refinement quality:

| Dimension | Score 0 (fail) | Score 1 (pass) | Score 2 (excellent) |
|---|---|---|---|
| Overlap | Any two elements overlap >1% | No overlap | No overlap, and all elements have >0.1" clearance |
| Word density | Any non-appendix slide >70 words | All slides within cap | All slides within cap AND average <50 words |
| Headline quality | Headlines are topic-only ("Revenue") | Headlines state a finding | Headlines are action-oriented takeaways |
| Citation coverage | Missing citations on content blocks | All content blocks cited | All citations include locator AND quote |
| Template fit | Template-purpose mismatch exists | All templates valid | Templates are optimal per selection rules (not just valid) |
| Speaker notes | Missing on >50% of content slides | Present on all content slides | Present and between 20-60 words on all |
