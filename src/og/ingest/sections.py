"""Section detection over the final emitted lines: flat, finest numbered level.

Four line shapes open a section: ARTICLE headings, "Section N" lines, dotted
numbered clauses, and single-level "N." clauses. The two numbered shapes
require the text after the number (and an optional table-cell " | ") to start
with a capital letter or an opening quote, so figures like "1.25 | $100.00"
stay body text. Everything else is body text that belongs to the enclosing
section. ARTICLE headings may continue onto the next line (an all-caps title
line), but never over a line that itself matches one of the section shapes.

A run of table-of-contents entries is collapsed into one "Table of Contents"
section. A candidate is a TOC entry when at least one line follows it before
the next candidate and every one of those lines is a page reference (one to
three digits, or a short roman numeral, case-insensitive). A maximal run of
at least three consecutive entries, plus an immediately preceding
"TABLE OF CONTENTS"-style heading line (a "Page" line in between does not
detach it), becomes a single section; shorter runs stay ordinary sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ARTICLE_RE = re.compile(r"^(?:ARTICLE|Article)\s+([IVXLC]+|\d+)\b[.:]?\s*(.*)$")
SECTION_RE = re.compile(r"^(?:Section|SECTION)\s+(\d+(?:\.\d+)*)\.?\s+(.*)$")
NUMBERED_RE = re.compile(r'^(\d+(?:\.\d+)+)\.?\s*(?:\|\s*)?([A-Z\u201c"].*)$')
SINGLE_RE = re.compile(r'^(\d{1,3})\.\s*(?:\|\s*)?([A-Z\u201c"].*)$')

_SECTION_PATTERNS = (ARTICLE_RE, SECTION_RE, NUMBERED_RE, SINGLE_RE)

_HEADING_CAP = 80

_PAGE_REF_RE = re.compile(r"(?:\d{1,3}|[ivxlc]{1,6})", re.IGNORECASE)
_TOC_HEADING_RE = re.compile(r"TABLE OF CONTENTS|Table of Contents|CONTENTS")
_TOC_MIN_ENTRIES = 3
_TOC_HEADING = "Table of Contents"


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
    return any(pattern.match(line) for pattern in _SECTION_PATTERNS)


def _continuation(line: str) -> bool:
    """An ARTICLE title on its own line: short, shouty, and not a section."""
    return (
        len(line) <= _HEADING_CAP
        and not any(ch.islower() for ch in line)
        and not matches_section_line(line)
    )


def _page_ref(line: str) -> bool:
    return _PAGE_REF_RE.fullmatch(line) is not None


def _toc_start(lines: list[str], first_entry: int) -> int:
    """The TOC section start: a heading line behind one optional "Page" line."""
    k = first_entry - 1
    if k >= 0 and lines[k] == "Page":
        k -= 1
    if k >= 0 and _TOC_HEADING_RE.fullmatch(lines[k]):
        return k
    return first_entry


def _merge_toc_runs(lines: list[str], marks: list[SectionMark]) -> list[SectionMark]:
    """Collapse each run of TOC entries into a single Table of Contents mark."""
    n = len(marks)
    entry = [False] * n
    for k in range(n):
        nxt = marks[k + 1].line_index if k + 1 < n else len(lines)
        gap = lines[marks[k].line_index + 1 : nxt]
        entry[k] = bool(gap) and all(_page_ref(g) for g in gap)

    out: list[SectionMark] = []
    k = 0
    while k < n:
        if entry[k]:
            j = k
            while j + 1 < n and entry[j + 1]:
                j += 1
            if j - k + 1 >= _TOC_MIN_ENTRIES:
                out.append(
                    SectionMark(_toc_start(lines, marks[k].line_index), None, _TOC_HEADING, None)
                )
                k = j + 1
                continue
        out.append(marks[k])
        k += 1
    return out


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
        m = SECTION_RE.match(line) or NUMBERED_RE.match(line) or SINGLE_RE.match(line)
        if m:
            marks.append(SectionMark(i, m.group(1), _cut_heading(m.group(2)), last_article))
    return _merge_toc_runs(lines, marks)
