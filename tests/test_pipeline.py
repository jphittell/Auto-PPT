from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pptx_gen.pipeline import ExportStatus, generate_deck
from pptx_gen.planning.prompt_chain import revise_for_design_quality
from pptx_gen.planning.schemas import DesignRefinement, PresentationSpec


class FakeStructuredClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict:
        assert schema_name == "DesignRefinement"
        assert "PresentationSpec" in user_prompt
        return self.payload


def test_generate_deck_without_refinement_writes_pptx(
    tmp_path: Path,
    make_presentation_spec,
    make_slide,
    make_block,
) -> None:
    spec = PresentationSpec(
        **make_presentation_spec(
            slides=[
                make_slide(
                    blocks=[
                        make_block(
                            content={"text": "Revenue improved meaningfully this quarter."},
                        )
                    ]
                )
            ]
        )
    )

    result = generate_deck(presentation_spec=spec, output_path=tmp_path / "deck.pptx", enable_refinement=False)

    assert Path(result.output_path).exists()
    assert result.export_job.status is ExportStatus.SUCCESS
    assert result.refinement_applied is False
    assert result.resolved_layout.slides


def test_generate_deck_from_source_runs_end_to_end(
    tmp_path: Path,
    deterministic_embedder,
    monkeypatch,
) -> None:
    monkeypatch.setattr("pptx_gen.pipeline.build_default_structured_llm_client", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PPTX_GEN_ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("PPTX_GEN_OPENAI_MODEL", raising=False)
    source_path = tmp_path / "source.txt"
    source_path.write_text(
        "Quarterly review. Revenue improved materially. Margin expanded after infrastructure changes. "
        "Leadership should approve the hiring plan.",
        encoding="utf-8",
    )

    result = generate_deck(
        source_path=source_path,
        output_path=tmp_path / "generated.pptx",
        audience="Leadership team",
        goal="Summarize quarterly performance",
        slide_count_target=5,
        embedder=deterministic_embedder,
    )

    assert Path(result.output_path).exists()
    assert Path(result.artifacts_dir, "brief.json").exists()
    assert Path(result.artifacts_dir, "presentation_spec.json").exists()
    assert result.brief is not None
    assert result.outline is not None
    assert result.retrieval_plan is not None
    assert result.ingestion_result is not None
    assert result.export_job.status is ExportStatus.SUCCESS
    assert result.resolved_layout.slides


def test_revise_for_design_quality_validates_structured_output(
    tmp_path: Path,
    make_presentation_spec,
    make_slide,
    make_block,
) -> None:
    spec = PresentationSpec(
        **make_presentation_spec(
            slides=[
                make_slide(
                    blocks=[
                        make_block(
                            content={"text": "Revenue improved meaningfully this quarter."},
                        )
                    ]
                )
            ]
        )
    )
    artifact_path = tmp_path / "first-pass.pptx"
    artifact_path.write_bytes(b"pptx")
    client = FakeStructuredClient({"applied": True, "rationale": ["shorten"], "schema_version": "1.0.0"})

    with pytest.raises(ValidationError):
        revise_for_design_quality(
            spec,
            qa_report_json="{}",
            render_artifact_path=artifact_path,
            llm_client=client,
            enabled=True,
        )


def test_generate_deck_with_refinement_applies_single_round(
    tmp_path: Path,
    make_presentation_spec,
    make_slide,
    make_block,
) -> None:
    original = PresentationSpec(
        **make_presentation_spec(
            slides=[
                make_slide(
                    blocks=[
                        make_block(
                            content={"text": "Revenue improved meaningfully this quarter."},
                        )
                    ]
                )
            ]
        )
    )
    revised_payload = original.model_dump()
    revised_payload["slides"][0]["blocks"][0]["content"] = {"text": "Revenue improved this quarter."}
    client = FakeStructuredClient(
        {
            "schema_version": "1.0.0",
            "applied": True,
            "rationale": ["Reduced text density"],
            "presentation_spec": revised_payload,
        }
    )

    result = generate_deck(
        presentation_spec=original,
        output_path=tmp_path / "refined-deck.pptx",
        enable_refinement=True,
        llm_client=client,
        user_brief="Summarize quarterly performance",
    )

    assert Path(result.output_path).exists()
    assert result.refinement_applied is True
    assert result.export_job.status is ExportStatus.SUCCESS
    assert result.presentation_spec.slides[0].blocks[0].content["text"] == "Revenue improved this quarter."


def test_generate_deck_skips_refinement_when_client_missing(
    tmp_path: Path,
    make_presentation_spec,
    make_slide,
    make_block,
    monkeypatch,
) -> None:
    monkeypatch.setattr("pptx_gen.pipeline.build_default_structured_llm_client", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PPTX_GEN_ANTHROPIC_MODEL", raising=False)
    spec = PresentationSpec(
        **make_presentation_spec(
            slides=[
                make_slide(
                    blocks=[
                        make_block(content={"text": "Revenue improved meaningfully this quarter."})
                    ]
                )
            ]
        )
    )

    result = generate_deck(
        presentation_spec=spec,
        output_path=tmp_path / "skip-refinement.pptx",
        enable_refinement=True,
        llm_client=None,
    )

    assert result.refinement_applied is False
    assert "no llm client configured" in result.refinement_status
    assert result.export_job.status is ExportStatus.SUCCESS


def test_design_refinement_preserves_citations(
    tmp_path: Path,
    make_presentation_spec,
    make_slide,
    make_block,
) -> None:
    spec = PresentationSpec(
        **make_presentation_spec(
            slides=[
                make_slide(
                    blocks=[
                        make_block(content={"text": "Revenue improved meaningfully this quarter."})
                    ]
                )
            ]
        )
    )
    artifact_path = tmp_path / "first-pass.pptx"
    artifact_path.write_bytes(b"pptx")
    revised_payload = spec.model_dump()
    revised_payload["slides"][0]["blocks"][0]["source_citations"][0]["locator"] = "doc-finance:page9"
    client = FakeStructuredClient(
        {
            "schema_version": "1.0.0",
            "applied": True,
            "rationale": ["Changed spacing"],
            "presentation_spec": revised_payload,
        }
    )

    with pytest.raises(ValueError, match="preserve citations"):
        revise_for_design_quality(
            spec,
            qa_report_json="{}",
            render_artifact_path=artifact_path,
            llm_client=client,
            enabled=True,
        )
