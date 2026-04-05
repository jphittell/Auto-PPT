"""Chart rendering boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_chart_to_png(chart_spec: dict[str, Any], output_path: str | Path) -> Path:
    # TODO: render chart blocks to PNG via matplotlib or plotly.
    raise NotImplementedError("Chart rendering is not implemented in Phase 1.")

