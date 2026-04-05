"""QA report contracts and validator boundaries."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class QAStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class QAItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: str = Field(min_length=1)
    status: QAStatus
    message: str = Field(min_length=1)


class QAReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1)
    passed: bool
    items: list[QAItem] = Field(default_factory=list)


def validate_layout(*args, **kwargs) -> QAReport:
    # TODO: implement overflow, overlap, alignment, contrast, and citation validators.
    raise NotImplementedError("Layout QA is not implemented in Phase 1.")


def validate_export(*args, **kwargs) -> QAReport:
    # TODO: implement post-export QA checks on the PPTX artifact.
    raise NotImplementedError("Export QA is not implemented in Phase 1.")

