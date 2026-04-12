"""Schema contracts for planning and SlideSpec generation."""

from __future__ import annotations

import datetime as dt
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pptx_gen.layout.schemas import StyleTokens


SCHEMA_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"


class SlidePurpose(str, Enum):
    TITLE = "title"
    SECTION = "section"
    CONTENT = "content"
    SUMMARY = "summary"
    CLOSING = "closing"
    AGENDA = "agenda"
    APPENDIX = "appendix"


class SlideArchetype(str, Enum):
    GENERIC = "generic"
    EXECUTIVE_SUMMARY = "executive_summary"
    EXECUTIVE_OVERVIEW = "executive_overview"
    ARCHITECTURE_GRID = "architecture_grid"
    COMPARISON = "comparison"
    METRICS = "metrics"
    CHART = "chart"
    TIMELINE = "timeline"    # timeline.roadmap, process.steps
    MATRIX = "matrix"        # matrix.2x2
    TEAM = "team"            # team.grid
    PROCESS = "process"      # process.steps
    DASHBOARD = "dashboard"  # dashboard.kpi
    FINANCIAL = "financial"  # financial.table
    STATUS = "status"        # status.rag


class PresentationBlockKind(str, Enum):
    TEXT = "text"
    BULLETS = "bullets"
    IMAGE = "image"
    TABLE = "table"
    CHART = "chart"
    KPI_CARDS = "kpi_cards"
    QUOTE = "quote"
    CALLOUT = "callout"
    TIMELINE = "timeline"          # ordered milestones [{label, date?, description?}]
    PEOPLE_CARDS = "people_cards"  # [{name, title, bio?, image_ref?}]
    STEPS = "steps"                # numbered process steps [{number, title, description}]
    MATRIX = "matrix"              # 2×2 quadrant [{quadrant: tl|tr|bl|br, title, items:[]}]
    STATUS_CARDS = "status_cards"  # RAG status rows [{label, status: red|amber|green, note?}]


class PIIFlag(str, Enum):
    NAME = "name"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    ID_NUMBER = "id_number"
    HEALTH = "health"
    FINANCIAL = "financial"


class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    quote: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class BlockSecurity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pii_flags: list[PIIFlag] = Field(default_factory=list)
    allowed_audiences: list[str] = Field(default_factory=list)


class LayoutIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str = Field(min_length=1)
    strict_template: bool = True


class PresentationBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1)
    kind: PresentationBlockKind
    content: dict[str, Any]
    source_citations: list[SourceCitation] = Field(default_factory=list)
    style_overrides: dict[str, Any] | None = None
    asset_refs: list[str] = Field(default_factory=list)
    x_security: BlockSecurity | None = None
    extensions: dict[str, Any] | None = None


class SlideSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    purpose: SlidePurpose
    layout_intent: LayoutIntent
    archetype: SlideArchetype | None = None
    headline: str = Field(min_length=1)
    speaker_notes: str = ""
    blocks: list[PresentationBlock] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_block_ids(self) -> "SlideSpec":
        seen: set[str] = set()
        for block in self.blocks:
            if block.block_id in seen:
                raise ValueError(f"duplicate block_id within slide: {block.block_id}")
            seen.add(block.block_id)
        return self


class DeckTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    style_tokens: StyleTokens


class DeckBriefExtensions(BaseModel):
    """Typed extensions so structured LLM output reliably populates these fields."""

    model_config = ConfigDict(extra="allow")

    document_title: str = ""
    one_sentence_thesis: str = ""
    key_takeaways: list[str] = Field(default_factory=list)
    deck_archetype: str = ""
    user_request: str = ""
    audience_focus: str = ""
    source_preview: str = ""
    source_format: str = ""
    source_slide_count: int = 0
    source_slide_types: dict[str, int] = Field(default_factory=dict)
    source_slide_blueprint: list[dict[str, Any]] = Field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-compatible access for backward compatibility with existing code."""
        try:
            value = getattr(self, key)
            if value is None or value == "" or value == []:
                return default
            return value
        except AttributeError:
            # Check extra fields
            extra = self.__pydantic_extra__ or {}
            return extra.get(key, default)


class DeckBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=SCHEMA_VERSION_PATTERN)
    audience: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    tone: str = Field(min_length=1)
    slide_count_target: int = Field(ge=1)
    source_corpus_ids: list[str] = Field(min_length=1)
    questions_for_user: list[str] = Field(default_factory=list)
    extensions: DeckBriefExtensions = Field(default_factory=DeckBriefExtensions)


class OutlineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    purpose: SlidePurpose
    archetype: SlideArchetype | None = None
    headline: str = Field(min_length=1)
    message: str = Field(min_length=1)
    evidence_queries: list[str] = Field(default_factory=list)
    template_key: str | None = None


class OutlineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=SCHEMA_VERSION_PATTERN)
    outline: list[OutlineItem] = Field(min_length=1)
    questions_for_user: list[str] = Field(default_factory=list)
    extensions: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_unique_slide_ids(self) -> "OutlineSpec":
        seen: set[str] = set()
        for item in self.outline:
            if item.slide_id in seen:
                raise ValueError(f"duplicate slide_id in outline: {item.slide_id}")
            seen.add(item.slide_id)
        return self


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    doc_ids: list[str] = Field(default_factory=list)
    min_date: dt.date | None = None


class RetrievalPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    queries: list[RetrievalQuery] = Field(min_length=1, max_length=5)


class RetrievalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=SCHEMA_VERSION_PATTERN)
    retrieval_plan: list[RetrievalPlanItem] = Field(min_length=1)
    questions_for_user: list[str] = Field(default_factory=list)
    extensions: dict[str, Any] | None = None


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] | None = None


class PresentationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=SCHEMA_VERSION_PATTERN)
    title: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    language: str = Field(default="en-US", min_length=2)
    theme: DeckTheme
    slides: list[SlideSpec] = Field(min_length=1)
    questions_for_user: list[str] = Field(default_factory=list)
    extensions: dict[str, Any] | None = None

    @field_validator("questions_for_user", mode="before")
    @classmethod
    def default_questions(cls, value: list[str] | None) -> list[str]:
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def validate_slides(self) -> "PresentationSpec":
        seen_slide_ids: set[str] = set()
        citation_required_kinds = {
            PresentationBlockKind.TEXT,
            PresentationBlockKind.BULLETS,
            PresentationBlockKind.TABLE,
            PresentationBlockKind.CHART,
            PresentationBlockKind.KPI_CARDS,
            PresentationBlockKind.QUOTE,
            PresentationBlockKind.CALLOUT,
        }
        citation_required_purposes = {
            SlidePurpose.CONTENT,
            SlidePurpose.SUMMARY,
            SlidePurpose.CLOSING,
        }
        word_capped_kinds = {
            PresentationBlockKind.TEXT,
            PresentationBlockKind.BULLETS,
            PresentationBlockKind.TABLE,
            PresentationBlockKind.CHART,
            PresentationBlockKind.QUOTE,
        }

        for slide in self.slides:
            if slide.slide_id in seen_slide_ids:
                raise ValueError(f"duplicate slide_id in presentation: {slide.slide_id}")
            seen_slide_ids.add(slide.slide_id)

            if slide.purpose is not SlidePurpose.CLOSING:
                for block in slide.blocks:
                    if block.kind not in word_capped_kinds:
                        continue
                    word_count = _count_words(block.content)
                    if word_count > 150:
                        raise ValueError(f"slide {slide.slide_id} exceeds 150-word content cap")

        return self


def _count_words(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(re.findall(r"\b\w+\b", value))
    if isinstance(value, list):
        return sum(_count_words(item) for item in value)
    if isinstance(value, dict):
        return sum(_count_words(item) for item in value.values())
    return len(re.findall(r"\b\w+\b", str(value)))


class DesignRefinement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=SCHEMA_VERSION_PATTERN)
    applied: bool = True
    rationale: list[str] = Field(default_factory=list)
    presentation_spec: PresentationSpec
