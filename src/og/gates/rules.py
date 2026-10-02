"""RulesGate: the deterministic decision-gate tier (wave 3 Task 14; ADR-003).

The cheapest tier of the cascade. It scans the change order's segments for
two kinds of auditable hits and never calls a model:

- Lexicon hits: whole-word, case-insensitive matches of the question's
  lexicon terms (``prompts/gate_questions_v1.yaml``). A trailing ``*`` in a
  term is a prefix wildcard that matches from a word start to that word's
  end; multiword terms match with any whitespace between the words.
- Section references: phrases of the form ``Section(s) <num>( and <num>)* of
  the (Original )?Lease`` (or ``Article <num> of the (Original )?Lease``).
  Each referenced number is looked up in ``GateContext.base_section_types``
  and is a hit when that section's obligation types intersect the question's
  ``section_types``. A reference to another document (``Section 2.C of 2A``)
  is not a base reference and never matches.

The signature block is excluded: from the segment that starts with
``IN WITNESS WHEREOF`` up to, but not including, the next segment that starts
with ``EXHIBIT``, or to the end of the document. Exhibits that follow the
signatures are still read.

Any hit gives ``answer=True`` with every hit as exact-slice ``GateEvidence``.
No hit gives ``answer=False``; either way ``run_check`` is True, because the
rules tier may skip work only through a later unanimous classifier decision
and never suppresses a finding itself (fail open, ADR-003).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable

from og.gates.types import GateContext, GateDecision, GateEvidence, Question
from og.textdoc import Segment, TextDoc

_SIGNATURE_START = "IN WITNESS WHEREOF"
_EXHIBIT_RESUMES = "EXHIBIT"

# Section numbers as they appear in cross-references: 4, 17.19, 8.3.1, 2.C.
_NUMBER = r"\d+(?:\.[0-9A-Za-z]+)*"

# Base-lease references only. "of 2A", "of the Second Amendment", etc. do not
# match, so a reference to a document outside the corpus is never a hit.
_SECTION_REF = re.compile(
    r"(?<!\w)Sections?\s+" + _NUMBER + r"(?:\s+and\s+" + _NUMBER + r")*"
    r"\s+of\s+the\s+(?:Original\s+)?Lease(?!\w)",
    re.IGNORECASE,
)
_ARTICLE_REF = re.compile(
    r"(?<!\w)Article\s+" + _NUMBER + r"\s+of\s+the\s+(?:Original\s+)?Lease(?!\w)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(_NUMBER)


def _term_pattern(term: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive pattern for one lexicon term.

    A trailing ``*`` is a prefix wildcard from a word start to that word's
    end; words of a multiword term are joined with any whitespace.
    """

    def word(part: str) -> str:
        if part.endswith("*"):
            return re.escape(part[:-1]) + r"\w*"
        return re.escape(part)

    return re.compile(
        r"(?<!\w)" + r"\s+".join(word(w) for w in term.split()) + r"(?!\w)", re.IGNORECASE
    )


def _signature_block(segments: list[Segment], doc: TextDoc) -> set[str]:
    """Segment ids from ``IN WITNESS WHEREOF`` up to the next ``EXHIBIT`` segment."""

    start: int | None = None
    for i, seg in enumerate(segments):
        if doc.segment_text(seg.id).startswith(_SIGNATURE_START):
            start = i
            break
    if start is None:
        return set()
    excluded = set()
    for seg in segments[start:]:
        excluded.add(seg.id)
        if doc.segment_text(seg.id).startswith(_EXHIBIT_RESUMES):
            break
    return excluded


class RulesGate:
    """Deterministic gate tier over lexicon terms and base section references."""

    name = "rules"

    def __init__(self, questions: Iterable[Question] = ()):
        self.questions = tuple(questions)

    def decide(
        self, question: Question, change_order: TextDoc, context: GateContext
    ) -> GateDecision:
        started = time.perf_counter()
        segments = sorted(change_order.segments, key=lambda s: s.char_start)
        excluded = _signature_block(segments, change_order)
        hits: list[GateEvidence] = []
        seen: set[tuple[str, int]] = set()

        def add(rule: str, segment: Segment, start: int, end: int) -> None:
            key = (rule, segment.char_start + start)
            if key in seen:
                return
            seen.add(key)
            hits.append(
                GateEvidence(
                    rule=rule,
                    segment_id=segment.id,
                    char_start=segment.char_start + start,
                    char_end=segment.char_start + end,
                    text=change_order.text[segment.char_start + start : segment.char_start + end],
                )
            )

        for segment in segments:
            if segment.id in excluded:
                continue
            text = change_order.text[segment.char_start : segment.char_end]
            for term in question.lexicon:
                for m in _term_pattern(term).finditer(text):
                    add(f"lexicon:{term}", segment, m.start(), m.end())
            for ref in (m for rx in (_SECTION_REF, _ARTICLE_REF) for m in rx.finditer(text)):
                for number in _NUMBER_RE.finditer(ref.group()):
                    types = context.base_section_types.get(number.group())
                    if not types:
                        continue
                    for obligation_type in sorted(frozenset(types) & question.section_types):
                        add(
                            f"section_ref:{number.group()}->{obligation_type}",
                            segment,
                            ref.start(),
                            ref.end(),
                        )

        return GateDecision(
            question=question.id,
            backend=self.name,
            tier="rules",
            answer=bool(hits),
            confidence=1.0 if hits else None,
            samples=(),
            evidence=tuple(hits),
            latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            error=None,
            run_check=True,
        )
