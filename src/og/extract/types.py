"""Shared extraction contract (coordinator-authored, frozen).

The model proposes RawItems. verify() turns them into Verified* values whose
every stored field is either the copied source slice or proven present in it.
Raw output is diagnostics only and never supplies a stored field.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

KINDS = ("obligation", "event", "party")
OBL_TYPES = (
    "payment",
    "delivery",
    "sla",
    "penalty",
    "termination_right",
    "guarantee",
    "notice",
    "insurance",
    "other",
)
ROLES = ("landlord", "tenant", "guarantor", "provider", "customer", "lender", "other")
STATUSES = ("active", "redacted", "blank")
CHUNK_STATUSES = ("ok", "refused", "truncated", "invalid", "error")

# Every field of one item in prompts/extract_v1.schema.json, in schema order.
RAW_FIELDS = (
    "span_text",
    "segment_id",
    "kind",
    "type",
    "owed_by",
    "owed_to",
    "description",
    "amount",
    "currency",
    "due_date",
    "anchor_event",
    "offset_days",
    "trigger",
    "status",
    "name",
    "date",
    "role",
)


@dataclass(frozen=True)
class RawItem:
    span_text: str
    segment_id: str
    kind: str
    type: str | None
    owed_by: str | None
    owed_to: str | None
    description: str | None
    amount: float | None
    currency: str | None
    due_date: str | None
    anchor_event: str | None
    offset_days: int | None
    trigger: str | None
    status: str | None
    name: str | None
    date: str | None
    role: str | None


@dataclass(frozen=True)
class Evidence:
    segment_id: str
    section_id: str | None
    section_number: str | None
    page: int
    char_start: int
    char_end: int
    span_text: str


@dataclass(frozen=True)
class VerifiedObligation:
    evidence: Evidence
    type: str
    status: str
    owed_by: str | None
    owed_to: str | None
    description: str
    amount: Decimal | None
    currency: str | None
    due_date: str | None
    anchor_event: str | None
    offset_days: int | None
    trigger: str | None


@dataclass(frozen=True)
class VerifiedEvent:
    evidence: Evidence
    name: str
    date: str | None
    status: str


@dataclass(frozen=True)
class VerifiedParty:
    evidence: Evidence
    name: str
    role: str


@dataclass(frozen=True)
class Drop:
    raw: RawItem
    reason: str


@dataclass(frozen=True)
class FieldCorrection:
    raw: RawItem
    field: str
    reason: str


@dataclass(frozen=True)
class VerifyResult:
    obligations: list[VerifiedObligation]
    events: list[VerifiedEvent]
    parties: list[VerifiedParty]
    drops: list[Drop]
    corrections: list[FieldCorrection]


@dataclass(frozen=True)
class Attempt:
    """One model attempt inside one API call; server-side fallback produces several."""

    model: str
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    refused: bool


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    segment_ids: list[str]
    text: str


@dataclass(frozen=True)
class ChunkOutcome:
    chunk_id: str
    status: str
    items: list[RawItem]
    attempts: list[Attempt]
    latency_ms: int | None
    cache_hit: bool
    request_fingerprint: str
    error: str | None  # a short code (e.g. an exception class name), never a repr


@dataclass(frozen=True)
class ExtractResult:
    doc_id: str
    prompt_version: str
    outcomes: list[ChunkOutcome]

    @property
    def complete(self) -> bool:
        return bool(self.outcomes) and all(o.status == "ok" for o in self.outcomes)

    @property
    def items(self) -> list[RawItem]:
        return [item for o in self.outcomes for item in o.items]


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    prompt_version: str
    model: str
    textdoc_sha256: str
    attempts: list[Attempt]


@dataclass(frozen=True)
class WriteStats:
    obligations: int
    events: int
    parties: int
    defined_terms: int
    unresolved_parties: int
    unresolved_anchors: int


class Refused(Exception):
    """The final attempt of a call ended with stop_reason == "refusal"."""


class TruncatedResponse(Exception):
    """stop_reason == "max_tokens": the structured output may be incomplete."""


class BadResponse(Exception):
    """The response failed local validation; args[0] is a short code."""


class WriteRefused(Exception):
    """A writer precondition failed; args[0] is a short code."""
