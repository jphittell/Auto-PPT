"""Click CLI entrypoints."""

from __future__ import annotations

from pathlib import Path

import click

from pptx_gen.pipeline import generate_deck, ingest_and_index


@click.group()
def cli() -> None:
    """AI PPTX Generator CLI."""


@cli.command("ingest")
@click.argument("source_path", type=click.Path(exists=True, path_type=Path))
def ingest_command(source_path: Path) -> None:
    """Parse, chunk, and index a local file."""

    result = ingest_and_index(source_path)
    click.echo(result.model_dump_json(indent=2))


@cli.command("generate")
@click.argument("source_path", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True, help="Target PPTX output path.")
@click.option("--audience", required=True, help="Audience for the deck.")
@click.option("--goal", required=True, help="Goal or outcome for the deck.")
@click.option("--tone", default="executive", show_default=True, help="Planning tone.")
@click.option("--slide-count", "slide_count_target", default=6, show_default=True, type=int, help="Target slide count.")
@click.option("--title", default=None, help="Optional deck title override.")
@click.option("--theme-name", default="Auto PPT", show_default=True, help="Theme name to embed in PresentationSpec.")
@click.option("--refine/--no-refine", default=False, help="Enable one design-only refinement round.")
def generate_command(
    source_path: Path,
    output_path: Path,
    audience: str,
    goal: str,
    tone: str,
    slide_count_target: int,
    title: str | None,
    theme_name: str,
    refine: bool,
) -> None:
    """Generate a PPTX deck from a local source document."""

    try:
        result = generate_deck(
            source_path=source_path,
            output_path=output_path,
            audience=audience,
            goal=goal,
            tone=tone,
            slide_count_target=slide_count_target,
            title=title,
            theme_name=theme_name,
            enable_refinement=refine,
            user_brief=goal,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(result.model_dump_json(indent=2))
