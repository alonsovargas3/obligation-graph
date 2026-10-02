"""Deterministic timing classification (wave 5; contract coordinator-authored and frozen).

Two stages (plan rev 2 W5-7):
  parse(doc, evidence)  -> ParsedTiming   pure: reads only the obligation's own quote
  resolve(parsed, anchors, legacy_due) -> Timing   owns the final kind, relation, bound
defined_dates(doc) finds cited calendar dates for defined terms (BLI rows and the closed
declaration forms in prompts/timing_grammar_v1.yaml). No model is involved. A trigger
span is always an exact slice inside the obligation quote; an anchor date always comes
from a cited declaration in the obligation's agreement or its recorded base. Bodies are
Task 40; the signatures, types and constants below are frozen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from og.extract.types import Evidence
from og.textdoc import TextDoc

GRAMMAR_PATH = Path(__file__).resolve().parents[2] / "prompts" / "timing_grammar_v1.yaml"

TIMING_KINDS = ("scheduled", "contingent", "unresolved", "untimed")
TRIGGER_KINDS = (
    "invoice",
    "notice",
    "demand",
    "default",
    "completion",
    "term_end",
    "defined_event",
    "other_event",
)
RELATIONS = ("lt", "lte", "eq", "gte", "gt")
OFFSET_UNITS = ("calendar", "business", "hours", "months")
UNRESOLVED_REASONS = (
    "business_days",
    "anchor_without_date",
    "anchor_not_found",
    "relative_to_other_obligation",
    "conditional_or_compound",
    "unsupported_unit",
    "cross_reference",
    "redacted_offset",
    "recurring_schedule",
    "month_granularity",
    "conflicting_dates",
)


@dataclass(frozen=True)
class TimingSpan:
    char_start: int
    char_end: int
    span_text: str  # == doc.text[char_start:char_end], inside the obligation quote


@dataclass(frozen=True)
class ParsedTiming:
    """What the obligation's own quote says, before any anchor is resolved."""

    construction: str | None  # a construction id from the grammar, or None
    relation: str | None  # one of RELATIONS
    offset_days: int | None  # signed: "N days prior to X" is -N
    offset_unit: str | None  # one of OFFSET_UNITS
    trigger: TimingSpan | None  # minimal construction + event phrase
    trigger_kind: str | None  # one of TRIGGER_KINDS
    anchor_name: str | None  # defined term immediately after the construction, if any
    reason: str | None  # an UNRESOLVED_REASONS value decided from the quote alone


@dataclass(frozen=True)
class DefinedDate:
    agreement_id: str
    name: str  # the defined term, as written (e.g. "Commencement Date")
    date: str  # ISO
    evidence: TimingSpan  # the full accepted declaration (label + value, or parenthetical)
    form: str  # "bli_row" | "declaration"


@dataclass(frozen=True)
class CitedAnchor:
    event_id: int
    agreement_id: str
    name: str
    date: str | None  # ISO, from the event's own cited declaration
    clause_ref_id: int


@dataclass(frozen=True)
class Timing:
    kind: str  # one of TIMING_KINDS
    trigger_kind: str | None
    trigger: TimingSpan | None
    relation: str | None
    offset_days: int | None
    offset_unit: str | None
    anchor_event_id: int | None
    bound_date: str | None  # ISO; set only when kind == "scheduled"
    reason: str | None  # set iff kind == "unresolved"


def parse(doc: TextDoc, evidence: Evidence) -> ParsedTiming:
    raise NotImplementedError


def resolve(
    parsed: ParsedTiming, anchors: list[CitedAnchor], legacy_due: str | None = None
) -> Timing:
    """Final kind and bound. `anchors` are the cited events of the obligation's own
    agreement and its recorded base only. A legacy explicit due date that disagrees with
    the derived bound yields unresolved/conflicting_dates; an ambiguous anchor name
    (several dated candidates with different dates) yields unresolved/conflicting_dates."""
    raise NotImplementedError


def defined_dates(doc: TextDoc) -> list[DefinedDate]:
    raise NotImplementedError
