"""Deterministic chart-to-PNG rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


def render_chart_to_png(chart_spec: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    chart_type = str(chart_spec.get("chart_type", "bar")).lower()
    data = chart_spec.get("data", [])
    if not isinstance(data, list) or not data:
        raise ValueError("chart_spec.data must be a non-empty list")

    labels = [str(item.get("label", "")) for item in data]
    values = [float(item.get("value", 0.0)) for item in data]

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    accent = chart_spec.get("accent_color", "#0A84FF")

    if chart_type == "bar":
        ax.bar(labels, values, color=accent)
    elif chart_type == "line":
        ax.plot(labels, values, color=accent, marker="o", linewidth=2)
    elif chart_type == "pie":
        ax.pie(values, labels=labels, autopct="%1.0f%%")
    elif chart_type == "scatter":
        x_values = list(range(len(values)))
        ax.scatter(x_values, values, color=accent)
        ax.set_xticks(x_values)
        ax.set_xticklabels(labels)
    else:
        plt.close(fig)
        raise ValueError(f"unsupported chart_type: {chart_type}")

    title = chart_spec.get("title")
    if title:
        ax.set_title(str(title))
    if chart_type != "pie":
        if chart_spec.get("x_label"):
            ax.set_xlabel(str(chart_spec["x_label"]))
        if chart_spec.get("y_label"):
            ax.set_ylabel(str(chart_spec["y_label"]))
        ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_path, format="png", bbox_inches="tight")
    plt.close(fig)
    return output_path
