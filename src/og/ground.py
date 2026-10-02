"""Deterministic grounding (ADR-002). Whitespace-normalized exact match only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from og.textdoc import TextDoc


@dataclass(frozen=True)
class Span:
    span_text: str
    char_start: int
    char_end: int
    section_id: str | None = None


@dataclass(frozen=True)
class GroundResult:
    grounded: bool
    char_start: int | None
    char_end: int | None
    method: Literal["range", "section", "none"]
    reason: str | None
    section_id: str | None = None
    page: int | None = None


def _norm_map(s: str) -> tuple[str, list[int]]:
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(s)
    while i < n:
        if s[i].isspace():
            j = i
            while j < n and s[j].isspace():
                j += 1
            out.append(" ")
            idx.append(i)
            i = j
        else:
            out.append(s[i])
            idx.append(i)
            i += 1
    return "".join(out), idx


def normalize_ws(s: str) -> str:
    return _norm_map(s)[0].strip()


def _find_all(text: str, base: int, needle: str) -> list[tuple[int, int]]:
    hay, idx = _norm_map(text)
    hits, pos = [], hay.find(needle)
    while pos != -1:
        hits.append((base + idx[pos], base + idx[pos + len(needle) - 1] + 1))
        pos = hay.find(needle, pos + 1)
    return hits


def _fail(reason: str) -> GroundResult:
    return GroundResult(False, None, None, "none", reason)


def _ok(doc: TextDoc, start: int, end: int, method: str) -> GroundResult:
    sec = doc.section_for(start)
    return GroundResult(
        True, start, end, method, None, sec.id if sec else None, doc.page_for(start)
    )


def ground(doc: TextDoc, span: Span) -> GroundResult:
    needle = normalize_ws(span.span_text)
    if not needle:
        return _fail("empty_span")
    explicit = doc.section_by_id(span.section_id) if span.section_id else None
    if 0 <= span.char_start < span.char_end <= len(doc.text):
        window = doc.text[span.char_start : span.char_end]
        for start, end in _find_all(window, span.char_start, needle):
            sec = doc.section_for(start)
            if sec is None or end > sec.char_end:
                continue  # crosses a section boundary
            if explicit is not None and sec.id != explicit.id:
                continue  # an explicit known section constrains the range pass
            return _ok(doc, start, end, "range")
    section = explicit or doc.section_for(span.char_start)  # unknown id: offset's section
    if section is None:
        return _fail("no_section")
    window = doc.text[section.char_start : section.char_end]
    hits = _find_all(window, section.char_start, needle)
    if not hits:
        return _fail("not_found_in_section")
    start, end = min(hits, key=lambda h: (abs(h[0] - span.char_start), h[0]))
    return _ok(doc, start, end, "section")


def log_drop(record: dict, path: str | Path = "logs/dropped.jsonl") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
