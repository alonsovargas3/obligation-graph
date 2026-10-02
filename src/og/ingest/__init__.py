"""HTML exhibit to TextDoc: emit lines, then derive sections, pages, segments.

parse_html works from a string, ingest_file from bytes on disk (verifying the
sha256 pin first). Both share one code path, so a TextDoc is identical whether
it came from a fixture string or the fetched bytes it cites.
"""

from __future__ import annotations

import bisect
import hashlib
from pathlib import Path

from bs4 import BeautifulSoup

from og.ingest import html as _html
from og.ingest import sections as _sections
from og.textdoc import Page, Section, Segment, TextDoc


def _doc_from_soup(soup: BeautifulSoup, doc_id: str, sha256: str) -> TextDoc:
    lines, page_starts = _html.emit(soup)
    text = "\n".join(lines)
    length = len(text)

    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    pages: list[Page] = []
    starts: list[int] = []
    if length:
        starts = [0, *page_starts]
        for i, s in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else length
            pages.append(Page(i + 1, s, end))

    marks = _sections.scan(lines)
    secs: list[Section] = []
    if not marks:
        if length:
            secs = [Section("s0000", None, "Preamble", 0, length, None)]
    else:
        first_start = offsets[marks[0].line_index]
        next_id = 1
        if first_start > 0:
            secs.append(Section("s0000", None, "Preamble", 0, first_start, None))
        for k, mark in enumerate(marks):
            start = offsets[mark.line_index]
            end = offsets[marks[k + 1].line_index] if k + 1 < len(marks) else length
            secs.append(
                Section(f"s{next_id:04d}", mark.number, mark.heading, start, end, mark.article)
            )
            next_id += 1

    sec_starts = [s.char_start for s in secs]
    segments = [
        Segment(
            f"p{i + 1:04d}",
            secs[bisect.bisect_right(sec_starts, start) - 1].id if sec_starts else None,
            bisect.bisect_right(starts, start),
            start,
            start + len(line),
        )
        for i, (line, start) in enumerate(zip(lines, offsets, strict=True))
    ]

    doc = TextDoc(doc_id, sha256, text, secs, pages, segments)
    doc.validate()
    return doc


def parse_html(html: str, doc_id: str, sha256: str) -> TextDoc:
    """Parse an HTML exhibit string into a validated TextDoc. Pure."""
    return _doc_from_soup(BeautifulSoup(html, "lxml"), doc_id, sha256)


def ingest_file(path: str | Path, doc_id: str, expected_sha256: str | None) -> TextDoc:
    """Read a fetched document, verify its sha256 pin, and ingest it."""
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not expected_sha256 or digest != expected_sha256:
        raise ValueError(f"{doc_id}: sha256 mismatch (pin {expected_sha256!r}, file {digest})")
    if Path(path).suffix == ".pdf":
        raise NotImplementedError("pdf ingest: wave 2")
    return _doc_from_soup(BeautifulSoup(raw, "lxml"), doc_id, digest)
