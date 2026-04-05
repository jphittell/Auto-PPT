"""PPTX rendering boundary."""

from __future__ import annotations

from pathlib import Path

from pptx_gen.pipeline import ExportJob


def export_pptx(*, output_path: str | Path, template_path: str | Path | None = None) -> ExportJob:
    # TODO: render a ResolvedDeckLayout into a standards-compliant PPTX with python-pptx.
    raise NotImplementedError("PPTX export is not implemented in Phase 1.")

