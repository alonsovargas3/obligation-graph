"""The HTML emitter: one DOM walk, final positions emitted as lines are flushed.

The emitter never re-searches the final text for an offset. Each line's start
offset is known at the moment the line is appended, so page markers can be
recorded against positions that are already final (plan, Task 3 step 2).

Whitespace handling: runs of [ \\t\\r\\n\\f\\v] collapse to one space inside a
line; U+00A0 and every other character pass through untouched. Line boundaries
strip every str.isspace() character (NBSP included) from both ends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from bs4.element import (
    CData,
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    ProcessingInstruction,
    Script,
    Stylesheet,
    Tag,
    TemplateString,
)

SKIP_TAGS = frozenset({"head", "script", "style", "title", "noscript"})
BLOCK_TAGS = frozenset(
    {"p", "div", "li", "tr", "table", "blockquote", "center", "h1", "h2", "h3", "h4", "h5", "h6"}
)
CELL_TAGS = frozenset({"td", "th"})

_WS_RUN = re.compile(r"[ \t\r\n\f\v]+")
_STYLE_WS = re.compile(r"\s+")
_BEFORE_STYLES = ("page-break-before:always", "break-before:page")
_AFTER_STYLES = ("page-break-after:always", "break-after:page")

_NON_TEXT = (
    Comment,
    CData,
    ProcessingInstruction,
    Declaration,
    Doctype,
    Script,
    Stylesheet,
    TemplateString,
)


@dataclass
class _RowState:
    """Separator state for the cells of one table row."""

    prev_cell_text: bool = False


@dataclass
class _CellState:
    """One td/th cell: does it contain text, and was its separator placed."""

    row: _RowState | None
    had_text: bool = False
    opened: bool = False


@dataclass
class Emitter:
    """Accumulates lines and page starts. Offsets are final when a line lands."""

    lines: list[str] = field(default_factory=list)
    current: str = ""
    offset: int = 0
    page_starts: list[int] = field(default_factory=list)
    page_pending: bool = False

    def text(self, chunk: str, cell: _CellState | None) -> None:
        chunk = _WS_RUN.sub(" ", chunk)
        if not chunk:
            return
        if cell is not None and any(not ch.isspace() for ch in chunk):
            if not cell.opened:
                cell.opened = True
                if cell.row is not None and cell.row.prev_cell_text:
                    self.current += " | "
            cell.had_text = True
        self.current += chunk

    def boundary(self) -> None:
        line = self.current.strip()
        self.current = ""
        if not line:
            return
        start = self.offset
        self.lines.append(line)
        self.offset += len(line) + 1
        if self.page_pending:
            self.page_pending = False
            if start > 0:
                self.page_starts.append(start)


def _style_norm(style: str) -> str:
    return _STYLE_WS.sub("", style.lower())


def _walk(node: object, em: Emitter, row: _RowState | None, cell: _CellState | None) -> None:
    if isinstance(node, Tag):
        name = node.name
        if name in SKIP_TAGS:
            return
        if name == "hr":
            em.boundary()
            em.page_pending = True
            return
        if name == "br":
            em.boundary()
            return
        style = node.get("style") or ""
        norm = _style_norm(style) if style else ""
        before = any(s in norm for s in _BEFORE_STYLES)
        after = any(s in norm for s in _AFTER_STYLES)
        if before:
            em.boundary()
            em.page_pending = True
        if name in BLOCK_TAGS:
            em.boundary()
        child_row, child_cell = row, cell
        cell_state: _CellState | None = None
        if name == "tr":
            child_row, child_cell = _RowState(), None
        elif name in CELL_TAGS:
            cell_state = _CellState(row)
            child_row, child_cell = row, cell_state
        for child in node.children:
            _walk(child, em, child_row, child_cell)
        if cell_state is not None and cell_state.row is not None:
            cell_state.row.prev_cell_text = cell_state.had_text
        if name in BLOCK_TAGS:
            em.boundary()
        if after:
            em.boundary()
            em.page_pending = True
    elif isinstance(node, NavigableString) and not isinstance(node, _NON_TEXT):
        em.text(str(node), cell)


def emit(soup: BeautifulSoup) -> tuple[list[str], list[int]]:
    """Walk the parsed document once. Returns (lines, page_starts).

    page_starts holds the start offsets of pages 2..n; page 1 always starts
    at 0. A pending break with no following text is dropped here, and text
    never crosses a page marker because setting a marker always follows a
    boundary that flushed what came before it.
    """
    em = Emitter()
    for child in soup.children:
        _walk(child, em, None, None)
    em.boundary()
    return em.lines, em.page_starts
