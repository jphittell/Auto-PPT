"""Five-step planning orchestration boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pptx_gen.planning.schemas import (
    DeckBrief,
    DesignRefinement,
    OutlineSpec,
    PresentationSpec,
    RetrievalPlan,
)


class StructuredLLMClient(Protocol):
    """Model-agnostic structured-output boundary for later implementation."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
        """Return schema-valid JSON for the requested contract."""


def collect_deck_brief(*args, **kwargs) -> DeckBrief:
    # TODO: implement brief collection with LiteLLM JSON mode.
    raise NotImplementedError


def generate_outline(*args, **kwargs) -> OutlineSpec:
    # TODO: implement outline generation from DeckBrief.
    raise NotImplementedError


def build_retrieval_plan(*args, **kwargs) -> RetrievalPlan:
    # TODO: implement up-to-5 retrieval queries per slide.
    raise NotImplementedError


def generate_presentation_spec(*args, **kwargs) -> PresentationSpec:
    # TODO: implement SlideSpec generation from outline plus RetrievedChunk evidence.
    raise NotImplementedError


def revise_for_design_quality(
    spec: PresentationSpec,
    *,
    qa_report_json: str,
    render_artifact_path: str | Path | None,
    llm_client: StructuredLLMClient | None = None,
    user_brief: str | None = None,
    enabled: bool = False,
) -> tuple[PresentationSpec, str, bool]:
    """Run one optional design-only refinement round and preserve citations."""

    if not enabled:
        return spec, "refinement disabled", False
    if render_artifact_path is None or not Path(render_artifact_path).exists():
        return spec, "refinement skipped: render artifact unavailable", False
    if llm_client is None:
        return spec, "refinement skipped: no llm client configured", False

    system_prompt = _load_prompt("step0_system.md")
    user_prompt = _load_prompt("step5_design_revise.md")
    replacements = {
        "{presentation_spec_json}": spec.model_dump_json(indent=2),
        "{style_tokens_json}": spec.theme.style_tokens.model_dump_json(indent=2),
        "{qa_report_json}": qa_report_json,
        "{render_artifact_path}": str(render_artifact_path),
        "{user_brief}": user_brief or "",
    }
    for placeholder, value in replacements.items():
        user_prompt = user_prompt.replace(placeholder, value)
    result = llm_client.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_name="DesignRefinement",
    )
    refinement = DesignRefinement.model_validate(result)
    revised = refinement.presentation_spec
    _ensure_citations_preserved(spec, revised)
    return revised, "; ".join(refinement.rationale) or "refinement applied", refinement.applied


def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / name
    return path.read_text(encoding="utf-8")


def _ensure_citations_preserved(original: PresentationSpec, revised: PresentationSpec) -> None:
    original_citations = {
        (slide.slide_id, block.block_id): [citation.model_dump() for citation in block.source_citations]
        for slide in original.slides
        for block in slide.blocks
    }
    revised_citations = {
        (slide.slide_id, block.block_id): [citation.model_dump() for citation in block.source_citations]
        for slide in revised.slides
        for block in slide.blocks
    }

    if original_citations.keys() != revised_citations.keys():
        raise ValueError("design refinement must preserve slide/block identity")

    for key, citations in original_citations.items():
        if citations != revised_citations[key]:
            raise ValueError(f"design refinement must preserve citations for {key[0]}:{key[1]}")
