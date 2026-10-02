"""Test helper (wave 5): a realistic timing set on a copy of the real v5 graph fixture.

`real_v5.db` carries no obligation_timing rows (the wave-5 writer derives them). This
helper inserts, by plain SQL, the timing the plan's rev 2 / rev 2.1 prescribes for a
handful of REAL obligations, citing REAL source text:

- defined-date events with their own grounded declaration ClauseRefs:
  base `(b) Commencement Date:` + `January 1, 2011` (p0429/p0430),
  Carbonite `(b) Target Commencement Date:` + `April 1, 2014.` (p0572/p0573),
  1A `As of June 1, 2012 (the “1A Expansion Date”)` (p0027),
  3A `expiring June 30, 2020 (the “3A Suite 409 Amended Surrender Date”)` (p0011);
- scheduled: 62, 65 (lt 2011-01-01), 236 (lt 2014-04-01), 514 (lte 2012-06-01),
  519 (lte 2020-06-30);
- contingent: 14 (invoice, within 15 days), 57 (invoice, no later than 30 days following);
- unresolved: 159 (business_days), 490 (redacted_offset);
- every other visible obligation has no timing row (reads as untimed).

Every trigger ClauseRef is an exact slice of the TextDoc inside the obligation's own
grounded extraction citation; it is owned by obligation_timing (obligation_id NULL).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from og.textdoc import TextDoc

FIX = Path(__file__).parent / "fixtures" / "graph"
REAL_V5 = FIX / "real_v5.db"
TEXT = FIX / "text"

BASE = "constantcontact-2011-ex1041"
A1 = "constantcontact-2012-ex101"
A3 = "endurance-2017-ex106"
CARBONITE = "carbonite-2014-ex1024"
TERAWULF = "terawulf-2025-ex10-1"
APPLIED = "applieddigital-2026-ex101"

# (agreement, char_start, char_end, name, ISO date) of each cited declaration.
DECLARATIONS = {
    "base_cd": (BASE, 44806, 44844, "Commencement Date", "2011-01-01"),
    "carb_tcd": (CARBONITE, 48757, 48801, "Target Commencement Date", "2014-04-01"),
    "a1_exp": (A1, 4057, 4101, "1A Expansion Date", "2012-06-01"),
    "a3_sur": (A3, 2775, 2841, "3A Suite 409 Amended Surrender Date", "2020-06-30"),
}

# obligation id -> (trigger needle inside its quote, kind, trigger_kind, relation,
#                   offset_days, offset_unit, anchor key, reason)
TIMING = {
    62: (
        "prior to the Commencement Date",
        "scheduled",
        "defined_event",
        "lt",
        None,
        None,
        "base_cd",
        None,
    ),
    65: (
        "prior to the Commencement Date",
        "scheduled",
        "defined_event",
        "lt",
        None,
        None,
        "base_cd",
        None,
    ),
    236: (
        "prior to the Target Commencement Date",
        "scheduled",
        "defined_event",
        "lt",
        None,
        None,
        "carb_tcd",
        None,
    ),
    514: (
        "on or before the 1A Expansion Date",
        "scheduled",
        "defined_event",
        "lte",
        None,
        None,
        "a1_exp",
        None,
    ),
    519: (
        "no later than the 3A Suite 409 Amended Surrender Date",
        "scheduled",
        "defined_event",
        "lte",
        None,
        None,
        "a3_sur",
        None,
    ),
    14: (
        "within fifteen (15) days after the receipt of a correct, itemized invoice",
        "contingent",
        "invoice",
        "lte",
        15,
        "calendar",
        None,
        None,
    ),
    57: (
        "no later than thirty (30) days following receipt of an invoice",
        "contingent",
        "invoice",
        "lte",
        30,
        "calendar",
        None,
        None,
    ),
    159: (
        "within ten (10) business days after the Effective Date",
        "unresolved",
        "defined_event",
        "lte",
        10,
        "business",
        None,
        "business_days",
    ),
    490: (
        "within [***] days after the occurrence thereof",
        "unresolved",
        "other_event",
        "lte",
        None,
        None,
        None,
        "redacted_offset",
    ),
}

SCHEDULED = {
    62: ("lt", "2011-01-01"),
    65: ("lt", "2011-01-01"),
    236: ("lt", "2014-04-01"),
    514: ("lte", "2012-06-01"),
    519: ("lte", "2020-06-30"),
}
CONTINGENT = {14, 57}
UNRESOLVED = {159: "business_days", 490: "redacted_offset"}
VISIBLE = 525


def textdoc(agreement_id: str) -> TextDoc:
    return TextDoc.load(TEXT / f"{agreement_id}.json")


def copy_v5(dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_V5, dst)
    return dst


def _ref(con: sqlite3.Connection, agreement_id: str, start: int, end: int) -> int:
    doc = textdoc(agreement_id)
    sec = doc.section_for(start)
    return con.execute(
        "INSERT INTO clause_ref(obligation_id, agreement_id, section, page, char_start,"
        " char_end, span_text, grounded) VALUES(NULL, ?, ?, ?, ?, ?, ?, 1)",
        (
            agreement_id,
            sec.number if sec else None,
            doc.page_for(start),
            start,
            end,
            doc.text[start:end],
        ),
    ).lastrowid


def obligation_quote(con: sqlite3.Connection, obligation_id: int) -> tuple[str, int, int, str]:
    """(agreement_id, char_start, char_end, span_text) of the grounded extraction citation."""
    return con.execute(
        "SELECT c.agreement_id, c.char_start, c.char_end, c.span_text FROM clause_ref c"
        " WHERE c.obligation_id = ? AND c.grounded = 1 ORDER BY c.char_start LIMIT 1",
        (obligation_id,),
    ).fetchone()


def insert_timing_set(db: Path) -> dict:
    """Insert the timing set; return ids: {"events": {key: id}, "decl_refs": {...},
    "trigger_refs": {obligation_id: ref id}}."""
    con = sqlite3.connect(db, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("BEGIN")
    events: dict[str, int] = {}
    decl_refs: dict[str, int] = {}
    for key, (agreement_id, start, end, name, iso) in DECLARATIONS.items():
        ref = _ref(con, agreement_id, start, end)
        decl_refs[key] = ref
        events[key] = con.execute(
            "INSERT INTO event(agreement_id, name, date, clause_ref_id) VALUES(?, ?, ?, ?)",
            (agreement_id, name, iso, ref),
        ).lastrowid
    trigger_refs: dict[int, int] = {}
    for oid, (needle, kind, tkind, rel, off, unit, anchor, reason) in TIMING.items():
        agreement_id, q0, _q1, quote = obligation_quote(con, oid)
        i = quote.index(needle)
        ref = _ref(con, agreement_id, q0 + i, q0 + i + len(needle))
        trigger_refs[oid] = ref
        bound = SCHEDULED[oid][1] if kind == "scheduled" else None
        con.execute(
            "INSERT INTO obligation_timing(obligation_id, kind, trigger_kind,"
            " trigger_clause_ref_id, relation, offset_days, offset_unit, anchor_event_id,"
            " bound_date, reason) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                oid,
                kind,
                tkind,
                ref,
                rel,
                off,
                unit,
                events[anchor] if anchor else None,
                bound,
                reason,
            ),
        )
    con.execute("COMMIT")
    con.close()
    return {"events": events, "decl_refs": decl_refs, "trigger_refs": trigger_refs}


def timed_v5(dst: Path) -> tuple[Path, dict]:
    """A copy of real_v5.db at `dst` with the timing set inserted."""
    copy_v5(dst)
    return dst, insert_timing_set(dst)
