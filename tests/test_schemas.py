from __future__ import annotations

import pytest
from pydantic import ValidationError

from pptx_gen.layout.schemas import ResolvedDeckLayout, StyleTokens
from pptx_gen.pipeline import ExportJob, ExportKind, ExportStatus
from pptx_gen.planning.schemas import DeckBrief, PresentationSpec, RetrievedChunk


def test_presentation_spec_rejects_duplicate_slide_ids(make_presentation_spec, make_slide) -> None:
    payload = make_presentation_spec(
        slides=[
            make_slide(slide_id="s1"),
            make_slide(slide_id="s1"),
        ]
    )

    with pytest.raises(ValidationError):
        PresentationSpec(**payload)


def test_presentation_spec_rejects_duplicate_block_ids(make_presentation_spec, make_slide, make_block) -> None:
    payload = make_presentation_spec(
        slides=[
            make_slide(
                blocks=[
                    make_block(block_id="b1"),
                    make_block(block_id="b1"),
                ]
            )
        ]
    )

    with pytest.raises(ValidationError):
        PresentationSpec(**payload)


def test_presentation_spec_enforces_word_cap(make_presentation_spec, make_slide, make_block) -> None:
    long_text = " ".join(["word"] * 71)
    payload = make_presentation_spec(
        slides=[
            make_slide(
                blocks=[
                    make_block(content={"text": long_text}),
                ]
            )
        ]
    )

    with pytest.raises(ValidationError):
        PresentationSpec(**payload)


def test_resolved_layout_rejects_duplicate_element_ids() -> None:
    with pytest.raises(ValidationError):
        ResolvedDeckLayout(
            deck_id="deck-1",
            slides=[
                {
                    "slide_id": "s1",
                    "elements": [
                        {
                            "element_id": "el1",
                            "kind": "textbox",
                            "x": 0.5,
                            "y": 0.5,
                            "w": 2.0,
                            "h": 1.0,
                            "z": 0,
                            "data_ref": "b1",
                        },
                        {
                            "element_id": "el1",
                            "kind": "image",
                            "x": 2.8,
                            "y": 0.5,
                            "w": 2.0,
                            "h": 1.5,
                            "z": 1,
                            "data_ref": "b2",
                        },
                    ],
                }
            ],
        )


def test_retrieved_chunk_requires_source_and_locator() -> None:
    with pytest.raises(ValidationError):
        RetrievedChunk(chunk_id="doc:e1:0", text="hello", locator="doc:page1")

    with pytest.raises(ValidationError):
        RetrievedChunk(chunk_id="doc:e1:0", text="hello", source_id="doc")

    with pytest.raises(ValidationError):
        RetrievedChunk(
            chunk_id="doc:e1:0",
            text="hello",
            source_id="doc",
            locator="doc:page1",
            score=1.1,
        )


def test_export_job_rules_and_transitions() -> None:
    with pytest.raises(ValidationError):
        ExportJob(
            id="job-1",
            kind=ExportKind.RENDER_PPTX,
            status=ExportStatus.IN_PROGRESS,
            artifact_urls=["https://example.com/file.pptx"],
        )

    job = ExportJob(
        id="job-2",
        kind=ExportKind.RENDER_PPTX,
        status=ExportStatus.SUCCESS,
        artifact_urls=["https://example.com/file.pptx"],
    )

    assert job.status is ExportStatus.SUCCESS
    ExportJob.ensure_valid_transition(ExportStatus.IN_PROGRESS, ExportStatus.SUCCESS)
    with pytest.raises(ValueError):
        ExportJob.ensure_valid_transition(ExportStatus.SUCCESS, ExportStatus.FAILED)


def test_questions_for_user_schema_defaults() -> None:
    brief = DeckBrief(
        audience="Executive leadership",
        goal="Summarize quarterly performance",
        tone="Professional",
        slide_count_target=10,
        source_corpus_ids=["doc-finance"],
    )

    assert brief.questions_for_user == []

    brief_with_questions = DeckBrief(
        audience="Executive leadership",
        goal="Summarize quarterly performance",
        tone="Professional",
        slide_count_target=10,
        source_corpus_ids=["doc-finance"],
        questions_for_user=["Which quarter should be emphasized?"],
    )
    assert brief_with_questions.questions_for_user == ["Which quarter should be emphasized?"]


def test_style_tokens_reject_invalid_hex(style_tokens_payload) -> None:
    payload = dict(style_tokens_payload)
    payload["colors"] = dict(style_tokens_payload["colors"])
    payload["colors"]["accent"] = "blue"

    with pytest.raises(ValidationError):
        StyleTokens(**payload)
