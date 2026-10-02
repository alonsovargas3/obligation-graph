"""Wave 5 Task 40: og.timing on the REAL corpus (plan rev 2 / rev 2.1).

Inputs: tests/fixtures/graph/real_v4.db (each obligation's grounded extraction quote) and
the seven real TextDocs in tests/fixtures/graph/text/. Expected values are the executed,
hand-checked evidence in docs/reviews/2026-10-02-astra-wave5-review.md (rounds 1-3).
Every expected span is derived by slicing fixture text, never retyped.

Anchors for resolve() are built from defined_dates() of the obligation's own agreement and
its recorded base (the 1A and 3A amendments amend constantcontact-2011-ex1041).
"""

import re
import sqlite3
from functools import cache
from pathlib import Path

import pytest
import yaml

from og.extract.types import Evidence
from og.textdoc import TextDoc
from og.timing import GRAMMAR_PATH, CitedAnchor, defined_dates, parse, resolve

FIX = Path(__file__).parent / "fixtures" / "graph"
DB = FIX / "real_v4.db"
CC = "constantcontact-2011-ex1041"
A1 = "constantcontact-2012-ex101"
A3 = "endurance-2017-ex106"
CARB = "carbonite-2014-ex1024"


def norm(s):
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


@cache
def doc(agreement_id):
    return TextDoc.load(FIX / "text" / f"{agreement_id}.json")


@cache
def base_of():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return dict(con.execute("SELECT id, base_agreement_id FROM agreement"))
    finally:
        con.close()


@cache
def evidence_rows():
    """{obligation id: (agreement id, Evidence)} for the 525 visible obligations."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT o.id, o.agreement_id, c.char_start, c.char_end, c.span_text"
            " FROM obligation o JOIN clause_ref c ON c.obligation_id = o.id"
            " AND c.grounded = 1 AND c.agreement_id = o.agreement_id"
            " ORDER BY o.id, c.char_start, c.char_end"
        ).fetchall()
    finally:
        con.close()
    out = {}
    for oid, agreement, start, end, span in rows:
        if oid in out:
            continue
        d = doc(agreement)
        assert d.text[start:end] == span
        seg = next(s for s in d.segments if s.char_start <= start < s.char_end)
        sec = d.section_for(start)
        out[oid] = (
            agreement,
            Evidence(
                seg.id,
                sec.id if sec else seg.section_id,
                sec.number if sec else None,
                d.page_for(start) or seg.page,
                start,
                end,
                span,
            ),
        )
    return out


@cache
def dates_of(agreement_id):
    return tuple(defined_dates(doc(agreement_id)))


def anchors_for(agreement_id):
    chain = [agreement_id]
    if base_of().get(agreement_id):
        chain.append(base_of()[agreement_id])
    out, n = [], 0
    for a in chain:
        for d in dates_of(a):
            n += 1
            out.append(CitedAnchor(n, a, d.name, d.date, clause_ref_id=10_000 + n))
    return out


@cache
def timing(oid):
    agreement, ev = evidence_rows()[oid]
    parsed = parse(doc(agreement), ev)
    t = resolve(parsed, anchors_for(agreement), None)
    return parsed, t


def by_name(agreement_id):
    got = {}
    for d in dates_of(agreement_id):
        got.setdefault(norm(d.name), []).append(d)
    return got


def seg_range(agreement_id, first, last=None):
    d = doc(agreement_id)
    return d.segment(first).char_start, d.segment(last or first).char_end


# --- defined dates on the real documents ----------------------------------------------


def test_every_defined_date_evidence_is_an_exact_slice():
    for agreement in (CC, A1, A3, CARB):
        for d in dates_of(agreement):
            e = d.evidence
            assert doc(agreement).text[e.char_start : e.char_end] == e.span_text
            assert d.agreement_id == agreement


@pytest.mark.parametrize(
    "name,label_seg,value_seg",
    [("Effective Date", "p0427", "p0428"), ("Commencement Date", "p0429", "p0430")],
)
def test_cc_bli_rows(name, label_seg, value_seg):
    [d] = by_name(CC)[name]
    assert (d.date, d.form) == ("2011-01-01", "bli_row")
    lo, hi = seg_range(CC, label_seg, value_seg)
    assert lo <= d.evidence.char_start and d.evidence.char_end <= hi
    assert "January" in d.evidence.span_text and name in norm(d.evidence.span_text)


@pytest.mark.parametrize(
    "name,date,label_seg,value_seg",
    [
        ("Effective Date", "2013-12-31", "p0570", "p0571"),
        ("Target Commencement Date", "2014-04-01", "p0572", "p0573"),
        ("Outside Completion Date", "2014-05-31", "p0578", "p0579"),
    ],
)
def test_carbonite_bli_rows(name, date, label_seg, value_seg):
    [d] = by_name(CARB)[name]
    assert (d.date, d.form) == (date, "bli_row")
    lo, hi = seg_range(CARB, label_seg, value_seg)
    assert lo <= d.evidence.char_start and d.evidence.char_end <= hi


def test_carbonite_event_driven_commencement_date_has_no_defined_date():
    assert "Commencement Date" not in by_name(CARB)


def test_1a_expansion_date_comes_from_the_well_formed_p0027_declaration():
    [d] = by_name(A1)["1A Expansion Date"]
    assert d.date == "2012-06-01"
    lo, hi = seg_range(A1, "p0027")
    assert lo <= d.evidence.char_start and d.evidence.char_end <= hi
    assert d.evidence.span_text.startswith("As of June 1, 2012")


def test_3a_amended_surrender_date_binds_its_own_date_only():
    [d] = by_name(A3)["3A Suite 409 Amended Surrender Date"]
    assert d.date == "2020-06-30"
    lo, hi = seg_range(A3, "p0011")
    assert lo <= d.evidence.char_start and d.evidence.char_end <= hi
    assert "June 30, 2020" in d.evidence.span_text
    assert "2018" not in d.evidence.span_text
    assert all(x.date not in ("2018-06-30", "2018-07-01") for x in dates_of(A3))


# --- the five scheduled deadlines -----------------------------------------------------------

SCHEDULED = {
    62: ("lt", "2011-01-01", "prior to the Commencement Date"),
    65: ("lt", "2011-01-01", "prior to the Commencement Date"),
    236: ("lt", "2014-04-01", "prior to the Target Commencement Date"),
    514: ("lte", "2012-06-01", "on or before the 1A Expansion Date"),
    519: ("lte", "2020-06-30", "no later than the 3A Suite 409 Amended Surrender Date"),
}


@pytest.mark.parametrize("oid", sorted(SCHEDULED))
def test_the_five_scheduled_deadlines(oid):
    relation, bound, phrase = SCHEDULED[oid]
    agreement, ev = evidence_rows()[oid]
    assert phrase in ev.span_text
    _, t = timing(oid)
    assert (t.kind, t.relation, t.bound_date, t.reason) == ("scheduled", relation, bound, None)
    assert t.trigger is not None and phrase in t.trigger.span_text
    assert t.anchor_event_id is not None
    [a] = [a for a in anchors_for(agreement) if a.event_id == t.anchor_event_id]
    assert a.date == bound


def test_exactly_five_obligations_are_scheduled():
    scheduled = {oid for oid in evidence_rows() if timing(oid)[1].kind == "scheduled"}
    assert scheduled == set(SCHEDULED)


# --- the challenge set ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "oid,kind,reason",
    [
        (238, "unresolved", "conditional_or_compound"),
        (239, "unresolved", "conditional_or_compound"),
        (490, "unresolved", "redacted_offset"),
        (504, "unresolved", "redacted_offset"),
        (159, "unresolved", "business_days"),
        (279, "unresolved", "unsupported_unit"),
        (293, "unresolved", "cross_reference"),
        (434, "unresolved", "business_days"),
        (443, "unresolved", "month_granularity"),
    ],
)
def test_challenge_unresolved(oid, kind, reason):
    _, t = timing(oid)
    assert (t.kind, t.reason, t.bound_date) == (kind, reason, None)


def test_89_binds_to_demand_not_the_historical_effective_date():
    agreement, ev = evidence_rows()[89]
    assert "upon demand" in ev.span_text
    _, t = timing(89)
    assert (t.kind, t.trigger_kind, t.bound_date, t.anchor_event_id) == (
        "contingent",
        "demand",
        None,
        None,
    )
    assert t.trigger.span_text.startswith("upon demand")
    assert "Effective Date" not in t.trigger.span_text


def test_57_invoice_no_later_than_following():
    _, t = timing(57)
    assert (t.kind, t.relation, t.offset_days, t.offset_unit, t.trigger_kind) == (
        "contingent",
        "lte",
        30,
        "calendar",
        "invoice",
    )
    assert t.trigger.span_text.startswith("no later than thirty (30) days following")


def test_14_invoice_within_after():
    _, t = timing(14)
    assert (t.kind, t.relation, t.offset_days, t.trigger_kind) == (
        "contingent",
        "lte",
        15,
        "invoice",
    )
    assert t.trigger.span_text.startswith("within fifteen (15) days after")


def test_159_business_days_keep_the_quoted_trigger():
    _, t = timing(159)
    assert t.trigger is not None and "Effective Date" in t.trigger.span_text
    assert t.offset_unit == "business"


def test_239_does_not_pick_the_dated_business_day_branch():
    parsed, t = timing(239)
    assert t.kind == "unresolved" and t.bound_date is None and t.anchor_event_id is None


# --- invariants over all 525 real obligations -----------------------------------------------------


@cache
def timing_cues():
    raw = yaml.safe_load(Path(GRAMMAR_PATH).read_text(encoding="utf-8"))
    return tuple(raw["unresolved"]["anchor_not_found"]["timing_cues"])


def test_all_525_obligations_classify_with_exact_in_quote_triggers():
    rows = evidence_rows()
    assert len(rows) == 525
    for oid, (agreement, ev) in rows.items():
        _, t = timing(oid)
        if t.trigger is not None:
            text = doc(agreement).text
            assert text[t.trigger.char_start : t.trigger.char_end] == t.trigger.span_text, oid
            assert ev.char_start <= t.trigger.char_start, oid
            assert t.trigger.char_end <= ev.char_end, oid
        if t.kind == "unresolved":
            assert t.reason is not None and t.bound_date is None, oid
        if t.kind == "contingent":
            assert t.trigger is not None and t.bound_date is None, oid
        if t.kind != "scheduled":
            assert t.bound_date is None, oid


def test_untimed_rows_contain_no_timing_cue():
    for oid, (_agreement, ev) in evidence_rows().items():
        _, t = timing(oid)
        if t.kind != "untimed":
            continue
        quote = norm(ev.span_text).lower()
        for cue in timing_cues():
            assert not re.search(r"(?<!\w)" + re.escape(cue.lower()) + r"(?!\w)", quote), (
                oid,
                cue,
            )
