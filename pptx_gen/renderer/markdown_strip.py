"""Utilities for stripping markdown syntax from short slide content fragments."""

from __future__ import annotations

import re


_MARKDOWN_HINT_PATTERN = re.compile(r"[#*_~`\\[>!]")
_LIST_PREFIX_PATTERN = re.compile(r"(?m)^[ \t]*(?:[-*+]|\d+\.)[ \t]+")


def strip_markdown(text: str) -> str:
    if not text:
        return text
    if not _MARKDOWN_HINT_PATTERN.search(text) and not _LIST_PREFIX_PATTERN.search(text):
        return text.strip()

    cleaned = text
    cleaned = re.sub(r"```(?:[^\n`]*)\n?(.*?)```", lambda match: match.group(1).strip(), cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[ \t]{0,3}>[ \t]?", "", cleaned, flags=re.MULTILINE)

    inline_patterns = (
        (r"\*\*\*([^*]+)\*\*\*", r"\1"),
        (r"___([^_]+)___", r"\1"),
        (r"\*\*([^*]+)\*\*", r"\1"),
        (r"__([^_]+)__", r"\1"),
        (r"\*([^*\n]+)\*", r"\1"),
        (r"_([^_\n]+)_", r"\1"),
        (r"~~([^~]+)~~", r"\1"),
        (r"`([^`]+)`", r"\1"),
        (r"!\[([^\]]*)\]\([^)]+\)", r"\1"),
        (r"\[([^\]]+)\]\([^)]+\)", r"\1"),
    )
    for pattern, replacement in inline_patterns:
        cleaned = re.sub(pattern, replacement, cleaned)

    cleaned = re.sub(r"^[ \t]*(?:[-*+]|\d+\.)[ \t]+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
