# Planning Content Quality Learnings

Date: 2026-04-10

## Summary

Thin and repetitive slide content was not primarily a slide-spec prompting failure. The larger issue
was that the API planning path was starving the slide-spec LLM of evidence and specificity before it
ever generated slide content.

## Confirmed Learnings

1. The API path was using deterministic fallbacks too early, even when a structured LLM client was available.
   - `/api/plan` built the deck brief with `llm_client=None`.
   - `/api/plan` also built the outline with `llm_client=None`.
   - `/api/generate` built the retrieval plan with `llm_client=None`.
   - As a result, the only LLM-assisted stage in the live API flow was slide-spec generation, which was too late to recover from weak upstream inputs.

2. Retrieval breadth was too narrow to support synthesis-heavy slides.
   - `execute_retrieval_plan()` was capped at `max_results_per_query=2` and `max_chunks_per_slide=5`.
   - In practice, duplicate hits and score filtering often reduced the real evidence set to only a few chunks per slide.
   - Expanding both limits together matters; increasing only the chunk cap would not materially improve evidence coverage.

3. The hardcoded pipeline-story shortcut was leaking internal product jargon into audience-facing decks.
   - `_is_pipeline_story()` matched broadly on terms like `ingestion`, `retrieval`, and `layout`.
   - That branch injected canned messages such as `Hybrid architecture`, `Design quality strategies`, and `Implementation implications`.
   - These strings made deterministic planning outputs sound like internal engineering shorthand instead of presentation-ready business framing.

4. The step 4 prompt must stay aligned with schema validators, not just the intended rubric.
   - `schemas.py` correctly enforced a 70-word cap.
   - `step4_slidespec.md` still contained two `80-word` references.
   - Prompt/schema drift creates avoidable validation failures and misleading instructions to the LLM.

5. Deterministic fallback remains useful and should be preserved intentionally.
   - The fix is not to force LLM-only planning.
   - The right behavior is: use the structured client earlier when configured, but keep the `None` path deterministic for tests and offline use.
   - Existing API tests already protect this pattern by resetting `_STRUCTURED_LLM_CLIENT = False`.

## Changes Applied

1. The API now threads `_get_optional_structured_llm_client()` into:
   - `collect_deck_brief(...)`
   - `generate_outline(...)`
   - `build_retrieval_plan(...)`

2. Retrieval defaults were widened to:
   - `max_results_per_query = 4`
   - `max_chunks_per_slide = 10`

3. The `_is_pipeline_story()` hardcoded message path was removed from deterministic outline generation.

4. Both remaining `80-word` references in `pptx_gen/planning/prompts/step4_slidespec.md` were corrected to `70-word`.

5. Tests were updated to validate the new intended behavior instead of the removed canned copy.

## Final Validation Status

- Targeted planning and API tests pass.
- Full test suite passes: `165 passed, 1 warning`.
- The remaining warning is the pre-existing third-party `chromadb` deprecation warning.

## Recommended Follow-Up

- Regenerate the same PDF-driven deck and inspect whether slide bullets, callouts, and headlines now pull from distinct retrieved evidence.
- If content quality still feels thin after these changes, inspect step 3 query diversity before modifying the step 4 slide-spec prompt again.
- Treat prompt/schema wording alignment as regression-test territory whenever planning validators enforce hard limits.
