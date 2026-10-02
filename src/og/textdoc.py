"""The shared document type: normalized text with offset-exact structure.

Ingest produces one TextDoc per document; grounding and extraction consume it
through segment ids. Every offset is a half-open [char_start, char_end)
interval into `text`, so a citation can always be checked against the bytes it
claims to come from.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Section:
    id: str
    number: str | None
    heading: str
    char_start: int
    char_end: int
    article: str | None = None


@dataclass(frozen=True)
class Page:
    page: int
    char_start: int
    char_end: int


@dataclass(frozen=True)
class Segment:
    id: str
    section_id: str | None
    page: int
    char_start: int
    char_end: int


@dataclass
class TextDoc:
    doc_id: str
    source_sha256: str
    text: str
    sections: list[Section] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)

    def section_for(self, offset: int) -> Section | None:
        for s in self.sections:
            if s.char_start <= offset < s.char_end:
                return s
        return None

    def section_by_id(self, id: str) -> Section | None:
        for s in self.sections:
            if s.id == id:
                return s
        return None

    def _page_containing(self, offset: int) -> Page | None:
        for p in self.pages:
            if p.char_start <= offset < p.char_end:
                return p
        return None

    def page_for(self, offset: int) -> int | None:
        page = self._page_containing(offset)
        return page.page if page is not None else None

    def segment(self, id: str) -> Segment:
        for seg in self.segments:
            if seg.id == id:
                return seg
        raise KeyError(id)

    def segment_text(self, id: str) -> str:
        seg = self.segment(id)
        return self.text[seg.char_start : seg.char_end]

    def validate(self) -> None:
        """Check the structural invariants. Raises ValueError on any violation."""
        if self.text == "":
            if self.sections or self.pages or self.segments:
                raise ValueError("empty text must have no sections, pages, or segments")
            return
        length = len(self.text)
        self._validate_pages(length)
        self._validate_sections(length)
        self._validate_segments(length)

    def _validate_pages(self, length: int) -> None:
        if not self.pages:
            raise ValueError("non-empty text requires at least one page")
        numbers: set[int] = set()
        end = 0
        for p in self.pages:
            if p.page in numbers:
                raise ValueError(f"duplicate page number: {p.page}")
            numbers.add(p.page)
            if not p.char_start < p.char_end:
                raise ValueError(f"page {p.page} is empty")
            if p.char_start != end:
                raise ValueError(f"page {p.page} does not start where the previous ended")
            end = p.char_end
        if end != length:
            raise ValueError("pages do not cover the text")

    def _validate_sections(self, length: int) -> None:
        if not self.sections:
            return
        ids: set[str] = set()
        end = 0
        for s in self.sections:
            if s.id in ids:
                raise ValueError(f"duplicate section id: {s.id}")
            ids.add(s.id)
            if not s.char_start < s.char_end:
                raise ValueError(f"section {s.id} is empty")
            if s.char_start != end:
                raise ValueError(f"section {s.id} does not start where the previous ended")
            end = s.char_end
        if end != length:
            raise ValueError("sections do not cover the text")

    def _validate_segments(self, length: int) -> None:
        ids: set[str] = set()
        prev_end: int | None = None
        for seg in sorted(self.segments, key=lambda s: s.char_start):
            if seg.id in ids:
                raise ValueError(f"duplicate segment id: {seg.id}")
            ids.add(seg.id)
            if not 0 <= seg.char_start < seg.char_end <= length:
                raise ValueError(f"segment {seg.id} is empty or out of bounds")
            if prev_end is not None and seg.char_start < prev_end:
                raise ValueError(f"segment {seg.id} overlaps the previous segment")
            prev_end = seg.char_end
            section = self.section_for(seg.char_start)
            if self.sections:
                if section is None:
                    raise ValueError(f"segment {seg.id} starts outside any section")
                if seg.section_id != section.id:
                    raise ValueError(
                        f"segment {seg.id} cites section {seg.section_id!r}, "
                        f"its offsets are in {section.id!r}"
                    )
                if seg.char_end > section.char_end:
                    raise ValueError(f"segment {seg.id} crosses out of section {section.id}")
            elif seg.section_id is not None:
                raise ValueError(f"segment {seg.id} cites a section but the doc has none")
            page = self._page_containing(seg.char_start)
            if page is None:
                raise ValueError(f"segment {seg.id} starts outside any page")
            if seg.page != page.page:
                raise ValueError(
                    f"segment {seg.id} cites page {seg.page}, its offsets are on page {page.page}"
                )
            if seg.char_end > page.char_end:
                raise ValueError(f"segment {seg.id} crosses out of page {page.page}")

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> TextDoc:
        data = json.loads(s)
        doc = cls(
            doc_id=data["doc_id"],
            source_sha256=data["source_sha256"],
            text=data["text"],
            sections=[Section(**x) for x in data["sections"]],
            pages=[Page(**x) for x in data["pages"]],
            segments=[Segment(**x) for x in data["segments"]],
        )
        doc.validate()
        return doc

    @classmethod
    def load(cls, path: str | Path) -> TextDoc:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: str | Path) -> None:
        self.validate()
        Path(path).write_text(self.to_json(), encoding="utf-8")
