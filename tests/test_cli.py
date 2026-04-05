from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import pptx_gen.pipeline as pipeline_module
from pptx_gen.cli import cli


def test_cli_generate_happy_path(monkeypatch, tmp_path: Path, deterministic_embedder) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text(
        "Quarterly review. Revenue improved materially. Margin expanded after infrastructure changes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline_module, "SentenceTransformerEmbedder", lambda: deterministic_embedder)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "generate",
            str(source_path),
            "--output",
            str(tmp_path / "deck.pptx"),
            "--audience",
            "Leadership",
            "--goal",
            "Summarize the quarter",
            "--slide-count",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "deck.pptx").exists()
    assert '"output_path"' in result.output


def test_cli_generate_requires_audience(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Short content.", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(source_path), "--output", str(tmp_path / "deck.pptx")])

    assert result.exit_code != 0
    assert "--audience" in result.output


def test_cli_generate_requires_goal(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Short content.", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "generate",
            str(source_path),
            "--output",
            str(tmp_path / "deck.pptx"),
            "--audience",
            "Leadership",
        ],
    )

    assert result.exit_code != 0
    assert "--goal" in result.output
