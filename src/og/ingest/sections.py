"""Section detection over the final emitted lines: flat, finest numbered level.

Three line shapes open a section: ARTICLE headings, "Section N" lines, and
numbered clauses with at least one dot. Everything else is body text that
belongs to the enclosing section. ARTICLE headings may continue onto the next
line (an all-caps title line), but never over a line that itself matches one
of the three section shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ARTICLE_RE = re.compile(r"^(?:ARTICLE|Article)\s+([IVXLC]+|\d+)\b[.:]?\s*(.*)$")
SECTION_RE = re.compile(r"^(?:Section|SECTION)\s+(\d+(?:\.\d+)*)\.?\s+(.*)$")
NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(\S.*)$")

_HEADING_CAP = 80


@dataclass(frozen=True)
class SectionMark:
    """A section-opening line: its line index plus the parsed fields."""

    line_index: int
    number: str
    heading: str
    article: str | None


def _cut_heading(raw: str) -> str:
    """Group 2 up to the first '. ' or a trailing '.', capped, stripped."""
    dot = raw.find(". ")
    if dot != -1:
        raw = raw[:dot]
    elif raw.endswith("."):
        raw = raw[:-1]
    return raw[:_HEADING_CAP].strip()


def matches_section_line(line: str) -> bool:
    return any(pattern.match(line) for pattern in (ARTICLE_RE, SECTION_RE, NUMBERED_RE))


def _continuation(line: str) -> bool:
    """An ARTICLE title on its own line: short, shouty, and not a section."""
    return (
        len(line) <= _HEADING_CAP
        and not any(ch.islower() for ch in line)
        and not matches_section_line(line)
    )


def scan(lines: list[str]) -> list[SectionMark]:
    """Return one SectionMark per section-opening line, in document order."""
    marks: list[SectionMark] = []
    last_article: str | None = None
    for i, line in enumerate(lines):
        m = ARTICLE_RE.match(line)
        if m:
            number, heading = m.group(1), m.group(2).strip()
            if not heading and i + 1 < len(lines) and _continuation(lines[i + 1]):
                heading = lines[i + 1]
            article = heading if heading else None
            last_article = article
            marks.append(SectionMark(i, number, heading, article))
            continue
        m = SECTION_RE.match(line) or NUMBERED_RE.match(line)
        if m:
            marks.append(SectionMark(i, m.group(1), _cut_heading(m.group(2)), last_article))
    return marks
