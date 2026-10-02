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

import sqlite3
from typing import TypedDict

# Rev 2.1 R2-1: the only identifiers allowed after FROM/JOIN in og/query.py,
# og/change/report.py, og/eval/score.py (pred_from_db) and og/eval/change_score.py.
READ_ALLOWLIST = frozenset(
    {
        "visible_obligation",
        "visible_obligation_clause",
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
    "It does not mean overdue, and it does not mean there is no obligation."
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
    offset: int
    truncated: bool
    unresolved_party_count: int
    note: str  # PENDING_NOTE


def list_agreements(con: sqlite3.Connection) -> list[AgreementOut]:
    raise NotImplementedError


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
    raise NotImplementedError


def upcoming_deadlines(
    con: sqlite3.Connection,
    *,
    days: int = 90,
    party: str | None = None,
    as_of: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> DeadlinesOut:
    raise NotImplementedError


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
    raise NotImplementedError
