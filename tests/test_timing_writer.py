"""Task 41: the writer derives and stores timing inside the snapshot transaction.

Plan rev 2 W5-3, W5-7, W5-8, W5-10, W5-11 and rev 2.1. write_snapshot calls og.timing
(parse, resolve, defined_dates) for every verified obligation and writes:
- one obligation_timing row per obligation (untimed included);
- each trigger as a ClauseRef with obligation_id NULL, owned only by obligation_timing,
  so the original extraction evidence (visible_obligation_clause, pred_from_db) is
  unchanged;
- defined-date events with their own full declaration citations, deduplicated within
  the agreement by normalized name.

Pinned decisions (plan rev 2 W5-8, W5-10):
- a dated deterministic candidate replaces an undated model event of the same name and
  cites the declaration, never the old name-only evidence;
- equal dates collapse to one event; conflicting dates leave the event dateless and a
  dependent deadline unresolved with reason conflicting_dates;
- an ambiguous local name never falls back to the base agreement's event;
- re-extracting a base whose event anchors an amendment's timing row is REFUSED with
  WriteRefused("dependents_exist"), like the legacy anchor guard; the previous snapshot
  stays;
- a timing exception rolls the whole write back: nothing is downgraded to untimed.

SYNTHETIC documents, built like tests/test_writer.py. The sentences use only
unambiguous grammar cases (prompts/timing_grammar_v1.yaml): a declaration
"As of DATE (the “NAME”)", "on or before the NAME", "prior to the NAME",
"within thirty (30) days after receipt of an invoice", and a clause with no timing.
"""

import hashlib

import pytest

import og.store.writer as writer_mod
import og.timing
from og.eval.score import pred_from_db
from og.extract.types import (
    Attempt,
    Evidence,
    RunInfo,
    VerifiedEvent,
    VerifiedObligation,
    VerifyResult,
    WriteRefused,
)
from og.store.db import connect
from og.store.writer import write_snapshot
from og.textdoc import Page, Section, Segment, TextDoc

LQ, RQ = "“", "”"

BASE_LINES = [
    "LEASE between Landlord Co as Landlord and Tenant Co as Tenant.",
    f"1. As of January 1, 2011 (the {LQ}Commencement Date{RQ}), the Term begins.",
    "2. Landlord shall complete the Pathway Installation prior to the Commencement Date.",
    "3. Tenant shall pay each Utility Charge within thirty (30) days after receipt of an invoice.",
    "4. Tenant shall maintain the insurance described in Exhibit B.",
    "5. Prior to occupying the Tenant Space, Tenant shall deliver certificates of insurance.",
]
AMEND_LINES = [
    "FIRST AMENDMENT between Landlord Co as Landlord and Tenant Co as Tenant.",
    f"1. As of June 1, 2012 (the {LQ}Expansion Date{RQ}), the Premises are expanded.",
    "2. Landlord shall complete the Expansion Work on or before the Expansion Date.",
    "3. Landlord shall complete the Cage Work prior to the Commencement Date.",
]
CONFLICT_LINES = [
    "SECOND AMENDMENT between Landlord Co as Landlord and Tenant Co as Tenant.",
    f"1. As of June 1, 2012 (the {LQ}Expansion Date{RQ}), the Premises are expanded.",
    f"2. As of July 1, 2012 (the {LQ}Expansion Date{RQ}), the Premises are expanded again.",
    "3. Landlord shall complete the Expansion Work on or before the Expansion Date.",
    f"4. As of March 1, 2013 (the {LQ}Commencement Date{RQ}), the new rent starts.",
    f"5. As of April 1, 2013 (the {LQ}Commencement Date{RQ}), the new rent starts again.",
    "6. Landlord shall complete the Cage Work prior to the Commencement Date.",
]
EQUAL_LINES = [
    "THIRD AMENDMENT between Landlord Co as Landlord and Tenant Co as Tenant.",
    f"1. As of June 1, 2012 (the {LQ}Expansion Date{RQ}), the Premises are expanded.",
    f"2. As of June 1, 2012 (the {LQ}Expansion Date{RQ}), the Premises remain expanded.",
    "3. Landlord shall complete the Expansion Work on or before the Expansion Date.",
]

PATHWAY = "Landlord shall complete the Pathway Installation prior to the Commencement Date."
UTILITY = (
    "Tenant shall pay each Utility Charge within thirty (30) days after receipt of an invoice."
)
INSURANCE = "Tenant shall maintain the insurance described in Exhibit B."
OCCUPY = "Prior to occupying the Tenant Space, Tenant shall deliver certificates of insurance."
EXPANSION = "Landlord shall complete the Expansion Work on or before the Expansion Date."
CAGE = "Landlord shall complete the Cage Work prior to the Commencement Date."


def make_doc(doc_id, lines, sha):
    text = "\n".join(lines)
    sections, segments, pos = [], [], 0
    for i, line in enumerate(lines):
        sid = f"s{i:04d}"
        end = pos + len(line) + (1 if i < len(lines) - 1 else 0)
        sections.append(Section(sid, str(i) if i else None, f"H{i}", pos, end, None))
        segments.append(Segment(f"p{i + 1:04d}", sid, 1, pos, pos + len(line)))
        pos += len(line) + 1
    doc = TextDoc(doc_id, sha, text, sections, [Page(1, 0, len(text))], segments)
    doc.validate()
    return doc


BASE = make_doc("b1", BASE_LINES, "sha-b1")
AMEND = make_doc("x1", AMEND_LINES, "sha-x1")
CONFLICT = make_doc("x2", CONFLICT_LINES, "sha-x2")
EQUAL = make_doc("x3", EQUAL_LINES, "sha-x3")


def ev(doc, quote):
    start = doc.text.index(quote)
    seg = next(s for s in doc.segments if s.char_start <= start < s.char_end)
    sec = doc.section_by_id(seg.section_id)
    return Evidence(seg.id, sec.id, sec.number, seg.page, start, start + len(quote), quote)


def obligation(doc, quote, type_="delivery"):
    return VerifiedObligation(
        evidence=ev(doc, quote),
        type=type_,
        status="active",
        owed_by=None,
        owed_to=None,
        description=quote,
        amount=None,
        currency=None,
        due_date=None,
        anchor_event=None,
        offset_days=None,
        trigger=None,
    )


def result(doc, quotes, events=()):
    return VerifyResult(
        obligations=[obligation(doc, q) for q in quotes],
        events=list(events),
        parties=[],
        drops=[],
        corrections=[],
    )


def write(con, doc, res, *, run_id="r1", base=None, type_="lease"):
    run_id = f"{doc.doc_id}-{run_id}"
    return write_snapshot(
        con,
        source={
            "id": doc.doc_id,
            "url": f"https://www.sec.gov/{doc.doc_id}.htm",
            "filer": "Filer",
            "filing_date": "2011-03-09",
            "form": "10-K",
            "exhibit": "10.1",
            "local_path": f"data/raw/{doc.doc_id}.htm",
            "sha256": doc.source_sha256,
        },
        agreement={
            "id": doc.doc_id,
            "title": f"Agreement {doc.doc_id}",
            "type": type_,
            "effective_date": None,
            "base_agreement_id": base,
            "is_form": False,
        },
        doc=doc,
        run=RunInfo(
            run_id=run_id,
            prompt_version="extract_v1@abc12345",
            model="claude-sonnet-5-5",
            textdoc_sha256=hashlib.sha256(doc.to_json().encode()).hexdigest(),
            attempts=[Attempt("claude-sonnet-5-5", 100, 50, 0, 0, False)],
        ),
        result=res,
    )


BASE_QUOTES = [PATHWAY, UTILITY, INSURANCE, OCCUPY]


@pytest.fixture
def con(tmp_path):
    con = connect(tmp_path / "g.db")
    yield con
    con.close()


def oid(con, quote):
    return con.execute(
        "SELECT o.id FROM obligation o JOIN clause_ref c ON c.obligation_id = o.id"
        " WHERE c.span_text = ?",
        (quote,),
    ).fetchone()[0]


def timing(con, quote):
    return con.execute(
        "SELECT kind, relation, bound_date, reason, anchor_agreement_id, trigger_span_text"
        " FROM visible_obligation_timing WHERE obligation_id = ?",
        (oid(con, quote),),
    ).fetchone()


def orphan_refs(con):
    """ClauseRefs that nothing owns: no obligation, event, party, term, site, timing, finding."""
    return con.execute(
        "SELECT count(*) FROM clause_ref c WHERE c.obligation_id IS NULL"
        " AND c.id NOT IN (SELECT clause_ref_id FROM event WHERE clause_ref_id IS NOT NULL)"
        " AND c.id NOT IN (SELECT clause_ref_id FROM agreement_party)"
        " AND c.id NOT IN (SELECT clause_ref_id FROM defined_term)"
        " AND c.id NOT IN (SELECT clause_ref_id FROM agreement_site)"
        " AND c.id NOT IN (SELECT trigger_clause_ref_id FROM obligation_timing"
        "  WHERE trigger_clause_ref_id IS NOT NULL)"
    ).fetchone()[0]


# --- one row per obligation, kinds and citations ---------------------------------------------


def test_every_obligation_gets_a_timing_row(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    n_obl = con.execute("SELECT count(*) FROM obligation").fetchone()[0]
    assert con.execute("SELECT count(*) FROM obligation_timing").fetchone()[0] == n_obl == 4
    assert con.execute("SELECT count(*) FROM visible_obligation_timing").fetchone()[0] == 4


def test_defined_event_bound_is_scheduled_with_a_strict_relation(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    kind, relation, bound, reason, anchor_agreement, trig = timing(con, PATHWAY)
    assert (kind, relation, bound, reason, anchor_agreement) == (
        "scheduled",
        "lt",
        "2011-01-01",
        None,
        "b1",
    )
    assert "prior to the Commencement Date" in trig
    lifecycle, due = con.execute(
        "SELECT lifecycle, effective_due FROM visible_obligation WHERE id = ?", (oid(con, PATHWAY),)
    ).fetchone()
    assert (lifecycle, due) == ("scheduled", None)


def test_invoice_trigger_is_contingent_with_no_date(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    kind, relation, bound, reason, _anchor, trig = timing(con, UTILITY)
    assert (kind, relation, bound, reason) == ("contingent", "lte", None, None)
    assert "receipt of an invoice" in trig
    off = con.execute(
        "SELECT offset_days, offset_unit, trigger_kind FROM obligation_timing"
        " WHERE obligation_id = ?",
        (oid(con, UTILITY),),
    ).fetchone()
    assert off == (30, "calendar", "invoice")


def test_clause_without_timing_is_untimed(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    assert timing(con, INSURANCE)[:4] == ("untimed", None, None, None)
    assert timing(con, INSURANCE)[5] is None


def test_trigger_refs_are_exact_slices_owned_only_by_timing(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    rows = con.execute(
        "SELECT t.obligation_id, c.obligation_id, c.grounded, c.char_start, c.char_end,"
        " c.span_text FROM obligation_timing t JOIN clause_ref c ON c.id = t.trigger_clause_ref_id"
    ).fetchall()
    assert rows
    for owner, linked_obligation, grounded, start, end, span in rows:
        assert linked_obligation is None, "timing evidence is not attached via obligation_id"
        assert grounded == 1
        assert BASE.text[start:end] == span
        o_start, o_end = con.execute(
            "SELECT char_start, char_end FROM clause_ref WHERE obligation_id = ?", (owner,)
        ).fetchone()
        assert o_start <= start and end <= o_end


def test_extraction_evidence_is_unchanged_by_a_same_start_trigger(con):
    """Astra's real 128 concern: a shorter same-start trigger must not become the quote."""
    write(con, BASE, result(BASE, BASE_QUOTES))
    occupy = oid(con, OCCUPY)
    clauses = con.execute(
        "SELECT span_text FROM visible_obligation_clause WHERE obligation_id = ?", (occupy,)
    ).fetchall()
    assert clauses == [(OCCUPY,)]
    preds = {p.span_text for p in pred_from_db(con, "b1")}
    assert OCCUPY in preds
    assert not any(p != q and q.startswith(p) for p in preds for q in BASE_QUOTES)


# --- defined-date events -----------------------------------------------------------------------


def events(con, agreement, name):
    return con.execute(
        "SELECT e.id, e.date, c.span_text FROM event e JOIN clause_ref c ON c.id = e.clause_ref_id"
        " WHERE e.agreement_id = ? AND e.name = ?",
        (agreement, name),
    ).fetchall()


def test_declaration_event_carries_its_full_declaration_citation(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    [(_eid, date, span)] = events(con, "b1", "Commencement Date")
    assert date == "2011-01-01"
    assert span == f"As of January 1, 2011 (the {LQ}Commencement Date{RQ})"


def test_dated_candidate_replaces_an_undated_model_event(con):
    undated = VerifiedEvent(
        ev(BASE, f"the {LQ}Commencement Date{RQ}"), "Commencement Date", None, "active"
    )
    write(con, BASE, result(BASE, BASE_QUOTES, events=[undated]))
    rows = events(con, "b1", "Commencement Date")
    assert len(rows) == 1
    _eid, date, span = rows[0]
    assert date == "2011-01-01"
    assert "January 1, 2011" in span, "the date cites the declaration, not the name-only quote"
    assert timing(con, PATHWAY)[:3] == ("scheduled", "lt", "2011-01-01")


def test_equal_dates_collapse_to_one_event(con):
    write(con, EQUAL, result(EQUAL, [EXPANSION]))
    rows = events(con, "x3", "Expansion Date")
    assert len(rows) == 1 and rows[0][1] == "2012-06-01"
    assert timing(con, EXPANSION)[:3] == ("scheduled", "lte", "2012-06-01")


def test_conflicting_dates_leave_the_dependent_unresolved(con):
    write(con, CONFLICT, result(CONFLICT, [EXPANSION]))
    dated = [r for r in events(con, "x2", "Expansion Date") if r[1] is not None]
    assert not dated, "conflicting declarations never yield a dated event"
    kind, relation, bound, reason, *_ = timing(con, EXPANSION)
    assert (kind, bound, reason) == ("unresolved", None, "conflicting_dates")


def test_ambiguous_local_name_never_falls_back_to_the_base(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    write(con, CONFLICT, result(CONFLICT, [CAGE]), base="b1", type_="amendment")
    kind, _relation, bound, reason, *_ = timing(con, CAGE)
    assert (kind, bound, reason) == ("unresolved", None, "conflicting_dates")


def test_amendment_binds_a_base_anchor_when_it_has_no_local_definition(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    write(con, AMEND, result(AMEND, [EXPANSION, CAGE]), base="b1", type_="amendment")
    assert timing(con, EXPANSION)[:5] == ("scheduled", "lte", "2012-06-01", None, "x1")
    assert timing(con, CAGE)[:5] == ("scheduled", "lt", "2011-01-01", None, "b1")


# --- snapshot replacement, dependencies, rollback ----------------------------------------------


def test_reextraction_replaces_timing_rows_and_refs(con):
    write(con, BASE, result(BASE, BASE_QUOTES), run_id="r1")
    before = con.execute("SELECT count(*) FROM obligation_timing").fetchone()[0]
    write(con, BASE, result(BASE, BASE_QUOTES), run_id="r2")
    assert con.execute("SELECT count(*) FROM obligation_timing").fetchone()[0] == before
    assert orphan_refs(con) == 0
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert timing(con, PATHWAY)[:3] == ("scheduled", "lt", "2011-01-01")


def test_reextracting_a_base_with_timing_dependents_is_refused(con):
    write(con, BASE, result(BASE, BASE_QUOTES))
    write(con, AMEND, result(AMEND, [EXPANSION, CAGE]), base="b1", type_="amendment")
    run_before = con.execute("SELECT run_id FROM extraction_run WHERE source_id='b1'").fetchone()
    with pytest.raises(WriteRefused, match="dependents_exist"):
        write(con, BASE, result(BASE, BASE_QUOTES), run_id="r2")
    assert (
        con.execute("SELECT run_id FROM extraction_run WHERE source_id='b1'").fetchone()
        == run_before
    )
    assert timing(con, CAGE)[:3] == ("scheduled", "lt", "2011-01-01")


def _boom(*_args, **_kwargs):
    raise RuntimeError("timing failure")


def test_a_timing_exception_rolls_back_the_whole_write(con, monkeypatch):
    write(con, BASE, result(BASE, BASE_QUOTES), run_id="r1")
    kinds_before = con.execute(
        "SELECT obligation_id, kind FROM obligation_timing ORDER BY obligation_id"
    ).fetchall()
    for name in ("parse", "resolve"):
        target = getattr(og.timing, name)
        monkeypatch.setattr(og.timing, name, _boom)
        for attr, value in list(vars(writer_mod).items()):
            if value is target:
                monkeypatch.setattr(writer_mod, attr, _boom)
    with pytest.raises(RuntimeError, match="timing failure"):
        write(con, BASE, result(BASE, BASE_QUOTES), run_id="r2")
    assert con.execute("SELECT run_id FROM extraction_run").fetchall() == [("b1-r1",)]
    assert (
        con.execute(
            "SELECT obligation_id, kind FROM obligation_timing ORDER BY obligation_id"
        ).fetchall()
        == kinds_before
    )
    assert ("untimed",) not in con.execute(
        "SELECT kind FROM obligation_timing WHERE obligation_id = ?", (oid(con, PATHWAY),)
    ).fetchall()
