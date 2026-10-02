import hashlib
import json
import sqlite3
from decimal import Decimal

import pytest

from og.extract.types import (
    Attempt,
    Evidence,
    RunInfo,
    VerifiedEvent,
    VerifiedObligation,
    VerifiedParty,
    VerifyResult,
    WriteRefused,
)
from og.store.db import connect
from og.store.writer import extract_defined_terms, write_snapshot
from og.textdoc import Page, Section, Segment, TextDoc

BASE_LINES = [
    "LEASE between DIGITAL 55 MIDDLESEX, LLC as Landlord and CONSTANT CONTACT, INC. as Tenant.",
    "1. \u201cCommencement Date\u201d means January 1, 2011.",
    "2. Tenant shall pay Base Rent of $54,000 per month.",
    "3. Landlord shall deliver the Tenant Space within 30 days after the Commencement Date.",
    "4. The \u201cTerm\u201d is ten years and the Rent (the \u201cBase Rent\u201d) is fixed.",
    "5. The \u201cTerm\u201d means ten years (\u201cPremises\u201d) and again (\u201cTerm\u201d).",
]
AMEND_LINES = [
    "FIRST AMENDMENT between DIGITAL 55 MIDDLESEX, LLC as Landlord and"
    " CONSTANT CONTACT, INC. as Tenant.",
    "1. Tenant shall pay the Expansion Fee within 10 days after the Commencement Date.",
]


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


BASE = make_doc("a1", BASE_LINES, "sha-a1")
AMEND = make_doc("a2", AMEND_LINES, "sha-a2")
OTHER = make_doc("a3", BASE_LINES, "sha-a3")


def ev(doc, quote, nth=0):
    start = -1
    for _ in range(nth + 1):
        start = doc.text.index(quote, start + 1)
    end = start + len(quote)
    seg = next(s for s in doc.segments if s.char_start <= start < s.char_end)
    sec = doc.section_by_id(seg.section_id)
    return Evidence(seg.id, sec.id, sec.number, seg.page, start, end, quote)


def obligation(doc, quote, **kw):
    fields = dict(
        type="payment",
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
    fields.update(kw)
    return VerifiedObligation(evidence=ev(doc, quote), **fields)


def party(doc, quote, name, role):
    return VerifiedParty(ev(doc, quote), name, role)


def event(doc, quote, name, date=None, nth=0):
    return VerifiedEvent(ev(doc, quote, nth), name, date, "active")


def base_parties(doc=BASE):
    return [
        party(
            doc, "DIGITAL 55 MIDDLESEX, LLC as Landlord", "DIGITAL 55 MIDDLESEX, LLC", "landlord"
        ),
        party(doc, "CONSTANT CONTACT, INC. as Tenant", "CONSTANT CONTACT, INC.", "tenant"),
    ]


def base_result(doc=BASE):
    return VerifyResult(
        obligations=[
            obligation(
                doc,
                "Tenant shall pay Base Rent of $54,000 per month.",
                owed_by="Tenant",
                owed_to="Landlord",
                amount=Decimal("54000"),
                currency="USD",
            ),
            obligation(
                doc,
                "Landlord shall deliver the Tenant Space within 30 days after the"
                " Commencement Date.",
                type="delivery",
                owed_by="Landlord",
                owed_to="Tenant",
                anchor_event="Commencement Date",
                offset_days=30,
            ),
        ],
        events=[
            event(
                doc,
                "\u201cCommencement Date\u201d means January 1, 2011.",
                "Commencement Date",
                "2011-01-01",
            )
        ],
        parties=base_parties(doc),
        drops=[],
        corrections=[],
    )


def source(doc, sha=None):
    return {
        "id": doc.doc_id,
        "url": f"https://www.sec.gov/{doc.doc_id}.htm",
        "filer": "Filer",
        "filing_date": "2011-03-09",
        "form": "10-K",
        "exhibit": "10.41",
        "local_path": f"data/raw/{doc.doc_id}.htm",
        "sha256": sha or doc.source_sha256,
    }


def agreement(doc, type_="lease", base=None):
    return {
        "id": doc.doc_id,
        "title": f"Agreement {doc.doc_id}",
        "type": type_,
        "effective_date": None,
        "base_agreement_id": base,
        "is_form": False,
    }


def run(doc, run_id="r1", prompt_version="extract_v1@abc12345"):
    return RunInfo(
        run_id=run_id,
        prompt_version=prompt_version,
        model="claude-sonnet-5-5",
        textdoc_sha256=hashlib.sha256(doc.to_json().encode()).hexdigest(),
        attempts=[Attempt("claude-sonnet-5-5", 100, 50, 0, 80, False)],
    )


def write(con, doc, result, *, run_id="r1", type_="lease", base=None, src=None):
    return write_snapshot(
        con,
        source=src or source(doc),
        agreement=agreement(doc, type_, base),
        doc=doc,
        run=run(doc, run_id),
        result=result,
    )


@pytest.fixture
def con(tmp_path):
    return connect(tmp_path / "g.db")


def counts(con, agreement_id):
    q = {
        "obligation": "SELECT count(*) FROM obligation WHERE agreement_id=?",
        "event": "SELECT count(*) FROM event WHERE agreement_id=?",
        "agreement_party": "SELECT count(*) FROM agreement_party WHERE agreement_id=?",
        "defined_term": "SELECT count(*) FROM defined_term WHERE agreement_id=?",
        "clause_ref": "SELECT count(*) FROM clause_ref WHERE agreement_id=?",
        "extraction_run": "SELECT count(*) FROM extraction_run WHERE source_id=?",
    }
    return {k: con.execute(v, (agreement_id,)).fetchone()[0] for k, v in q.items()}


def test_happy_path_counts_and_stats(con):
    stats = write(con, BASE, base_result())
    assert stats.obligations == 2
    assert stats.events == 1
    assert stats.parties == 2
    assert stats.defined_terms == len(extract_defined_terms(BASE))
    assert stats.unresolved_parties == 0
    assert stats.unresolved_anchors == 0


def test_every_row_is_visible_and_grounded(con):
    write(con, BASE, base_result())
    assert con.execute("SELECT count(*) FROM visible_obligation").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM visible_agreement_party").fetchone()[0] == 2
    n_terms = con.execute("SELECT count(*) FROM defined_term").fetchone()[0]
    assert con.execute("SELECT count(*) FROM visible_defined_term").fetchone()[0] == n_terms
    rows = con.execute(
        "SELECT agreement_id, char_start, char_end, span_text, grounded FROM clause_ref"
    ).fetchall()
    assert rows
    for agreement_id, start, end, span, grounded in rows:
        assert agreement_id == "a1"
        assert grounded == 1
        assert span == BASE.text[start:end]


def test_obligation_fields_are_stored(con):
    write(con, BASE, base_result())
    rent = con.execute(
        "SELECT o.amount, o.currency, o.status, pb.name, pt.name, o.description"
        " FROM obligation o JOIN party pb ON pb.id = o.owed_by JOIN party pt ON pt.id = o.owed_to"
        " WHERE o.type = 'payment'"
    ).fetchone()
    assert rent == (
        54000.0,
        "USD",
        "active",
        "CONSTANT CONTACT, INC.",
        "DIGITAL 55 MIDDLESEX, LLC",
        "Tenant shall pay Base Rent of $54,000 per month.",
    )
    deliver = con.execute(
        "SELECT o.offset_days, e.name, e.date FROM obligation o"
        " JOIN event e ON e.id = o.anchor_event_id WHERE o.type = 'delivery'"
    ).fetchone()
    assert deliver == (30, "Commencement Date", "2011-01-01")
    section_page = con.execute(
        "SELECT c.section, c.page FROM clause_ref c JOIN obligation o ON o.id = c.obligation_id"
        " WHERE o.type = 'payment'"
    ).fetchone()
    assert section_page == ("2", 1)


def test_obligations_carry_the_run(con):
    write(con, BASE, base_result())
    run_row = con.execute(
        "SELECT id, run_id, prompt_version, model, textdoc_sha256, model_attempts_json"
        " FROM extraction_run WHERE source_id='a1'"
    ).fetchone()
    assert run_row[1:5] == (
        "r1",
        "extract_v1@abc12345",
        "claude-sonnet-5-5",
        hashlib.sha256(BASE.to_json().encode()).hexdigest(),
    )
    attempts = json.loads(run_row[5])
    assert len(attempts) == 1 and attempts[0]["model"] == "claude-sonnet-5-5"
    ids = {r[0] for r in con.execute("SELECT extraction_run_id FROM obligation")}
    assert ids == {run_row[0]}


def test_rewrite_replaces_snapshot_and_leaves_other_agreements(con):
    write(con, OTHER, base_result(OTHER), run_id="other")
    other_before = counts(con, "a3")
    write(con, BASE, base_result(), run_id="r1")
    first = counts(con, "a1")
    write(con, BASE, base_result(), run_id="r2")
    assert counts(con, "a1") == first
    assert counts(con, "a3") == other_before
    runs = con.execute("SELECT run_id FROM extraction_run WHERE source_id='a1'").fetchall()
    assert runs == [("r2",)]


def test_failed_write_rolls_back_to_previous_snapshot(con):
    write(con, BASE, base_result())
    before = counts(con, "a1")
    bad = base_result()
    broken = VerifyResult(
        obligations=[*bad.obligations, obligation(BASE, "Tenant shall pay", type="bogus")],
        events=bad.events,
        parties=bad.parties,
        drops=[],
        corrections=[],
    )
    with pytest.raises((sqlite3.IntegrityError, WriteRefused)):
        write(con, BASE, broken, run_id="r2")
    assert counts(con, "a1") == before
    runs = con.execute("SELECT run_id FROM extraction_run WHERE source_id='a1'").fetchall()
    assert runs == [("r1",)]


def test_pin_mismatch_refused(con):
    with pytest.raises(WriteRefused) as e:
        write(con, BASE, base_result(), src=source(BASE, sha="different"))
    assert e.value.args[0] == "pin_mismatch"
    assert counts(con, "a1")["obligation"] == 0


def test_source_repin_refused(con):
    write(con, BASE, base_result())
    repinned = make_doc("a1", BASE_LINES, "sha-new")
    with pytest.raises(WriteRefused) as e:
        write(con, repinned, base_result(repinned), run_id="r2")
    assert e.value.args[0] == "source_repin"


def test_span_mismatch_refused(con):
    good = base_result()
    o = good.obligations[0]
    bad_ev = Evidence(
        o.evidence.segment_id,
        o.evidence.section_id,
        o.evidence.section_number,
        o.evidence.page,
        o.evidence.char_start,
        o.evidence.char_end,
        "Tenant shall pay Base Rent of $45,000 per month.",
    )
    bad = VerifyResult(
        obligations=[
            VerifiedObligation(**{**o.__dict__, "evidence": bad_ev}),
            *good.obligations[1:],
        ],
        events=good.events,
        parties=good.parties,
        drops=[],
        corrections=[],
    )
    with pytest.raises(WriteRefused) as e:
        write(con, BASE, bad)
    assert e.value.args[0] == "span_mismatch"
    assert counts(con, "a1")["obligation"] == 0


def amendment_result(doc=AMEND):
    return VerifyResult(
        obligations=[
            obligation(
                doc,
                "Tenant shall pay the Expansion Fee within 10 days after the Commencement Date.",
                owed_by="Tenant",
                owed_to="Landlord",
                anchor_event="Commencement Date",
                offset_days=10,
            )
        ],
        events=[],
        parties=base_parties(doc),
        drops=[],
        corrections=[],
    )


def test_anchor_resolves_through_base_agreement(con):
    write(con, BASE, base_result())
    stats = write(con, AMEND, amendment_result(), run_id="ra", type_="amendment", base="a1")
    assert stats.unresolved_anchors == 0
    row = con.execute(
        "SELECT e.agreement_id, o.offset_days FROM obligation o"
        " JOIN event e ON e.id = o.anchor_event_id WHERE o.agreement_id='a2'"
    ).fetchone()
    assert row == ("a1", 10)


def test_dependents_exist_refused(con):
    write(con, BASE, base_result())
    write(con, AMEND, amendment_result(), run_id="ra", type_="amendment", base="a1")
    with pytest.raises(WriteRefused) as e:
        write(con, BASE, base_result(), run_id="r2")
    assert e.value.args[0] == "dependents_exist"
    assert counts(con, "a2")["obligation"] == 1


def test_ambiguous_base_anchor_left_unresolved(con):
    base = base_result()
    two_events = VerifyResult(
        obligations=[base.obligations[0]],
        events=[
            event(
                BASE,
                "\u201cCommencement Date\u201d means January 1, 2011.",
                "Commencement Date",
                "2011-01-01",
            ),
            event(BASE, "Commencement Date", "Commencement Date", None, nth=1),
        ],
        parties=base.parties,
        drops=[],
        corrections=[],
    )
    write(con, BASE, two_events)
    stats = write(con, AMEND, amendment_result(), run_id="ra", type_="amendment", base="a1")
    assert stats.unresolved_anchors == 1
    row = con.execute(
        "SELECT anchor_event_id, offset_days FROM obligation WHERE agreement_id='a2'"
    ).fetchone()
    assert row == (None, None)


def test_anchor_resolves_in_same_agreement(con):
    stats = write(con, BASE, base_result())
    assert stats.unresolved_anchors == 0
    row = con.execute(
        "SELECT e.agreement_id FROM obligation o JOIN event e ON e.id = o.anchor_event_id"
    ).fetchone()
    assert row == ("a1",)


def test_ambiguous_role_left_unresolved(con):
    base = base_result()
    two_landlords = VerifyResult(
        obligations=[base.obligations[0]],
        events=[],
        parties=[
            party(
                BASE,
                "DIGITAL 55 MIDDLESEX, LLC as Landlord",
                "DIGITAL 55 MIDDLESEX, LLC",
                "landlord",
            ),
            party(BASE, "CONSTANT CONTACT, INC. as Tenant", "CONSTANT CONTACT, INC.", "landlord"),
        ],
        drops=[],
        corrections=[],
    )
    stats = write(con, BASE, two_landlords)
    assert stats.unresolved_parties == 2  # owed_by Tenant: no tenant; owed_to Landlord: two
    row = con.execute("SELECT owed_by, owed_to FROM obligation").fetchone()
    assert row == (None, None)


SUFFIX_LINES = [
    "LEASE between Digital 55 Middlesex, LLC as Landlord and Digital 55 Middlesex, Inc. as Tenant.",
    "1. Digital 55 Middlesex, Inc. shall pay rent to digital 55   middlesex, llc monthly.",
]
SUFFIX = make_doc("a4", SUFFIX_LINES, "sha-a4")


def test_distinct_suffix_entities_and_normalized_name_match(con):
    result = VerifyResult(
        obligations=[
            obligation(
                SUFFIX,
                "Digital 55 Middlesex, Inc. shall pay rent to digital 55   middlesex, llc monthly.",
                owed_by="Digital 55 Middlesex, Inc.",
                owed_to="digital 55   middlesex, llc",
            )
        ],
        events=[],
        parties=[
            party(
                SUFFIX,
                "Digital 55 Middlesex, LLC as Landlord",
                "Digital 55 Middlesex, LLC",
                "landlord",
            ),
            party(
                SUFFIX,
                "Digital 55 Middlesex, Inc. as Tenant",
                "Digital 55 Middlesex, Inc.",
                "tenant",
            ),
        ],
        drops=[],
        corrections=[],
    )
    stats = write(con, SUFFIX, result)
    assert stats.unresolved_parties == 0
    names = {r[0] for r in con.execute("SELECT name FROM party")}
    assert names == {"Digital 55 Middlesex, LLC", "Digital 55 Middlesex, Inc."}
    row = con.execute(
        "SELECT pb.name, pt.name FROM obligation o JOIN party pb ON pb.id = o.owed_by"
        " JOIN party pt ON pt.id = o.owed_to"
    ).fetchone()
    assert row == ("Digital 55 Middlesex, Inc.", "Digital 55 Middlesex, LLC")


def test_party_rows_are_shared_across_agreements(con):
    write(con, BASE, base_result())
    write(con, AMEND, amendment_result(), run_id="ra", type_="amendment", base="a1")
    assert con.execute("SELECT count(*) FROM party").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM agreement_party").fetchone()[0] == 4


def test_extract_defined_terms_patterns_and_first_occurrence():
    terms = extract_defined_terms(BASE)
    by_term = {t: (s, e) for t, s, e in terms}
    assert set(by_term) == {"Commencement Date", "Term", "Base Rent", "Premises"}
    s, e = by_term["Term"]
    assert BASE.text[s:e] == "\u201cTerm\u201d"
    assert s == BASE.text.index("\u201cTerm\u201d means")  # first defining occurrence wins
    s, e = by_term["Base Rent"]
    assert BASE.text[s:e] == "\u201cBase Rent\u201d"
    assert len(terms) == len(by_term)


def test_defined_terms_written_with_clause_refs(con):
    write(con, BASE, base_result())
    rows = con.execute(
        "SELECT d.term, c.span_text, c.grounded FROM visible_defined_term d"
        " JOIN clause_ref c ON c.id = d.clause_ref_id ORDER BY c.char_start"
    ).fetchall()
    assert [r[0] for r in rows] == ["Commencement Date", "Base Rent", "Term", "Premises"]
    assert all(r[1] == f"\u201c{r[0]}\u201d" and r[2] == 1 for r in rows)
