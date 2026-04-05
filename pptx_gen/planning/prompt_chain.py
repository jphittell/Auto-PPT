"""Five-step planning orchestration boundary."""

from __future__ import annotations

from typing import Protocol

from pptx_gen.planning.schemas import (
    DeckBrief,
    OutlineSpec,
    PresentationSpec,
    RetrievalPlan,
    RetrievedChunk,
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


def revise_for_design_quality(*args, **kwargs) -> PresentationSpec:
    # TODO: implement design-only revision pass that preserves citations.
    raise NotImplementedError

