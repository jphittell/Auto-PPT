# Gold Fixture Set

Schema-valid JSON examples for every planning stage. Each file validates against
the corresponding Pydantic model in `pptx_gen/planning/schemas.py`.

## File naming convention

```
{stage}_{scenario}_{quality}.json
```

- **stage:** `brief`, `outline`, `retrieval`, `spec`
- **scenario:** short name for the use case
- **quality:** `good` (exemplary), `bad` (common failure), `edge` (edge case)

## Scenarios

| ID | Description | Source corpus |
|----|-------------|---------------|
| q1_review | Q1 business review for board | Financial PDF + model XLSX + pipeline report |
| oracle_hcm | Oracle HCM implementation options analysis | HCM release notes + integration guide |
| product_launch | SaaS product launch deck | Product spec + competitive analysis |
| incident_retro | Post-incident retrospective | Incident timeline + RCA doc |
