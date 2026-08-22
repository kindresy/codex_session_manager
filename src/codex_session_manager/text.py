"""Display-cell-aware text helpers for terminal rendering."""

from __future__ import annotations

import unicodedata


def _cell_width(character: str) -> int:
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1


def display_width(text: str) -> int:
    return sum(_cell_width(character) for character in text)


def clip_display(text: str, width: int, ellipsis: str = "…") -> str:
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    ellipsis_width = display_width(ellipsis)
    if width < ellipsis_width:
        return ""
    limit = width - ellipsis_width
    result: list[str] = []
    used = 0
    for character in text:
        character_width = _cell_width(character)
        if used + character_width > limit:
            break
        result.append(character)
        used += character_width
    return "".join(result) + ellipsis


def wrap_display(text: str, width: int) -> list[str]:
    if width <= 0:
        return [""]
    if not text:
        return [""]

    lines: list[str] = []
    for source_line in text.splitlines() or [""]:
        current: list[str] = []
        used = 0
        for character in source_line:
            character_width = _cell_width(character)
            if current and used + character_width > width:
                lines.append("".join(current))
                current = []
                used = 0
            current.append(character)
            used += character_width
        lines.append("".join(current))
    return lines or [""]
