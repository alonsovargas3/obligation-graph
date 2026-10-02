"""The read API (wave 4; contract coordinator-authored and frozen, bodies are Task 30).

The only reader behind MCP, the UI, and the README demo. Every function:
- reads only the allowlisted views and metadata tables (READ_ALLOWLIST), taking every
  citation from a citation-bearing projection, never joining clause_ref directly;
- runs inside one read transaction, so all fields come from one snapshot;
- returns plain JSON-serializable dicts in which every contractual item carries its
  ClauseRefs, and every supporting binding (party, event, site) carries its own.
Redacted and blank obligations keep their independently verified fields (ADR-005) and
add a marker; nothing is inferred.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

import yaml

from og.change.report import load_change_report
from og.paths import sources_path

# Rev 2.1 R2-1: the only identifiers allowed after FROM/JOIN in og/query.py,
# og/change/report.py, og/eval/score.py (pred_from_db) and og/eval/change_score.py.
READ_ALLOWLIST = frozenset(
    {
        "visible_obligation",
        "visible_obligation_clause",
        "visible_obligation_timing",
        "visible_party_binding",
        "visible_event_binding",
        "visible_site_binding",
        "visible_change_finding",
        "visible_change_finding_ref",
        "visible_supersedes",
        "fresh_change_run",
        "agreement",
        "source",
        "party",
        "site",
        "change_run_chain",
        "gate_decision",
    }
)
ROLE_WORDS = ("landlord", "tenant", "guarantor", "provider", "customer", "lender")
MARKERS = {"redacted": "[REDACTED]", "blank": "[BLANK]"}
MAX_LIMIT = 500
PENDING_NOTE = (
    "Pending means the documents give no computable due date for this obligation. "
    "It does not mean overdue, and it does not mean there is no obligation. "
    "Contingent obligations are due relative to a quoted event that has not been "
    "recorded; unresolved ones have timing the system cannot compute (a reason is "
    "given); the rest state no deadline."
)
# change_order() statuses (rev 2 W4-3 / round-3 response matrix).
CHANGE_STATUSES = (
    "ok",  # a fresh ungated run exists; gated may be null when it is missing or stale
    "unknown_change_order",  # the input matches no pinned change order
    "missing_change_run",  # pinned, but no stored run (run make change)
    "stale_change_run",  # stored runs exist but none is fresh (run make change)
    "missing_textdoc",  # a chain TextDoc is absent (run make ingest)
)


class ClauseRefOut(TypedDict):
    agreement_id: str
    section: str | None
    page: int | None
    char_start: int
    char_end: int
    span_text: str


class PartyBindingOut(TypedDict):
    name: str
    role: str
    clause: ClauseRefOut


class EventBindingOut(TypedDict):
    name: str
    date: str | None
    clause: ClauseRefOut


class SiteOut(TypedDict):
    name: str
    location: str | None
    label: str  # always "agreement site"
    clause: ClauseRefOut


class AgreementOut(TypedDict):
    id: str
    title: str
    type: str
    is_form: bool
    base_agreement_id: str | None
    metadata: dict  # {filer, filing_date, form, exhibit, source_url}: source metadata, not terms
    parties: list[PartyBindingOut]
    sites: list[SiteOut]
    obligation_count: int


class TimingOut(TypedDict):
    kind: str  # scheduled | contingent | unresolved | untimed
    trigger_kind: str | None
    trigger: ClauseRefOut | None  # minimal quoted trigger, inside the obligation quote
    relation: str | None  # lt | lte | eq | gte | gt
    offset_days: int | None
    offset_unit: str | None
    anchor: EventBindingOut | None  # the cited dated event the bound is computed from
    reason: str | None  # set iff kind == "unresolved"


class DeadlineOut(TypedDict):
    relation: str  # lt | lte | eq
    date: str  # ISO bound; with relation "lt" this is a strict before-date, not a due date
    clause: ClauseRefOut  # the anchor's declaration


class ObligationOut(TypedDict):
    id: int
    agreement_id: str
    type: str
    status: str  # active | superseded | redacted | blank
    marker: str | None  # "[REDACTED]" | "[BLANK]" | None
    lifecycle: str  # superseded | pending | scheduled
    owed_by: PartyBindingOut | None
    owed_to: PartyBindingOut | None
    description: str
    amount: str | None  # plain decimal string
    currency: str | None
    due_date: str | None
    effective_due: str | None
    anchor_event: EventBindingOut | None
    offset_days: int | None
    trigger: str | None
    agreement_sites: list[SiteOut]
    clauses: list[ClauseRefOut]  # at least one
    superseded_by: list[dict]  # [{obligation_id, change_order_id, clause: ClauseRefOut}]
    timing: TimingOut  # wave 5; kind "untimed" with nulls when no timing row is visible
    deadline: DeadlineOut | None  # wave 5; set iff timing.kind == "scheduled"


class ObligationPage(TypedDict):
    obligations: list[ObligationOut]
    total: int  # matches before pagination
    returned: int
    offset: int
    truncated: bool  # offset + returned < total
    unresolved_party_count: int  # matches (same non-party filters) whose payer or payee is unbound


class DeadlinesOut(TypedDict):
    as_of: str
    days: int
    window_end: str
    scheduled: list[ObligationOut]
    pending: list[ObligationOut]  # one page
    pending_total: int
    contingent: list[ObligationOut]  # one page; a subset of pending (wave 5)
    contingent_total: int
    unresolved_total: int
    untimed_total: int
    offset: int
    truncated: bool
    unresolved_party_count: int
    note: str  # PENDING_NOTE


# ---------------------------------------------------------------- internals


@contextmanager
def _snapshot(con: sqlite3.Connection):
    """One read transaction per public call: BEGIN, then COMMIT (ROLLBACK on error)."""
    con.execute("BEGIN")
    try:
        yield
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def _check_paging(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be in 1..{MAX_LIMIT}, got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be at least 0, got {offset}")


def _clause_ref(agreement_id: str, row: tuple) -> ClauseRefOut:
    """(section, page, char_start, char_end, span_text) plus the agreement id."""
    section, page, char_start, char_end, span_text = row
    return {
        "agreement_id": agreement_id,
        "section": section,
        "page": page,
        "char_start": char_start,
        "char_end": char_end,
        "span_text": span_text,
    }


def _amount_str(amount: Any) -> str | None:
    """A plain decimal string; a REAL like 64490.0 must not read as a float."""
    if amount is None:
        return None
    value = float(amount)
    return str(int(value)) if value == int(value) else str(value)


def _where(
    *,
    party: str | None,
    site: str | None,
    type: str | None,
    status: str | None,
    lifecycle: str | None,
    agreement: str | None,
    include_superseded: bool,
) -> tuple[str, list[Any]]:
    """All filters as one SQL predicate over visible_obligation o. party means payee."""
    clauses: list[str] = []
    params: list[Any] = []
    if not include_superseded:
        clauses.append("o.lifecycle <> 'superseded'")
    if type is not None:
        clauses.append("o.type = ?")
        params.append(type)
    if status is not None:
        clauses.append("o.status = ?")
        params.append(status)
    if lifecycle is not None:
        clauses.append("o.lifecycle = ?")
        params.append(lifecycle)
    if agreement is not None:
        clauses.append("o.agreement_id = ?")
        params.append(agreement)
    if party is not None:
        needle = party.lower()
        if needle in ROLE_WORDS:
            clauses.append(
                "EXISTS (SELECT 1 FROM visible_party_binding pb"
                " WHERE pb.agreement_id = o.agreement_id AND pb.party_id = o.owed_to"
                " AND pb.role = ?)"
            )
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM visible_party_binding pb"
                " WHERE pb.agreement_id = o.agreement_id AND pb.party_id = o.owed_to"
                " AND instr(lower(pb.name), ?) > 0)"
            )
        params.append(needle)
    if site is not None:
        needle = site.lower()
        clauses.append(
            "EXISTS (SELECT 1 FROM visible_site_binding vb"
            " WHERE vb.agreement_id = o.agreement_id"
            " AND (instr(lower(vb.name), ?) > 0"
            " OR (vb.location IS NOT NULL AND instr(lower(vb.location), ?) > 0)))"
        )
        params.extend((needle, needle))
    return " AND ".join(clauses) if clauses else "1=1", params


_ORDER = " ORDER BY o.effective_due IS NULL, o.effective_due, o.agreement_id, o.id"

# id, agreement_id, type, status, lifecycle, description, amount, currency, due_date,
# effective_due, anchor_event_id, offset_days, trigger, owed_by, owed_to
_ROW_SQL = (
    "SELECT o.id, o.agreement_id, o.type, o.status, o.lifecycle, o.description, o.amount,"
    " o.currency, o.due_date, o.effective_due, o.anchor_event_id, o.offset_days,"
    ' o."trigger", o.owed_by, o.owed_to FROM visible_obligation o'
)

_UNBOUND = (
    " (o.owed_to IS NULL OR NOT EXISTS (SELECT 1 FROM visible_party_binding bp"
    " WHERE bp.agreement_id = o.agreement_id AND bp.party_id = o.owed_to)"
    " OR o.owed_by IS NULL OR NOT EXISTS (SELECT 1 FROM visible_party_binding bp"
    " WHERE bp.agreement_id = o.agreement_id AND bp.party_id = o.owed_by))"
)


def _unresolved_party_count(
    con: sqlite3.Connection, where: str, params: list[Any], join: str = ""
) -> int:
    """Matches whose payer or payee is null, unbound, or has a revoked binding."""
    sql = (
        "SELECT count(*) FROM visible_obligation o" + join + " WHERE (" + where + ") AND" + _UNBOUND
    )
    return con.execute(sql, params).fetchone()[0]


def _binding_map(
    con: sqlite3.Connection, agreements: set[str]
) -> dict[tuple[str, int], PartyBindingOut]:
    """(agreement_id, party_id) -> cited binding. A party with several roles in one
    agreement resolves to its last role in alphabetical order (none in this corpus)."""
    out: dict[tuple[str, int], PartyBindingOut] = {}
    keys = sorted(agreements)
    if not keys:
        return out
    rows = con.execute(
        "SELECT agreement_id, party_id, name, role, section, page, char_start, char_end,"
        " span_text FROM visible_party_binding WHERE agreement_id IN ("
        + ",".join("?" * len(keys))
        + ") ORDER BY agreement_id, party_id, role",
        keys,
    ).fetchall()
    for row in rows:
        agreement_id, party_id, name, role = row[:4]
        out[(agreement_id, party_id)] = {
            "name": name,
            "role": role,
            "clause": _clause_ref(agreement_id, row[4:9]),
        }
    return out


def _site_map(con: sqlite3.Connection, agreements: set[str]) -> dict[str, list[SiteOut]]:
    out: dict[str, list[SiteOut]] = {}
    keys = sorted(agreements)
    if not keys:
        return out
    rows = con.execute(
        "SELECT agreement_id, name, location, section, page, char_start, char_end, span_text"
        " FROM visible_site_binding WHERE agreement_id IN ("
        + ",".join("?" * len(keys))
        + ") ORDER BY agreement_id, clause_ref_id",
        keys,
    ).fetchall()
    for row in rows:
        agreement_id, name, location = row[:3]
        out.setdefault(agreement_id, []).append(
            {
                "name": name,
                "location": location,
                "label": "agreement site",
                "clause": _clause_ref(agreement_id, row[3:8]),
            }
        )
    return out


def _event_map(
    con: sqlite3.Connection, event_ids: set[int]
) -> dict[int, tuple[str, EventBindingOut]]:
    """event_id -> (event agreement id, cited binding); same-agreement anchors only."""
    out: dict[int, tuple[str, EventBindingOut]] = {}
    keys = sorted(event_ids)
    if not keys:
        return out
    rows = con.execute(
        "SELECT event_id, agreement_id, name, date, section, page, char_start, char_end,"
        " span_text FROM visible_event_binding WHERE event_id IN ("
        + ",".join("?" * len(keys))
        + ") ORDER BY event_id",
        keys,
    ).fetchall()
    for row in rows:
        event_id, agreement_id, name, event_date = row[:4]
        out[event_id] = (
            agreement_id,
            {
                "name": name,
                "date": event_date,
                "clause": _clause_ref(agreement_id, row[4:9]),
            },
        )
    return out


def _clause_map(
    con: sqlite3.Connection, obligation_ids: list[int]
) -> dict[int, list[ClauseRefOut]]:
    out: dict[int, list[ClauseRefOut]] = {}
    if not obligation_ids:
        return out
    rows = con.execute(
        "SELECT obligation_id, agreement_id, section, page, char_start, char_end, span_text"
        " FROM visible_obligation_clause WHERE obligation_id IN ("
        + ",".join("?" * len(obligation_ids))
        + ") ORDER BY obligation_id, char_start, clause_ref_id",
        obligation_ids,
    ).fetchall()
    for row in rows:
        obligation_id, agreement_id = row[:2]
        out.setdefault(obligation_id, []).append(_clause_ref(agreement_id, row[2:7]))
    return out


# Wave 5: timing hydration comes only through the visible_obligation_timing projection.
# A row with no visible timing is untimed: kind "untimed" with null fields (rev 2.2).
_TIMING_SQL = (
    "SELECT obligation_id, agreement_id, kind, trigger_kind, relation, offset_days,"
    " offset_unit, reason, trigger_clause_ref_id, trigger_section, trigger_page,"
    " trigger_char_start, trigger_char_end, trigger_span_text, anchor_event_id,"
    " anchor_agreement_id, anchor_name, anchor_date, anchor_section, anchor_page,"
    " anchor_char_start, anchor_char_end, anchor_span_text, bound_date"
    " FROM visible_obligation_timing"
)
# The stated deadline of a scheduled row: the timing bound when the timing is visible,
# otherwise the legacy effective_due. Strict lt bounds are exposed with their relation
# and are never shown as due-on dates (rev 2 W5-1).
_TIMING_JOIN = " LEFT JOIN visible_obligation_timing vt ON vt.obligation_id = o.id"
_DEADLINE = "COALESCE(vt.bound_date, o.effective_due)"


def _untimed() -> TimingOut:
    return {
        "kind": "untimed",
        "trigger_kind": None,
        "trigger": None,
        "relation": None,
        "offset_days": None,
        "offset_unit": None,
        "anchor": None,
        "reason": None,
    }


def _timing_map(
    con: sqlite3.Connection, obligation_ids: list[int]
) -> dict[int, tuple[TimingOut, DeadlineOut | None]]:
    """obligation_id -> (timing, deadline) from the projection; revoking either citation
    (trigger, anchor declaration) removes the row here and so everywhere at once."""
    out: dict[int, tuple[TimingOut, DeadlineOut | None]] = {}
    if not obligation_ids:
        return out
    rows = con.execute(
        _TIMING_SQL + " WHERE obligation_id IN (" + ",".join("?" * len(obligation_ids)) + ")",
        obligation_ids,
    ).fetchall()
    for row in rows:
        kind, relation = row[2], row[4]
        trigger = _clause_ref(row[1], row[9:14]) if row[8] is not None else None
        anchor = None
        if row[14] is not None:
            anchor = {
                "name": row[16],
                "date": row[17],
                "clause": _clause_ref(row[15], row[18:23]),
            }
        timing: TimingOut = {
            "kind": kind,
            "trigger_kind": row[3],
            "trigger": trigger,
            "relation": relation,
            "offset_days": row[5],
            "offset_unit": row[6],
            "anchor": anchor,
            "reason": row[7],
        }
        deadline: DeadlineOut | None = None
        if kind == "scheduled" and anchor is not None and row[23] is not None:
            deadline = {"relation": relation, "date": row[23], "clause": anchor["clause"]}
        out[row[0]] = (timing, deadline)
    return out


def _superseded_by_map(con: sqlite3.Connection, ids: list[int]) -> dict[int, list[dict]]:
    """Per obligation: visible supersession edges against it, each with the superseding
    obligation's own first clause (rev 2.2)."""
    out: dict[int, list[dict]] = {}
    if not ids:
        return out
    edges = con.execute(
        "SELECT obligation_id, superseded_obligation_id, change_order_id"
        " FROM visible_supersedes WHERE superseded_obligation_id IN ("
        + ",".join("?" * len(ids))
        + ") ORDER BY superseded_obligation_id, obligation_id",
        ids,
    ).fetchall()
    if not edges:
        return out
    superseding_ids = [row[0] for row in edges]
    first_clause: dict[int, ClauseRefOut] = {}
    rows = con.execute(
        "SELECT obligation_id, agreement_id, section, page, char_start, char_end, span_text"
        " FROM visible_obligation_clause WHERE obligation_id IN ("
        + ",".join("?" * len(superseding_ids))
        + ") ORDER BY obligation_id, char_start, clause_ref_id",
        superseding_ids,
    ).fetchall()
    for row in rows:
        obligation_id, agreement_id = row[:2]
        first_clause.setdefault(obligation_id, _clause_ref(agreement_id, row[2:7]))
    for obligation_id, superseded_obligation_id, change_order_id in edges:
        out.setdefault(superseded_obligation_id, []).append(
            {
                "obligation_id": obligation_id,
                "change_order_id": change_order_id,
                "clause": first_clause.get(obligation_id),
            }
        )
    return out


def _hydrate(con: sqlite3.Connection, rows: list[tuple]) -> list[ObligationOut]:
    """visible_obligation rows as ObligationOut dicts with their cited bindings."""
    if not rows:
        return []
    agreements = {row[1] for row in rows}
    parties = _binding_map(con, agreements)
    sites = _site_map(con, agreements)
    events = _event_map(con, {row[10] for row in rows if row[10] is not None})
    ids = [row[0] for row in rows]
    clauses = _clause_map(con, ids)
    superseded_by = _superseded_by_map(con, ids)
    timings = _timing_map(con, ids)
    out: list[ObligationOut] = []
    for row in rows:
        obligation_id, agreement_id, status = row[0], row[1], row[3]
        anchor_event = None
        if row[10] is not None and row[10] in events:
            event_agreement, binding = events[row[10]]
            if event_agreement == agreement_id:
                anchor_event = binding
        owed_by = row[13]
        owed_to = row[14]
        timing, deadline = timings.get(obligation_id, (_untimed(), None))
        out.append(
            {
                "id": obligation_id,
                "agreement_id": agreement_id,
                "type": row[2],
                "status": status,
                "marker": MARKERS.get(status),
                "lifecycle": row[4],
                "owed_by": parties.get((agreement_id, owed_by)) if owed_by is not None else None,
                "owed_to": parties.get((agreement_id, owed_to)) if owed_to is not None else None,
                "description": row[5],
                "amount": _amount_str(row[6]),
                "currency": row[7],
                "due_date": row[8],
                "effective_due": row[9],
                "anchor_event": anchor_event,
                "offset_days": row[11],
                "trigger": row[12],
                "agreement_sites": sites.get(agreement_id, []),
                "clauses": clauses.get(obligation_id, []),
                "superseded_by": superseded_by.get(obligation_id, []),
                "timing": timing,
                "deadline": deadline,
            }
        )
    return out


# ---------------------------------------------------------------- public API


def list_agreements(con: sqlite3.Connection) -> list[AgreementOut]:
    with _snapshot(con):
        rows = con.execute(
            "SELECT a.id, a.title, a.type, a.is_form, a.base_agreement_id, s.filer,"
            " s.filing_date, s.form, s.exhibit, s.url"
            " FROM agreement a JOIN source s ON s.id = a.source_id ORDER BY a.id"
        ).fetchall()
        counts = dict(
            con.execute(
                "SELECT agreement_id, count(*) FROM visible_obligation GROUP BY agreement_id"
            ).fetchall()
        )
        parties: dict[str, list[PartyBindingOut]] = {}
        for row in con.execute(
            "SELECT agreement_id, party_id, name, role, section, page, char_start,"
            " char_end, span_text FROM visible_party_binding"
            " ORDER BY agreement_id, clause_ref_id"
        ).fetchall():
            agreement_id = row[0]
            parties.setdefault(agreement_id, []).append(
                {
                    "name": row[2],
                    "role": row[3],
                    "clause": _clause_ref(agreement_id, row[4:9]),
                }
            )
        sites: dict[str, list[SiteOut]] = {}
        for row in con.execute(
            "SELECT agreement_id, name, location, section, page, char_start, char_end,"
            " span_text FROM visible_site_binding ORDER BY agreement_id, clause_ref_id"
        ).fetchall():
            agreement_id = row[0]
            sites.setdefault(agreement_id, []).append(
                {
                    "name": row[1],
                    "location": row[2],
                    "label": "agreement site",
                    "clause": _clause_ref(agreement_id, row[3:8]),
                }
            )
    return [
        {
            "id": row[0],
            "title": row[1],
            "type": row[2],
            "is_form": bool(row[3]),
            "base_agreement_id": row[4],
            "metadata": {
                "filer": row[5],
                "filing_date": row[6],
                "form": row[7],
                "exhibit": row[8],
                "source_url": row[9],
            },
            "parties": parties.get(row[0], []),
            "sites": sites.get(row[0], []),
            "obligation_count": counts.get(row[0], 0),
        }
        for row in rows
    ]


def get_obligations(
    con: sqlite3.Connection,
    *,
    party: str | None = None,
    site: str | None = None,
    type: str | None = None,
    status: str | None = None,
    lifecycle: str | None = None,
    agreement: str | None = None,
    include_superseded: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> ObligationPage:
    _check_paging(limit, offset)
    with _snapshot(con):
        where, params = _where(
            party=party,
            site=site,
            type=type,
            status=status,
            lifecycle=lifecycle,
            agreement=agreement,
            include_superseded=include_superseded,
        )
        total = con.execute(
            "SELECT count(*) FROM visible_obligation o WHERE " + where, params
        ).fetchone()[0]
        rows = con.execute(
            _ROW_SQL + " WHERE " + where + _ORDER + " LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        non_party_where, non_party_params = _where(
            party=None,
            site=site,
            type=type,
            status=status,
            lifecycle=lifecycle,
            agreement=agreement,
            include_superseded=include_superseded,
        )
        unresolved = _unresolved_party_count(con, non_party_where, non_party_params)
        obligations = _hydrate(con, rows)
    return {
        "obligations": obligations,
        "total": total,
        "returned": len(obligations),
        "offset": offset,
        "truncated": offset + len(obligations) < total,
        "unresolved_party_count": unresolved,
    }


def upcoming_deadlines(
    con: sqlite3.Connection,
    *,
    days: int = 90,
    party: str | None = None,
    as_of: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> DeadlinesOut:
    _check_paging(limit, offset)
    if days < 0:
        raise ValueError(f"days must be at least 0, got {days}")
    start = as_of if as_of is not None else datetime.now(UTC).date().isoformat()
    start_date = date.fromisoformat(start)
    window_end = (start_date + timedelta(days=days)).isoformat()
    where, params = _where(
        party=party,
        site=None,
        type=None,
        status=None,
        lifecycle=None,
        agreement=None,
        include_superseded=False,
    )
    with _snapshot(con):
        # Rev 2.1: scheduled rows are selected by their stated deadline date in the
        # window, whatever the relation (strict lt bounds included, shown with their
        # relation), and ordered by deadline date, then agreement, then id (rev 2.2).
        scheduled_rows = con.execute(
            _ROW_SQL
            + _TIMING_JOIN
            + " WHERE ("
            + where
            + ") AND o.lifecycle = 'scheduled'"
            + " AND "
            + _DEADLINE
            + " >= ? AND "
            + _DEADLINE
            + " <= ?"
            + " ORDER BY "
            + _DEADLINE
            + ", o.agreement_id, o.id",
            (*params, start, window_end),
        ).fetchall()
        # Pending subdivides into contingent, unresolved, and untimed (no visible
        # timing row reads as untimed); the three totals partition pending exactly.
        kind_counts = dict(
            con.execute(
                "SELECT COALESCE(vt.kind, 'untimed'), count(*) FROM visible_obligation o"
                + _TIMING_JOIN
                + " WHERE ("
                + where
                + ") AND o.lifecycle = 'pending' GROUP BY 1",
                params,
            ).fetchall()
        )
        pending_rows = con.execute(
            _ROW_SQL
            + " WHERE ("
            + where
            + ") AND o.lifecycle = 'pending'"
            + _ORDER
            + " LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        # Contingent is a paged subset of pending under the same filters and ordering.
        contingent_rows = con.execute(
            _ROW_SQL
            + _TIMING_JOIN
            + " WHERE ("
            + where
            + ") AND o.lifecycle = 'pending' AND vt.kind = 'contingent'"
            + _ORDER
            + " LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        unresolved = _unresolved_party_count(
            con,
            "(o.lifecycle = 'pending'"
            " OR (o.lifecycle = 'scheduled' AND "
            + _DEADLINE
            + " >= ? AND "
            + _DEADLINE
            + " <= ?))",
            [start, window_end],
            _TIMING_JOIN,
        )
        scheduled = _hydrate(con, scheduled_rows)
        pending = _hydrate(con, pending_rows)
        contingent = _hydrate(con, contingent_rows)
    pending_total = sum(kind_counts.values())
    return {
        "as_of": start,
        "days": days,
        "window_end": window_end,
        "scheduled": scheduled,
        "pending": pending,
        "pending_total": pending_total,
        "contingent": contingent,
        "contingent_total": kind_counts.get("contingent", 0),
        "unresolved_total": kind_counts.get("unresolved", 0),
        "untimed_total": kind_counts.get("untimed", 0),
        "offset": offset,
        "truncated": offset + len(pending) < pending_total,
        "unresolved_party_count": unresolved,
        "note": PENDING_NOTE,
    }


def _pinned_change_orders() -> list[dict]:
    """The change-order entries of data/sources.yaml (amends set), resolved from og.paths."""
    try:
        raw = yaml.safe_load(sources_path().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    return [dict(d) for d in raw.get("documents", []) if d.get("amends")]


def _resolve_change_order(value: str) -> dict | None:
    """A pinned change order for an accepted input (rev 2 W4-11), or None.

    Accepted: a change-order id; a pinned local_path; a bare filename equal to a
    pinned local_path basename; an existing file whose sha256 equals a pinned
    change order's source sha256. Ambiguous inputs resolve to None.
    """
    docs = _pinned_change_orders()
    for key in ("id", "local_path"):
        hits = [d for d in docs if str(d.get(key) or "") == value]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None
    hits = [d for d in docs if str(d.get("local_path") or "").rsplit("/", 1)[-1] == value]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1 or not Path(value).is_file():
        return None
    digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
    hits = [d for d in docs if str(d.get("sha256") or "") == digest]
    return hits[0] if len(hits) == 1 else None


def _gate_summary(gates: list[dict]) -> dict:
    tiers: Counter = Counter()
    backends: Counter = Counter()
    for gate in gates:
        tiers[str(gate.get("tier"))] += 1
        backends[str(gate.get("backend"))] += 1
    return {
        "questions": len(gates),
        "run_check": sum(1 for gate in gates if gate.get("run_check")),
        "skipped": sum(1 for gate in gates if not gate.get("run_check")),
        "tiers": dict(tiers),
        "backends": dict(backends),
    }


def _change_error(status: str, change_order_id: str | None, message: str) -> dict:
    return {
        "status": status,
        "stored_report": False,
        "analysis_performed": False,
        "change_order_id": change_order_id,
        "source_sha256": None,
        "chain": None,
        "pair_id": None,
        "ungated": None,
        "gated": None,
        "gate_summary": None,
        "message": message,
    }


def change_order(con: sqlite3.Connection, change_order: str) -> dict:
    """The stored, verified ChangeReport for a pinned change order (no analysis).

    `change_order` is a change-order id, a sources.yaml local_path, a bare filename equal
    to a pinned local_path basename, or an existing file whose sha256 equals a pinned
    change order's source sha256 (rev 2 W4-11). Returns
    {"status": one of CHANGE_STATUSES, "stored_report": True, "analysis_performed": False,
     "change_order_id", "source_sha256", "chain", "pair_id", "ungated", "gated",
     "gate_summary", "message"}; on a non-ok status the report fields are null and
    "message" gives the pipeline step to run.
    """
    doc = _resolve_change_order(change_order)
    if doc is None:
        return _change_error(
            "unknown_change_order",
            None,
            f"Unknown change order {change_order!r}: add it to data/sources.yaml, then"
            " run make fetch ingest extract change.",
        )
    co_id = str(doc["id"])
    with _snapshot(con):
        try:
            ungated = load_change_report(con, co_id, "ungated")
        except ValueError:
            return _change_error(
                "missing_change_run",
                co_id,
                f"No stored change run for {co_id!r}: run make change to check it.",
            )
        if "error" in ungated:
            return _change_error(ungated["error"], co_id, ungated["message"])
        try:
            gated = load_change_report(con, co_id, "gated")
        except ValueError:
            gated = None
        if gated is not None and "error" in gated:
            gated = None
        source_sha = con.execute(
            "SELECT s.sha256 FROM agreement a JOIN source s ON s.id = a.source_id WHERE a.id = ?",
            (co_id,),
        ).fetchone()
        gates = (gated or ungated)["gates"]
        return {
            "status": "ok",
            "stored_report": True,
            "analysis_performed": False,
            "change_order_id": co_id,
            "source_sha256": source_sha[0] if source_sha else str(doc.get("sha256")),
            "chain": ungated["chain"],
            "pair_id": ungated["pair_id"],
            "ungated": ungated,
            "gated": gated,
            "gate_summary": _gate_summary(gates),
            "message": f"Stored, verified report for {co_id} (no analysis performed).",
        }
