"""The snapshot writer: verified items in, one grounded graph snapshot out.

The writer is the only code that sets grounded = 1. Every row it writes
carries a ClauseRef copied from verified evidence (or, for defined terms,
located deterministically in the TextDoc), and re-extracting a source
replaces that source's snapshot in a single transaction (ADR-008).

Wave 4 (Task 33, rev 2 W4-8/W4-9): a sources.yaml entry may pin its site
(``site: {segment_id, quote, name, location}``). The pin is verified against
the TextDoc before any write (the quote grounds exactly in that segment;
name and location are copied from the quote); an invalid pin refuses the
whole write. A site is immutable and unique on (name, location); the cited
``agreement_site`` binding is replaced with the snapshot.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from og.extract.types import (
    ROLES,
    Evidence,
    RunInfo,
    VerifiedEvent,
    VerifiedObligation,
    VerifiedParty,
    VerifyResult,
    WriteRefused,
    WriteStats,
)
from og.textdoc import TextDoc

# Deterministic defined-term patterns: "Term" means, (the "Term"), ("Term").
# Curly quotes; the span covers the quotes, the returned term does not.
_DEFINED_TERM_RE = re.compile(
    "\u201c([^\u201c\u201d]+)\u201d\\s+means"
    r"|\(\s*the\s+\u201c([^\u201c\u201d]+)\u201d\s*\)"
    r"|\(\s*\u201c([^\u201c\u201d]+)\u201d\s*\)"
)


def extract_defined_terms(doc: TextDoc) -> list[tuple[str, int, int]]:
    """First defining occurrence of each quoted term, in document order.

    Returns (term, char_start, char_end) where the offsets cover the curly
    quotes and the term is the text between them.
    """
    found: dict[str, tuple[str, int, int]] = {}
    for m in _DEFINED_TERM_RE.finditer(doc.text):
        group = m.lastindex
        assert group is not None  # every alternative has exactly one group
        term = m.group(group)
        if term in found:
            continue
        found[term] = (term, m.start(group) - 1, m.end(group) + 1)
    return list(found.values())


def _verify_site_pin(doc: TextDoc, pin: object) -> dict[str, Any] | None:
    """Verify a sources.yaml site pin; WriteRefused("site_pin_invalid") on any mismatch.

    Returns the grounded pin ({name, location, section, page, char_start,
    char_end, span_text}) or None when the entry carries no pin. The quote
    must appear verbatim inside the pinned segment; name and location must be
    copied from it (never inferred).
    """
    if pin is None:
        return None
    if not isinstance(pin, dict):
        raise WriteRefused("site_pin_invalid")
    segment_id = pin.get("segment_id")
    quote = pin.get("quote")
    name = pin.get("name")
    location = pin.get("location")
    if not all(isinstance(v, str) and v for v in (segment_id, quote, name, location)):
        raise WriteRefused("site_pin_invalid")
    segment = next((s for s in doc.segments if s.id == segment_id), None)
    if segment is None:
        raise WriteRefused("site_pin_invalid")
    start = doc.text.find(quote, segment.char_start, segment.char_end)
    if start < 0:
        raise WriteRefused("site_pin_invalid")
    if name not in quote or location not in quote:
        raise WriteRefused("site_pin_invalid")
    section = doc.section_for(start)
    return {
        "name": name,
        "location": location,
        "section": section.number if section is not None else None,
        "page": doc.page_for(start),
        "char_start": start,
        "char_end": start + len(quote),
        "span_text": quote,
    }


def _write_site_pin(con: sqlite3.Connection, agreement_id: str, pin: dict[str, Any]) -> None:
    """One immutable site row (unique on name, location) plus its cited binding.

    The site row is never updated: a re-extraction either reuses it or leaves
    it for the other agreements that cite it (W4-9).
    """
    row = con.execute(
        "SELECT id FROM site WHERE name = ? AND location IS ?",
        (pin["name"], pin["location"]),
    ).fetchone()
    if row is not None:
        site_id = row[0]
    else:
        site_id = con.execute(
            "INSERT INTO site(name, location, capacity_mw) VALUES(?, ?, NULL)",
            (pin["name"], pin["location"]),
        ).lastrowid
    ref = _insert_ref(
        con,
        agreement_id,
        section=pin["section"],
        page=pin["page"],
        char_start=pin["char_start"],
        char_end=pin["char_end"],
        span_text=pin["span_text"],
    )
    con.execute(
        "INSERT INTO agreement_site(agreement_id, site_id, clause_ref_id) VALUES(?, ?, ?)",
        (agreement_id, site_id, ref),
    )


def write_snapshot(
    con: sqlite3.Connection,
    *,
    source: dict[str, Any],
    agreement: dict[str, Any],
    doc: TextDoc,
    run: RunInfo,
    result: VerifyResult,
) -> WriteStats:
    """Replace this source's snapshot with the verified extraction result."""
    agreement_id = agreement["id"]
    site_pin = _check_preconditions(
        con, source=source, agreement_id=agreement_id, doc=doc, result=result
    )
    con.execute("BEGIN IMMEDIATE")
    try:
        _upsert_source(con, source)
        _upsert_agreement(con, agreement, source_id=source["id"])
        _delete_snapshot(con, agreement_id, source_id=source["id"])
        run_row_id = _insert_run(con, run, source_id=source["id"])
        party_rows = _write_parties(con, agreement_id, result.parties)
        event_rows = _write_events(con, agreement_id, result.events)
        n_terms = _write_defined_terms(con, agreement_id, doc)
        if site_pin is not None:
            _write_site_pin(con, agreement_id, site_pin)
        unresolved_parties, unresolved_anchors = _write_obligations(
            con,
            agreement_id,
            base_agreement_id=agreement.get("base_agreement_id"),
            run_row_id=run_row_id,
            obligations=result.obligations,
            party_rows=party_rows,
            event_rows=event_rows,
        )
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return WriteStats(
        obligations=len(result.obligations),
        events=len(result.events),
        parties=len(party_rows),
        defined_terms=n_terms,
        unresolved_parties=unresolved_parties,
        unresolved_anchors=unresolved_anchors,
    )


def _check_preconditions(
    con: sqlite3.Connection,
    *,
    source: dict[str, Any],
    agreement_id: str,
    doc: TextDoc,
    result: VerifyResult,
) -> dict[str, Any] | None:
    """Fail closed before any write; the previous snapshot must survive.

    Returns the verified site pin (or None when the entry has no pin).
    """
    if doc.source_sha256 != source["sha256"]:
        raise WriteRefused("pin_mismatch")
    row = con.execute("SELECT sha256 FROM source WHERE id = ?", (source["id"],)).fetchone()
    if row is not None and row[0] != source["sha256"]:
        raise WriteRefused("source_repin")
    site_pin = _verify_site_pin(doc, source.get("site"))
    evidences: list[Evidence] = [
        *(o.evidence for o in result.obligations),
        *(e.evidence for e in result.events),
        *(p.evidence for p in result.parties),
    ]
    for ev in evidences:
        if doc.text[ev.char_start : ev.char_end] != ev.span_text:
            raise WriteRefused("span_mismatch")
    dependents = con.execute(
        "SELECT count(*) FROM obligation o JOIN event e ON e.id = o.anchor_event_id"
        " WHERE e.agreement_id = ? AND o.agreement_id <> ?",
        (agreement_id, agreement_id),
    ).fetchone()[0]
    if dependents:
        raise WriteRefused("dependents_exist")
    return site_pin


def _upsert_source(con: sqlite3.Connection, source: dict[str, Any]) -> None:
    con.execute(
        "INSERT INTO source(id, url, filer, filing_date, form, exhibit, local_path, sha256)"
        " VALUES(:id, :url, :filer, :filing_date, :form, :exhibit, :local_path, :sha256)"
        " ON CONFLICT(id) DO UPDATE SET url = excluded.url, filer = excluded.filer,"
        " filing_date = excluded.filing_date, form = excluded.form,"
        " exhibit = excluded.exhibit, local_path = excluded.local_path,"
        " sha256 = excluded.sha256",
        source,
    )


def _upsert_agreement(
    con: sqlite3.Connection, agreement: dict[str, Any], *, source_id: str
) -> None:
    params = {
        "id": agreement["id"],
        "title": agreement["title"],
        "type": agreement["type"],
        "effective_date": agreement.get("effective_date"),
        "source_id": source_id,
        "base_agreement_id": agreement.get("base_agreement_id"),
        "is_form": int(bool(agreement.get("is_form", False))),
    }
    con.execute(
        "INSERT INTO agreement(id, title, type, effective_date, source_id,"
        " base_agreement_id, is_form)"
        " VALUES(:id, :title, :type, :effective_date, :source_id, :base_agreement_id, :is_form)"
        " ON CONFLICT(id) DO UPDATE SET title = excluded.title, type = excluded.type,"
        " effective_date = excluded.effective_date, source_id = excluded.source_id,"
        " base_agreement_id = excluded.base_agreement_id, is_form = excluded.is_form",
        params,
    )


def delete_change_runs(con: sqlite3.Connection, run_row_ids: Iterable[int]) -> None:
    """Delete change runs and everything they own, children before parents.

    A run owns its supersedes edges, gate decisions, findings, chain rows, and
    the ClauseRefs those findings cite (extraction never owns those refs).
    Called by _delete_snapshot (re-extraction invalidation) and by the change
    writer (run replacement), always inside a transaction.
    """
    ids = sorted({i for i in run_row_ids if i is not None})
    if not ids:
        return
    runs = ",".join("?" * len(ids))
    con.execute(f"DELETE FROM supersedes WHERE change_run_id IN ({runs})", ids)
    con.execute(f"DELETE FROM gate_decision WHERE change_run_id IN ({runs})", ids)
    refs = [
        row[0]
        for row in con.execute(
            f"SELECT new_clause_ref_id FROM change_finding WHERE change_run_id IN ({runs})"
            f" UNION SELECT old_clause_ref_id FROM change_finding WHERE change_run_id IN ({runs})"
            f" UNION SELECT context_clause_ref_id FROM change_finding"
            f" WHERE change_run_id IN ({runs})",
            ids * 3,
        )
        if row[0] is not None
    ]
    con.execute(f"DELETE FROM change_finding WHERE change_run_id IN ({runs})", ids)
    if refs:
        cited = ",".join("?" * len(refs))
        con.execute(
            f"DELETE FROM clause_ref WHERE id IN ({cited}) AND obligation_id IS NULL"
            " AND id NOT IN (SELECT clause_ref_id FROM agreement_party)"
            " AND id NOT IN (SELECT clause_ref_id FROM defined_term)"
            " AND id NOT IN (SELECT clause_ref_id FROM event WHERE clause_ref_id IS NOT NULL)"
            " AND id NOT IN (SELECT clause_ref_id FROM supersedes)"
            " AND id NOT IN (SELECT clause_ref_id FROM guarantees)"
            " AND id NOT IN (SELECT clause_ref_id FROM triggers)"
            " AND id NOT IN (SELECT new_clause_ref_id FROM change_finding)"
            " AND id NOT IN (SELECT old_clause_ref_id FROM change_finding"
            " WHERE old_clause_ref_id IS NOT NULL)"
            " AND id NOT IN (SELECT context_clause_ref_id FROM change_finding"
            " WHERE context_clause_ref_id IS NOT NULL)",
            refs,
        )
    con.execute(f"DELETE FROM change_run_chain WHERE change_run_id IN ({runs})", ids)
    con.execute(f"DELETE FROM change_run WHERE id IN ({runs})", ids)


def _delete_snapshot(con: sqlite3.Connection, agreement_id: str, *, source_id: str) -> None:
    """Children before parents; party rows themselves are never deleted."""
    # Site bindings go before the clause refs they cite (W4-9), so a
    # re-extraction with a changed or removed pin replaces the binding.
    con.execute("DELETE FROM agreement_site WHERE agreement_id = ?", (agreement_id,))
    # Re-extraction invalidation (rev 2 R4): every change run whose chain
    # includes this agreement was computed against a snapshot about to vanish.
    delete_change_runs(
        con,
        (
            row[0]
            for row in con.execute(
                "SELECT id FROM change_run WHERE change_order_id = ?"
                " UNION SELECT change_run_id FROM change_run_chain WHERE agreement_id = ?",
                (agreement_id, agreement_id),
            )
        ),
    )
    con.execute(
        "DELETE FROM clause_ref WHERE obligation_id IN"
        " (SELECT id FROM obligation WHERE agreement_id = ?)",
        (agreement_id,),
    )
    con.execute("DELETE FROM obligation WHERE agreement_id = ?", (agreement_id,))
    con.execute("DELETE FROM event WHERE agreement_id = ?", (agreement_id,))
    con.execute("DELETE FROM defined_term WHERE agreement_id = ?", (agreement_id,))
    con.execute("DELETE FROM agreement_party WHERE agreement_id = ?", (agreement_id,))
    con.execute("DELETE FROM clause_ref WHERE agreement_id = ?", (agreement_id,))
    con.execute("DELETE FROM extraction_run WHERE source_id = ?", (source_id,))


def _insert_run(con: sqlite3.Connection, run: RunInfo, *, source_id: str) -> int:
    cur = con.execute(
        "INSERT INTO extraction_run(run_id, source_id, prompt_version, model,"
        " textdoc_sha256, model_attempts_json, completed_at)"
        " VALUES(?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            run.run_id,
            source_id,
            run.prompt_version,
            run.model,
            run.textdoc_sha256,
            json.dumps([asdict(a) for a in run.attempts]),
        ),
    )
    return cur.lastrowid


def _insert_ref(
    con: sqlite3.Connection,
    agreement_id: str,
    *,
    section: str | None,
    page: int | None,
    char_start: int,
    char_end: int,
    span_text: str,
    obligation_id: int | None = None,
) -> int:
    """The writer is the only caller that may set grounded = 1."""
    cur = con.execute(
        "INSERT INTO clause_ref(obligation_id, agreement_id, section, page,"
        " char_start, char_end, span_text, grounded) VALUES(?, ?, ?, ?, ?, ?, ?, 1)",
        (obligation_id, agreement_id, section, page, char_start, char_end, span_text),
    )
    return cur.lastrowid


def _evidence_ref(
    con: sqlite3.Connection, agreement_id: str, ev: Evidence, *, obligation_id: int | None = None
) -> int:
    return _insert_ref(
        con,
        agreement_id,
        section=ev.section_number,
        page=ev.page,
        char_start=ev.char_start,
        char_end=ev.char_end,
        span_text=ev.span_text,
        obligation_id=obligation_id,
    )


def _party_id(con: sqlite3.Connection, name: str) -> int:
    """Party rows are global by exact stored name; created on first sight."""
    row = con.execute("SELECT id FROM party WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return row[0]
    return con.execute("INSERT INTO party(name) VALUES(?)", (name,)).lastrowid


def _write_parties(
    con: sqlite3.Connection, agreement_id: str, parties: list[VerifiedParty]
) -> list[tuple[int, str, str]]:
    """Returns (party_id, name, role) rows of this agreement's parties."""
    rows: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()
    for p in parties:
        pid = _party_id(con, p.name)
        if (pid, p.role) in seen:
            continue
        seen.add((pid, p.role))
        ref = _evidence_ref(con, agreement_id, p.evidence)
        con.execute(
            "INSERT INTO agreement_party(agreement_id, party_id, role, clause_ref_id)"
            " VALUES(?, ?, ?, ?)",
            (agreement_id, pid, p.role, ref),
        )
        rows.append((pid, p.name, p.role))
    return rows


def _write_events(
    con: sqlite3.Connection, agreement_id: str, events: list[VerifiedEvent]
) -> list[tuple[int, str]]:
    """Returns (event_row_id, name) rows of this agreement's events."""
    rows: list[tuple[int, str]] = []
    for e in events:
        ref = _evidence_ref(con, agreement_id, e.evidence)
        cur = con.execute(
            "INSERT INTO event(agreement_id, name, date, clause_ref_id) VALUES(?, ?, ?, ?)",
            (agreement_id, e.name, e.date, ref),
        )
        rows.append((cur.lastrowid, e.name))
    return rows


def _write_defined_terms(con: sqlite3.Connection, agreement_id: str, doc: TextDoc) -> int:
    count = 0
    for term, start, end in extract_defined_terms(doc):
        section = doc.section_for(start)
        ref = _insert_ref(
            con,
            agreement_id,
            section=section.number if section else None,
            page=doc.page_for(start),
            char_start=start,
            char_end=end,
            span_text=doc.text[start:end],
        )
        con.execute(
            "INSERT INTO defined_term(agreement_id, term, clause_ref_id) VALUES(?, ?, ?)",
            (agreement_id, term, ref),
        )
        count += 1
    return count


def _norm(value: str) -> str:
    """Case- and space-normalized comparison key; no other normalization."""
    return "".join(value.split()).casefold()


def _resolve_party(value: str | None, party_rows: list[tuple[int, str, str]]) -> int | None:
    """A role word among this agreement's roles, else an exact normalized name.

    Only a unique candidate resolves; ambiguity stays NULL and is counted.
    """
    if value is None:
        return None
    key = _norm(value)
    if key in ROLES:
        candidates = [pid for pid, _name, role in party_rows if role == key]
        if len(candidates) == 1:
            return candidates[0]
    candidates = [pid for pid, name, _role in party_rows if _norm(name) == key]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _resolve_anchor(
    name: str | None,
    same_agreement: list[tuple[int, str]],
    base_agreement: list[tuple[int, str]],
) -> int | None:
    """Exactly one event in this agreement, else exactly one in the base."""
    if name is None:
        return None
    key = _norm(name)
    candidates = [eid for eid, ename in same_agreement if _norm(ename) == key]
    if len(candidates) == 1:
        return candidates[0]
    candidates = [eid for eid, ename in base_agreement if _norm(ename) == key]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _write_obligations(
    con: sqlite3.Connection,
    agreement_id: str,
    *,
    base_agreement_id: str | None,
    run_row_id: int,
    obligations: list[VerifiedObligation],
    party_rows: list[tuple[int, str, str]],
    event_rows: list[tuple[int, str]],
) -> tuple[int, int]:
    base_event_rows: list[tuple[int, str]] = []
    if base_agreement_id is not None:
        base_event_rows = con.execute(
            "SELECT id, name FROM event WHERE agreement_id = ?", (base_agreement_id,)
        ).fetchall()
    unresolved_parties = 0
    unresolved_anchors = 0
    for o in obligations:
        owed_by = _resolve_party(o.owed_by, party_rows)
        owed_to = _resolve_party(o.owed_to, party_rows)
        unresolved_parties += o.owed_by is not None and owed_by is None
        unresolved_parties += o.owed_to is not None and owed_to is None
        anchor_id = _resolve_anchor(o.anchor_event, event_rows, base_event_rows)
        if o.anchor_event is not None and anchor_id is None:
            unresolved_anchors += 1
        cur = con.execute(
            "INSERT INTO obligation(agreement_id, site_id, type, owed_by, owed_to,"
            " description, amount, currency, due_date, anchor_event_id, offset_days,"
            ' "trigger", status, extraction_run_id)'
            " VALUES(?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agreement_id,
                o.type,
                owed_by,
                owed_to,
                o.description,
                None if o.amount is None else float(o.amount),
                o.currency,
                o.due_date,
                anchor_id,
                o.offset_days if anchor_id is not None else None,
                o.trigger,
                o.status,
                run_row_id,
            ),
        )
        _evidence_ref(con, agreement_id, o.evidence, obligation_id=cur.lastrowid)
    return unresolved_parties, unresolved_anchors
