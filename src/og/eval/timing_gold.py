"""Timing reference-label loading and validation (wave 5 Task 43, plan rev 2 W5-9).

The timing gold file (``eval/gold/timing/<name>.yaml``) pins every agreement
it uses by the canonical TextDoc sha256, and every label by a verbatim quote
inside one cited segment. Loading is strict, as ``og.eval.gold``: span
containment (the quote inside its segment, the trigger inside the quote, the
anchor declaration inside its own segment), document hashes, enums, and the
iff rules (``bound_date`` iff ``scheduled``, ``reason`` iff ``unresolved``)
are all checked before anything is scored. Any failure raises
``ValueError(<code>)`` and nothing is returned.

Items carry no obligation id and no type: the scorer matches them to visible
obligations of the same agreement by span overlap alone (IoU >= 0.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from og.eval.gold import SCOPES, textdoc_sha256
from og.textdoc import TextDoc
from og.timing import OFFSET_UNITS, RELATIONS, TIMING_KINDS, UNRESOLVED_REASONS

VERSION = "timing_gold_v1"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class AnchorLabel:
    """A labeled anchor: the cited declaration of the anchor's date."""

    name: str
    agreement_id: str
    segment_id: str
    span_text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class TimingLabel:
    """One labeled obligation, resolved to absolute quote offsets."""

    agreement_id: str
    segment_id: str
    char_start: int
    char_end: int
    span_text: str
    timing_kind: str
    relation: str | None
    bound_date: str | None
    anchor: AnchorLabel | None
    offset_days: int | None
    offset_unit: str | None
    trigger_span_text: str | None
    reason: str | None


@dataclass(frozen=True)
class TimingGold:
    name: str
    documents: dict[str, str]
    provenance: dict[str, Any]
    scope: str
    items: list[TimingLabel]


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_date(v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not _ISO_DATE.match(v):
        raise ValueError("bad_date:bound_date")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError("bad_date:bound_date") from None
    return v


def _check_offset_days(v: Any) -> int | None:
    if v is None:
        return None
    if not _is_int(v):
        raise ValueError("bad_number:offset_days")
    return v


def _span_offsets(doc: TextDoc, segment: Any, span_text: str, what: str) -> tuple[int, int]:
    """Absolute offsets of the first occurrence of `span_text` inside `segment`."""
    segment_text = doc.text[segment.char_start : segment.char_end]
    i = segment_text.find(span_text)
    if i < 0:
        raise ValueError(f"{what}_not_in_segment")
    start = segment.char_start + i
    return start, start + len(span_text)


def _load_anchor(
    raw: Any,
    docs: dict[str, TextDoc],
    segments: dict[str, dict[str, Any]],
    document_ids: frozenset[str],
) -> AnchorLabel | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("bad_type:anchor")
    for f in ("name", "agreement_id", "segment_id", "span_text"):
        v = raw.get(f)
        if not isinstance(v, str) or not v:
            raise ValueError(f"bad_type:anchor.{f}")
    agreement_id = raw["agreement_id"]
    doc = docs.get(agreement_id)
    if doc is None or agreement_id not in document_ids:
        raise ValueError(f"unknown_agreement:{agreement_id}")
    segment = segments[agreement_id].get(raw["segment_id"])
    if segment is None:
        raise ValueError(f"unknown_segment:{raw['segment_id']}")
    char_start, char_end = _span_offsets(doc, segment, raw["span_text"], "anchor_span")
    return AnchorLabel(
        name=raw["name"],
        agreement_id=agreement_id,
        segment_id=raw["segment_id"],
        span_text=raw["span_text"],
        char_start=char_start,
        char_end=char_end,
    )


def _load_item(
    raw: Any,
    docs: dict[str, TextDoc],
    segments: dict[str, dict[str, Any]],
    document_ids: frozenset[str],
) -> TimingLabel:
    if not isinstance(raw, dict):
        raise ValueError("bad_format")
    for f in ("agreement_id", "segment_id", "span_text", "timing_kind"):
        if f not in raw:
            raise ValueError(f"missing_field:{f}")

    agreement_id = raw["agreement_id"]
    doc = docs.get(agreement_id)
    if not isinstance(agreement_id, str) or doc is None or agreement_id not in document_ids:
        raise ValueError(f"unknown_agreement:{agreement_id}")

    segment = segments[agreement_id].get(raw["segment_id"])
    if segment is None:
        raise ValueError(f"unknown_segment:{raw['segment_id']}")

    span_text = raw["span_text"]
    if not isinstance(span_text, str) or not span_text:
        raise ValueError("bad_type:span_text")
    char_start, char_end = _span_offsets(doc, segment, span_text, "span")

    kind = raw["timing_kind"]
    if kind not in TIMING_KINDS:
        raise ValueError("bad_enum:timing_kind")

    relation = raw.get("relation")
    if relation is not None and relation not in RELATIONS:
        raise ValueError("bad_enum:relation")

    bound_date = _check_date(raw.get("bound_date"))
    if kind == "scheduled" and bound_date is None:
        raise ValueError("scheduled_without_bound")
    if kind != "scheduled" and bound_date is not None:
        raise ValueError("bound_on_non_scheduled")

    reason = raw.get("reason")
    if reason is not None and reason not in UNRESOLVED_REASONS:
        raise ValueError("bad_enum:reason")
    if kind == "unresolved" and reason is None:
        raise ValueError("unresolved_without_reason")
    if kind != "unresolved" and reason is not None:
        raise ValueError("reason_on_non_unresolved")

    trigger_span_text = raw.get("trigger_span_text")
    if trigger_span_text is not None:
        if not isinstance(trigger_span_text, str) or not trigger_span_text:
            raise ValueError("bad_type:trigger_span_text")
        if trigger_span_text not in span_text:
            raise ValueError("trigger_not_in_span")

    offset_unit = raw.get("offset_unit")
    if offset_unit is not None and offset_unit not in OFFSET_UNITS:
        raise ValueError("bad_enum:offset_unit")

    anchor = _load_anchor(raw.get("anchor"), docs, segments, document_ids)

    return TimingLabel(
        agreement_id=agreement_id,
        segment_id=raw["segment_id"],
        char_start=char_start,
        char_end=char_end,
        span_text=span_text,
        timing_kind=kind,
        relation=relation,
        bound_date=bound_date,
        anchor=anchor,
        offset_days=_check_offset_days(raw.get("offset_days")),
        offset_unit=offset_unit,
        trigger_span_text=trigger_span_text,
        reason=reason,
    )


def load_timing_gold(path: str | Path, docs: dict[str, TextDoc]) -> TimingGold:
    """Load and fully validate a timing reference set against its TextDocs.

    `docs` maps agreement id to TextDoc and must contain every agreement the
    file pins in `documents`, each with the pinned canonical sha256.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bad_format")
    if data.get("version") != VERSION:
        raise ValueError("bad_version")

    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("bad_type:name")

    raw_documents = data.get("documents")
    if not isinstance(raw_documents, dict) or not raw_documents:
        raise ValueError("bad_format")
    for agreement_id, sha in raw_documents.items():
        doc = docs.get(agreement_id)
        if doc is None:
            raise ValueError(f"missing_textdoc:{agreement_id}")
        if not isinstance(sha, str) or sha != textdoc_sha256(doc):
            raise ValueError(f"textdoc_sha_mismatch:{agreement_id}")
    document_ids = frozenset(raw_documents)

    scope = data.get("scope")
    if scope not in SCOPES:
        raise ValueError("bad_enum:scope")

    provenance = data.get("provenance")
    if provenance is None:
        provenance = {}
    if not isinstance(provenance, dict):
        raise ValueError("bad_format")

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("bad_format")

    segments = {a: {s.id: s for s in d.segments} for a, d in docs.items()}
    items = [_load_item(r, docs, segments, document_ids) for r in raw_items]

    return TimingGold(
        name=name,
        documents=raw_documents,
        provenance=provenance,
        scope=scope,
        items=items,
    )
