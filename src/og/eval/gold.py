"""Reference-set (gold) loading and validation.

The gold file is the trust anchor for every eval number, so loading is strict:
identity pins (doc, raw source, TextDoc), offset bounds, verbatim spans inside
their cited segment, enums, and value types are all checked before any label is
scored. Any failure raises ``ValueError(<code>)`` and nothing is returned.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from og.extract.types import OBL_TYPES
from og.textdoc import TextDoc

SCOPES = ("full_agreement", "sampled")
STATUSES = ("active", "superseded", "redacted", "blank")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def textdoc_sha256(doc: TextDoc) -> str:
    """The document identity used by the writer, gold pins, and request fingerprints."""
    return hashlib.sha256(doc.to_json().encode()).hexdigest()


@dataclass(frozen=True)
class GoldItem:
    segment_id: str
    char_start: int
    char_end: int
    span_text: str
    type: str
    owed_by: str | None
    owed_to: str | None
    description: str
    amount: int | float | None
    currency: str | None
    due_date: str | None
    anchor_event: str | None
    offset_days: int | None
    trigger: str | None
    status: str


@dataclass(frozen=True)
class Gold:
    doc_id: str
    source_sha256: str
    textdoc_sha256: str
    provenance: dict[str, Any]
    scope: str
    obligations: list[GoldItem]


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _opt_str(raw: dict[str, Any], field: str) -> str | None:
    v = raw.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError(f"bad_type:{field}")
    return v


def _check_date(raw: dict[str, Any], field: str) -> str | None:
    v = raw.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or not _ISO_DATE.match(v):
        raise ValueError(f"bad_date:{field}")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"bad_date:{field}") from None
    return v


def _check_number(raw: dict[str, Any], field: str) -> int | float | None:
    v = raw.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"bad_number:{field}")
    if isinstance(v, float) and not math.isfinite(v):
        raise ValueError(f"bad_number:{field}")
    return v


def _check_int(raw: dict[str, Any], field: str) -> int | None:
    v = raw.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise ValueError(f"bad_number:{field}")
    return v


def _load_item(raw: Any, doc: TextDoc, segments: dict[str, Any]) -> GoldItem:
    if not isinstance(raw, dict):
        raise ValueError("bad_format")
    for f in (
        "segment_id",
        "char_start",
        "char_end",
        "span_text",
        "type",
        "description",
        "status",
    ):
        if f not in raw:
            raise ValueError(f"missing_field:{f}")

    char_start = _check_int(raw, "char_start")
    char_end = _check_int(raw, "char_end")
    if not 0 <= char_start < char_end <= len(doc.text):
        raise ValueError("out_of_bounds")
    if raw["span_text"] != doc.text[char_start:char_end]:
        raise ValueError("span_mismatch")

    segment = segments.get(raw["segment_id"])
    if segment is None or not (segment.char_start <= char_start and char_end <= segment.char_end):
        raise ValueError("span_outside_segment")

    if raw["type"] not in OBL_TYPES:
        raise ValueError("bad_enum:type")
    if raw["status"] not in STATUSES:
        raise ValueError("bad_enum:status")

    description = raw["description"]
    if not isinstance(description, str):
        raise ValueError("bad_type:description")

    return GoldItem(
        segment_id=raw["segment_id"],
        char_start=char_start,
        char_end=char_end,
        span_text=raw["span_text"],
        type=raw["type"],
        owed_by=_opt_str(raw, "owed_by"),
        owed_to=_opt_str(raw, "owed_to"),
        description=description,
        amount=_check_number(raw, "amount"),
        currency=_opt_str(raw, "currency"),
        due_date=_check_date(raw, "due_date"),
        anchor_event=_opt_str(raw, "anchor_event"),
        offset_days=_check_int(raw, "offset_days"),
        trigger=_opt_str(raw, "trigger"),
        status=raw["status"],
    )


def load_gold(path: str | Path, doc: TextDoc) -> Gold:
    """Load and fully validate a reference set against its TextDoc."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bad_format")

    if data.get("doc_id") != doc.doc_id:
        raise ValueError("doc_id_mismatch")
    if data.get("source_sha256") != doc.source_sha256:
        raise ValueError("source_sha_mismatch")
    if data.get("textdoc_sha256") != textdoc_sha256(doc):
        raise ValueError("textdoc_sha_mismatch")

    scope = data.get("scope")
    if scope not in SCOPES:
        raise ValueError("bad_enum:scope")

    raw_obligations = data.get("obligations")
    if not isinstance(raw_obligations, list):
        raise ValueError("bad_format")

    provenance = data.get("provenance")
    if provenance is None:
        provenance = {}
    if not isinstance(provenance, dict):
        raise ValueError("bad_format")

    segments = {s.id: s for s in doc.segments}
    obligations = [_load_item(r, doc, segments) for r in raw_obligations]

    return Gold(
        doc_id=data["doc_id"],
        source_sha256=data["source_sha256"],
        textdoc_sha256=data["textdoc_sha256"],
        provenance=provenance,
        scope=scope,
        obligations=obligations,
    )
