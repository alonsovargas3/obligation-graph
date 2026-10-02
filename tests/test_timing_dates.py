"""Wave 5 rev 2.3: a calendar date is never a trigger event.

Found while integrating Task 41: "no later than June 30, 2020" parsed as contingent on an
"other_event" named "June 30" (the first-comma rule also cut the date). On the real corpus
the same defect made obligations 256 and 267 ("on or before June 15 ... after the end of
each calendar year") contingent; an annual date is a recurring schedule. Rule frozen in
prompts/timing_grammar_v1.yaml (calendar_date_not_event, trigger_span year-comma clause).
"""

import sqlite3
from pathlib import Path

from extract_fakes import build_doc

from og.extract.types import Evidence
from og.textdoc import TextDoc
from og.timing import parse, resolve

FIX = Path(__file__).parent / "fixtures" / "graph"


def _ev(doc, seg_id="p0001"):
    seg = doc.segment(seg_id)
    text = doc.text[seg.char_start : seg.char_end]
    return Evidence(seg.id, seg.section_id, "1", 1, seg.char_start, seg.char_end, text)


def _classify(sentence):
    doc = build_doc([("1", "Term", [sentence])])
    parsed = parse(doc, _ev(doc))
    return parsed, resolve(parsed, [])


def test_one_off_calendar_date_is_not_an_event():
    parsed, timing = _classify("Tenant shall surrender the Premises no later than June 30, 2020.")
    assert timing.kind == "unresolved"
    assert timing.reason == "anchor_not_found"
    assert timing.trigger_kind != "other_event"
    assert timing.bound_date is None
    assert parsed.trigger is not None
    assert parsed.trigger.span_text == "no later than June 30, 2020"


def test_annual_calendar_date_is_a_recurring_schedule():
    _, timing = _classify(
        "Landlord shall deliver the statement on or before June 15 after the end of each "
        "calendar year."
    )
    assert (timing.kind, timing.reason) == ("unresolved", "recurring_schedule")
    assert timing.bound_date is None


def test_defined_event_trigger_is_unaffected():
    parsed, _ = _classify("Tenant shall pay within thirty (30) days after receipt of an invoice.")
    assert parsed.trigger_kind == "invoice"


def _real(oid):
    con = sqlite3.connect(FIX / "real_v5.db")
    try:
        a, s, e, t, sec, pg = con.execute(
            "SELECT o.agreement_id, c.char_start, c.char_end, c.span_text, c.section, c.page"
            " FROM obligation o JOIN clause_ref c ON c.obligation_id = o.id AND c.grounded = 1"
            " WHERE o.id = ? ORDER BY c.char_start LIMIT 1",
            (oid,),
        ).fetchone()
    finally:
        con.close()
    doc = TextDoc.load(FIX / "text" / f"{a}.json")
    seg = next(x for x in doc.segments if x.char_start <= s < x.char_end)
    return doc, Evidence(seg.id, seg.section_id, sec, pg, s, e, t)


def test_real_annual_statement_deadlines_are_recurring():
    for oid in (256, 267):
        doc, ev = _real(oid)
        timing = resolve(parse(doc, ev), [])
        assert (timing.kind, timing.reason) == ("unresolved", "recurring_schedule"), oid
