# Retrieval Query Cookbook — Auto PPT v1

**Version:** 1.0.0
**Status:** Authoritative for v1
**Scope:** Examples of good evidence queries for the planning stage's RetrievalPlan.

---

## 1. Purpose

The planning stage generates `RetrievalQuery` objects for each slide. Query quality directly
determines whether the vector index returns relevant chunks. This cookbook provides examples
of bad, better, and ideal queries for each common retrieval intent.

---

## 2. Query Design Principles

1. **Be specific about what you need.** "revenue" is too broad. "Q1 2026 total revenue figure
   and year-over-year growth rate" tells the retriever exactly what to find.

2. **Name the entity.** Include company names, product names, time periods, and metric names.
   The index is keyword-sensitive even when using embeddings.

3. **One concept per query.** Don't combine "revenue growth AND margin expansion" into one query.
   Split them so each retrieval has a focused target.

4. **Include the comparison basis.** If you need a delta, name both the numerator and denominator
   periods: "Q1 2026 vs Q1 2025" not just "Q1 growth."

5. **Max 5 queries per slide.** More than 5 dilutes relevance. If you need more, the slide
   should be split.

---

## 3. Query Examples by Intent Type

### 3.1 Summary Query

**User intent:** Get a high-level overview of the document's main findings.

| Quality | Query |
|---|---|
| Bad | "summary" |
| Better | "executive summary of the report" |
| Ideal | "Key findings and recommendations from the Oracle HCM 26B Global HR release" |

**Why the ideal works:** Names the specific document, asks for findings AND recommendations,
gives the retriever enough signal to find the abstract or conclusion section.

---

### 3.2 Metric Lookup Query

**User intent:** Find a specific number or KPI.

| Quality | Query |
|---|---|
| Bad | "revenue" |
| Better | "Q1 2026 revenue" |
| Ideal | "Q1 2026 total revenue figure in dollars and year-over-year percentage growth" |

**Why the ideal works:** Specifies the time period, the metric name, the unit, and the
comparison type. This helps the retriever distinguish between "revenue mentioned in passing"
and "the actual revenue figure."

---

### 3.3 Comparison Query

**User intent:** Compare two things — products, periods, regions, options.

| Quality | Query |
|---|---|
| Bad | "APAC vs NA" |
| Better | "APAC and NA revenue comparison" |
| Ideal | "APAC pipeline growth rate Q1 2026 compared to NA and EMEA growth rates same period" |

**Why the ideal works:** Names all three entities being compared, specifies the metric
(pipeline growth rate), and pins the time period. The retriever can now find passages that
discuss regional performance side by side.

---

### 3.4 Quote / Citation Query

**User intent:** Find a direct quote or authoritative statement to cite.

| Quality | Query |
|---|---|
| Bad | "CEO quote" |
| Better | "CEO statement about growth strategy" |
| Ideal | "Direct quote from executive leadership on H1 2026 hiring plan rationale and growth projections" |

**Why the ideal works:** Specifies the source (executive leadership), the topic (hiring plan),
and what kind of statement (rationale and projections). This finds attributable quotes rather
than general mentions.

---

### 3.5 Methodology / Process Query

**User intent:** Find how something was done — methodology, approach, process steps.

| Quality | Query |
|---|---|
| Bad | "methodology" |
| Better | "data collection methodology" |
| Ideal | "Integration approach options and evaluation criteria for Oracle HCM implementation" |

**Why the ideal works:** Names the specific system, the type of methodology (integration
approach), and what aspect matters (evaluation criteria). This avoids retrieving every mention
of "methodology" in the corpus.

---

### 3.6 Timeline / Milestone Query

**User intent:** Find dates, deadlines, or phased plans.

| Quality | Query |
|---|---|
| Bad | "timeline" |
| Better | "project timeline and milestones" |
| Ideal | "Implementation timeline phases and target completion dates for Oracle HCM 26B deployment" |

**Why the ideal works:** Specifies the project, asks for both phases and dates, and names the
deployment. The retriever can now find Gantt chart descriptions or phased rollout sections.

---

### 3.7 Risk / Issue Query

**User intent:** Find identified risks, issues, or concerns.

| Quality | Query |
|---|---|
| Bad | "risks" |
| Better | "operational risks and mitigations" |
| Ideal | "Supplier concentration risk in data pipeline and proposed mitigation actions with deadlines" |

**Why the ideal works:** Names the specific risk (supplier concentration), the domain (data
pipeline), and what's needed (mitigations AND deadlines). This finds the risk register entry,
not just passing mentions of "risk."

---

### 3.8 Recommendation / Action Item Query

**User intent:** Find what the document recommends doing.

| Quality | Query |
|---|---|
| Bad | "recommendations" |
| Better | "recommended next steps" |
| Ideal | "Recommended actions for board approval including hiring plan and supplier diversification review" |

**Why the ideal works:** Names the specific actions expected and the approval body. This finds
the recommendation section rather than scattered suggestions.

---

## 4. Query Patterns for Common Slide Types

| Slide type | Typical query count | Query pattern |
|---|---|---|
| Title slide | 0 | No retrieval needed — title comes from the brief |
| Agenda slide | 0 | No retrieval — agenda is derived from the outline |
| KPI slide | 2-3 | One query per metric: "Q1 2026 [metric name] [unit] and [comparison basis]" |
| Narrative content | 2-4 | One for the main claim, one for supporting evidence, one for the counterpoint or context |
| Chart slide | 1-2 | One for the underlying data, one for the narrative interpretation |
| Table slide | 1-2 | One for the structured data, one for any context or notes |
| Risk slide | 2-3 | One per risk: "[risk name] description, impact assessment, and mitigation plan" |
| Summary slide | 0-1 | Optional: one query to verify the closing recommendation matches the evidence |

---

## 5. Anti-Patterns

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| Single-word queries | Too broad; retriever returns noise | Add entity, time, metric |
| Compound queries | "revenue AND margin AND headcount" retrieves passages that mention any one of these, not all three | Split into separate queries |
| Leading questions | "Why did revenue increase?" presumes a direction; biases retrieval | "Q1 2026 revenue change drivers and contributing factors" |
| Negation queries | "revenue excluding APAC" is hard for embedding models | Query for total revenue, then query for APAC separately; let planning stage compute the difference |
| Duplicate queries across slides | Same query on slide 3 and slide 5 wastes retrieval budget | Reuse the retrieved chunk by `chunk_id` reference |
