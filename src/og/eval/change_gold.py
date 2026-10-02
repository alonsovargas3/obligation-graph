"""Change-order reference set (gold) loading and validation (Task 20).

The change gold file is the trust anchor for every wave 3 eval number, so
loading is strict, like ``og.eval.gold``: identity pins (chain membership,
canonical TextDoc hashes per member), verbatim spans inside their cited
segment, enum and origin checks, and kind-specific value shapes are all
checked before any label is scored. Any failure raises ``ValueError(<code>)``
and nothing is returned.

The gold also carries the chain documents' segment tables, because scoring
matches findings by segment identity (rev 2 R9): a predicted ClauseRef is only
character offsets in the DB, and its segment is recovered from the same
TextDocs the gold was pinned against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from og.change.types import CATEGORIES, FINDING_KINDS, OLD_ORIGINS
from og.eval.gold import SCOPES, textdoc_sha256
from og.textdoc import TextDoc

FINDING_FIELDS = (
    "kind",
    "new_segment_id",
    "new_span_text",
    "old_origin",
    "old_doc",
    "old_segment_id",
    "old_span_text",
    "target_label",
    "old_value",
    "new_value",
    "delta",
    "currency",
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DECIMAL = re.compile(r"^-?\d+(?:\.\d+)?$")
_WHOLE = re.compile(r"^-?\d+$")

# Kinds that carry no values at all.
_KINDS_WITHOUT_VALUES = ("supersedes", "potential_conflict")


@dataclass(frozen=True)
class ChangeGoldFinding:
    kind: str
    new_segment_id: str
    new_span_text: str
    old_origin: str
    old_doc: str | None
    old_segment_id: str | None
    old_span_text: str | None
    target_label: str | None
    old_value: str | None
    new_value: str | None
    delta: str | None
    currency: str | None


@dataclass(frozen=True)
class ChangeGold:
    change_order_id: str
    chain: tuple[str, ...]
    textdoc_sha256: dict[str, str]
    provenance: dict[str, Any]
    scope: str
    gates: dict[str, bool]
    gate_segments: dict[str, tuple[str, ...]]
    findings: list[ChangeGoldFinding]
    # agreement id -> segment id -> (char_start, char_end); recovers a predicted
    # ClauseRef's segment without re-reading the TextDocs.
    segments: dict[str, dict[str, tuple[int, int]]]


def _require_str(raw: dict[str, Any], field: str, *, code: str) -> str:
    v = raw.get(field)
    if not isinstance(v, str) or not v:
        raise ValueError(f"{code}:{field}")
    return v


def _opt_str(raw: dict[str, Any], field: str) -> str | None:
    v = raw.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError(f"bad_type:{field}")
    return v


def _segment_table(doc: TextDoc) -> dict[str, tuple[int, int]]:
    return {s.id: (s.char_start, s.char_end) for s in doc.segments}


def _segment_text(doc: TextDoc, segments: dict[str, tuple[int, int]], segment_id: Any) -> str:
    if not isinstance(segment_id, str) or segment_id not in segments:
        raise ValueError("unknown_segment")
    start, end = segments[segment_id]
    return doc.text[start:end]


def _check_span(
    doc: TextDoc, segments: dict[str, tuple[int, int]], segment_id: Any, span: Any
) -> None:
    """The cited span must occur verbatim inside the cited segment."""
    if not isinstance(span, str) or not span:
        raise ValueError("bad_type:span")
    if span not in _segment_text(doc, segments, segment_id):
        raise ValueError("span_mismatch")


def _check_values(raw: dict[str, Any]) -> None:
    kind = raw["kind"]
    old_value = _opt_str(raw, "old_value")
    new_value = _opt_str(raw, "new_value")
    delta = _opt_str(raw, "delta")
    currency = _opt_str(raw, "currency")

    if kind in _KINDS_WITHOUT_VALUES:
        if any(v is not None for v in (old_value, new_value, delta, currency)):
            raise ValueError("values_forbidden")
        return

    if kind == "shifted_date":
        for field, v in (("old_value", old_value), ("new_value", new_value)):
            if not isinstance(v, str) or not _ISO_DATE.match(v):
                raise ValueError(f"bad_date:{field}")
        if not isinstance(delta, str) or not _WHOLE.match(delta):
            raise ValueError("bad_number:delta")
        if currency is not None:
            raise ValueError("values_forbidden:currency")
        return

    if kind == "price_change":
        if old_value is not None:
            raise ValueError("old_value_forbidden")
        if not isinstance(new_value, str) or not _DECIMAL.match(new_value):
            raise ValueError("bad_number:new_value")
        if delta is not None:
            raise ValueError("values_forbidden:delta")
        return

    raise ValueError("bad_enum:kind")


def _load_finding(raw: Any, docs: dict[str, TextDoc], chain: tuple[str, ...]) -> ChangeGoldFinding:
    if not isinstance(raw, dict):
        raise ValueError("bad_format")
    for f in FINDING_FIELDS:
        if f not in raw:
            raise ValueError(f"missing_field:{f}")

    kind = raw["kind"]
    if kind not in FINDING_KINDS:
        raise ValueError("bad_enum:kind")
    origin = raw["old_origin"]
    if origin not in OLD_ORIGINS:
        raise ValueError("bad_enum:old_origin")

    co_id = chain[-1]
    co_doc = docs[co_id]
    co_segments = _segment_table(co_doc)
    new_segment_id = _require_str(raw, "new_segment_id", code="bad_type")
    _check_span(co_doc, co_segments, new_segment_id, raw["new_span_text"])

    old_doc = old_segment_id = None
    if origin == "chain":
        old_doc = _require_str(raw, "old_doc", code="bad_type")
        if old_doc not in chain or chain.index(old_doc) >= len(chain) - 1:
            raise ValueError("old_doc_not_in_chain")
        old_doc_segments = _segment_table(docs[old_doc])
        old_segment_id = _require_str(raw, "old_segment_id", code="bad_type")
        _check_span(docs[old_doc], old_doc_segments, old_segment_id, raw["old_span_text"])
    elif origin == "self":
        if raw["old_doc"] is not None:
            raise ValueError("old_side_forbidden:old_doc")
        old_segment_id = _require_str(raw, "old_segment_id", code="bad_type")
        _check_span(co_doc, co_segments, old_segment_id, raw["old_span_text"])
    else:  # unresolved: the target document is not in the corpus
        if any(raw[f] is not None for f in ("old_doc", "old_segment_id", "old_span_text")):
            raise ValueError("old_side_forbidden")
        if kind == "supersedes" and (
            not isinstance(raw["target_label"], str) or not raw["target_label"].strip()
        ):
            # R3: the label is required only for supersedes with an unresolved
            # target; a price added has no label (rev 2.2).
            raise ValueError("target_label_required")

    _check_values(raw)

    return ChangeGoldFinding(
        kind=kind,
        new_segment_id=new_segment_id,
        new_span_text=raw["new_span_text"],
        old_origin=origin,
        old_doc=old_doc,
        old_segment_id=old_segment_id,
        old_span_text=_opt_str(raw, "old_span_text"),
        target_label=_opt_str(raw, "target_label"),
        old_value=_opt_str(raw, "old_value"),
        new_value=_opt_str(raw, "new_value"),
        delta=_opt_str(raw, "delta"),
        currency=_opt_str(raw, "currency"),
    )


def _load_gates(raw: Any, co_doc: TextDoc) -> tuple[dict[str, bool], dict[str, tuple[str, ...]]]:
    if not isinstance(raw, dict):
        raise ValueError("bad_format")
    for cat in CATEGORIES:
        if cat not in raw:
            raise ValueError(f"missing_gate:{cat}")
    unknown = set(raw) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown_gate:{sorted(unknown)[0]}")

    segment_ids = {s.id for s in co_doc.segments}
    answers: dict[str, bool] = {}
    segments: dict[str, tuple[str, ...]] = {}
    for cat, entry in raw.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("answer"), bool):
            raise ValueError(f"bad_type:gates.{cat}")
        ids = entry.get("segment_ids", [])
        if not isinstance(ids, list) or any(
            not isinstance(s, str) or s not in segment_ids for s in ids
        ):
            raise ValueError(f"unknown_segment:gates.{cat}")
        answers[cat] = entry["answer"]
        segments[cat] = tuple(ids)
    return answers, segments


def read_change_chain(path: str | Path) -> list[str]:
    """The chain list, read without full validation (for loading the TextDocs)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("chain"), list):
        raise ValueError("bad_format")
    return [str(a) for a in data["chain"]]


def load_change_gold(path: str | Path, docs: dict[str, TextDoc]) -> ChangeGold:
    """Load and fully validate a change-order reference set against its TextDocs.

    ``docs`` must contain every chain member; each member's canonical TextDoc
    hash is pinned by the file, so a re-ingested document rejects the labels.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bad_format")

    co_id = data.get("change_order_id")
    if not isinstance(co_id, str) or not co_id:
        raise ValueError("bad_type:change_order_id")

    chain_raw = data.get("chain")
    if (
        not isinstance(chain_raw, list)
        or len(chain_raw) < 2
        or any(not isinstance(a, str) for a in chain_raw)
        or len(set(chain_raw)) != len(chain_raw)
        or chain_raw[-1] != co_id
    ):
        raise ValueError("bad_format:chain")

    chain = tuple(chain_raw)
    for member in chain:
        doc = docs.get(member)
        if doc is None:
            raise ValueError(f"doc_not_provided:{member}")
        if doc.doc_id != member:
            raise ValueError(f"doc_id_mismatch:{member}")

    pins = data.get("textdoc_sha256")
    if not isinstance(pins, dict):
        raise ValueError("bad_format:textdoc_sha256")
    for member in chain:
        if pins.get(member) != textdoc_sha256(docs[member]):
            raise ValueError(f"textdoc_sha_mismatch:{member}")

    scope = data.get("scope")
    if scope not in SCOPES or scope != "full_agreement":
        raise ValueError("bad_enum:scope")

    provenance = data.get("provenance")
    if provenance is None:
        provenance = {}
    if not isinstance(provenance, dict):
        raise ValueError("bad_format:provenance")

    gates, gate_segments = _load_gates(data.get("gates"), docs[co_id])

    raw_findings = data.get("findings")
    if not isinstance(raw_findings, list):
        raise ValueError("bad_format:findings")
    findings = [_load_finding(r, docs, chain) for r in raw_findings]

    return ChangeGold(
        change_order_id=co_id,
        chain=chain,
        textdoc_sha256={m: pins[m] for m in chain},
        provenance=provenance,
        scope=scope,
        gates=gates,
        gate_segments=gate_segments,
        findings=findings,
        segments={m: _segment_table(docs[m]) for m in chain},
    )
