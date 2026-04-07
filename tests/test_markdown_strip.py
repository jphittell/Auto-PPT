from __future__ import annotations

from pptx_gen.api import _stringify_block_content
from pptx_gen.planning.schemas import PresentationBlockKind
from pptx_gen.renderer.markdown_strip import strip_markdown
from pptx_gen.renderer.slide_ops import extract_table_content, extract_text_lines


def test_strip_markdown_removes_headings_and_nested_emphasis() -> None:
    assert strip_markdown("## **Overview**") == "Overview"


def test_strip_markdown_removes_inline_emphasis_and_code() -> None:
    assert strip_markdown("***Bold*** and **strong** and *emphasis* and `code`") == "Bold and strong and emphasis and code"


def test_strip_markdown_removes_underscore_styles_and_strikethrough() -> None:
    assert strip_markdown("__Bold__ _italic_ ~~old~~") == "Bold italic old"


def test_strip_markdown_removes_links_and_images() -> None:
    assert strip_markdown("See [docs](https://example.com) and ![diagram](chart.png)") == "See docs and diagram"


def test_strip_markdown_removes_list_prefixes() -> None:
    assert strip_markdown("- First\n* Second\n+ Third\n1. Fourth") == "First\nSecond\nThird\nFourth"


def test_strip_markdown_removes_fenced_code_blocks_and_rules() -> None:
    markdown = "```python\nprint('hi')\n```\n\n---"
    assert strip_markdown(markdown) == "print('hi')"


def test_strip_markdown_removes_blockquotes() -> None:
    assert strip_markdown("> Quoted insight") == "Quoted insight"


def test_strip_markdown_passthrough_for_plain_text() -> None:
    assert strip_markdown("Plain text only") == "Plain text only"


def test_strip_markdown_handles_mixed_markdown() -> None:
    markdown = "# Title\n\n- **Fast** rollout with [evidence](https://example.com)\n> Keep ~~legacy~~ context"
    assert strip_markdown(markdown) == "Title\n\nFast rollout with evidence\nKeep legacy context"


def test_strip_markdown_handles_empty_string() -> None:
    assert strip_markdown("") == ""


def test_extract_text_lines_strips_markdown() -> None:
    content = {"items": ["# Overview", "**Fast** rollout", "[Docs](https://example.com)"]}
    assert extract_text_lines(content) == ["Overview", "Fast rollout", "Docs"]


def test_extract_table_content_strips_markdown() -> None:
    table = {
        "columns": ["**Area**", "`Status`"],
        "rows": [["# Ingest", "[Ready](https://example.com)"], ["- Export", "~~Blocked~~"]],
    }
    assert extract_table_content(table) == (
        ["Area", "Status"],
        [["Ingest", "Ready"], ["Export", "Blocked"]],
    )


def test_stringify_block_content_strips_markdown() -> None:
    content = {"text": "## **Overview** with [link](https://example.com)"}
    assert _stringify_block_content(PresentationBlockKind.TEXT, content) == "Overview with link"
