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
def generate_command() -> None:
    """Generate a PPTX deck from ingested sources."""

    try:
        generate_deck()
    except NotImplementedError as exc:
        raise click.ClickException(str(exc)) from exc

