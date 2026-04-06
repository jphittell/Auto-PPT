from __future__ import annotations

import json
import os
import subprocess
import sys
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
    monkeypatch.setattr(pipeline_module, "build_default_structured_llm_client", lambda: None)

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


def test_cli_generate_uses_ascii_safe_json_output(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Short content.", encoding="utf-8")

    class FakeResult:
        def model_dump_json(self, **kwargs) -> str:
            assert kwargs["ensure_ascii"] is True
            assert kwargs["indent"] == 2
            return '{"note":"Revenue \\u2192 margin"}'

    monkeypatch.setattr("pptx_gen.cli.generate_deck", lambda **_: FakeResult())

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
        ],
    )

    assert result.exit_code == 0, result.output
    assert "\\u2192" in result.output


def test_python_module_generate_invokes_cli(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    output_path = tmp_path / "deck.pptx"
    source_path.write_text("Quarterly review. Revenue improved materially.", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "PPTX_GEN_ANTHROPIC_MODEL": "",
            "PPTX_GEN_OPENAI_MODEL": "",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pptx_gen.cli",
            "generate",
            str(source_path),
            "--output",
            str(output_path),
            "--audience",
            "Leadership",
            "--goal",
            "Summarize the quarter",
            "--slide-count",
            "5",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert output_path.exists()
    payload = json.loads(completed.stdout)
    assert payload["output_path"] == str(output_path)
