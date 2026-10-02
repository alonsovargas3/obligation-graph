"""Greedy, deterministic chunking of a TextDoc for extraction.

Segments in "Table of Contents" sections are never sent. Chunk 1 carries the
opening segments; every later chunk repeats a short read-only context prefix
(the leading primary segments of chunk 1) so the model keeps the preamble in
view without being allowed to cite it. The prefix lines are tagged ``[ctx]``
and never appear in any chunk's ``segment_ids``, so extraction cannot cite
them and every non-TOC segment remains primary in exactly one chunk.
"""

from __future__ import annotations

from ..textdoc import TextDoc
from .types import Chunk

CONTEXT_HEADER = "CONTEXT (do not extract)"
CONTEXT_CHARS = 1500


def _segment_line(segment_id: str, text: str) -> str:
    return f"[{segment_id}] {text}\n"


def _context_line(segment_id: str, text: str) -> str:
    return f"[ctx {segment_id}] {text}\n"


def _context_segments(segments: list, texts: dict[str, str]) -> list:
    """The leading segments, capped at CONTEXT_CHARS of segment text, at least one."""
    chosen: list = []
    total = 0
    for seg in segments:
        if chosen and total + len(texts[seg.id]) > CONTEXT_CHARS:
            break
        chosen.append(seg)
        total += len(texts[seg.id])
    return chosen


def chunk_doc(doc: TextDoc, max_chars: int = 12000) -> list[Chunk]:
    """Split `doc` into chunks of at most `max_chars` rendered characters.

    Packing is greedy and in order: a chunk closes before the next section
    would push its full text (context prefix included) past the cap; a section
    too large for an empty chunk is split at segment boundaries; a segment too
    large for an empty chunk becomes a single-segment chunk (soft cap).
    """
    toc_sections = {s.id for s in doc.sections if s.heading == "Table of Contents"}
    segments = sorted(
        (s for s in doc.segments if s.section_id not in toc_sections),
        key=lambda s: s.char_start,
    )
    if not segments:
        return []

    groups: list[list] = []
    for seg in segments:
        if groups and groups[-1][0].section_id == seg.section_id:
            groups[-1].append(seg)
        else:
            groups.append([seg])

    texts = {s.id: doc.segment_text(s.id) for s in segments}
    lens = {s.id: len(_segment_line(s.id, texts[s.id])) for s in segments}

    chunks: list[Chunk] = []
    current: list = []
    prefix = ""

    def flush() -> None:
        nonlocal current, prefix
        if not current:
            return
        body = "".join(_segment_line(s.id, texts[s.id]) for s in current)
        chunks.append(
            Chunk(
                chunk_id=f"c{len(chunks) + 1:04d}",
                doc_id=doc.doc_id,
                segment_ids=[s.id for s in current],
                text=prefix + body,
            )
        )
        current = []
        if len(chunks) == 1:
            # Rev 2.2 R2-1: later chunks prefix the leading primary segments of
            # chunk 1, capped at CONTEXT_CHARS of segment text, at least one.
            ctx = _context_segments([doc.segment(sid) for sid in chunks[0].segment_ids], texts)
            prefix = CONTEXT_HEADER + "\n" + "".join(_context_line(s.id, texts[s.id]) for s in ctx)

    for group in groups:
        group_len = sum(lens[s.id] for s in group)
        cur_len = sum(lens[s.id] for s in current)
        if current and len(prefix) + cur_len + group_len > max_chars:
            flush()
            cur_len = 0
        if current:
            current.extend(group)
            continue
        if len(prefix) + group_len <= max_chars:
            current = list(group)
            continue
        # The section alone overflows an empty chunk: split at segment boundaries.
        for seg in group:
            if current and len(prefix) + cur_len + lens[seg.id] > max_chars:
                flush()
                cur_len = 0
            current.append(seg)
            cur_len += lens[seg.id]
            if len(prefix) + lens[seg.id] > max_chars:
                # A segment too large for an empty chunk is its own chunk (soft cap).
                flush()
                cur_len = 0
    flush()
    return chunks
