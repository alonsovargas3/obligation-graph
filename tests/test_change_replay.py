"""Rev 2.3: recorded real change-check responses replayed through verify (C7 findings).

The fixtures under tests/fixtures/api/change_v1/ are real claude-sonnet-5-5 outputs
from the C7 live run on the 1A and 3A chains. Two rule/contract mismatches surfaced
there and are pinned here:

1. prompts/change_v1.schema.json asks for a price `new_value` "exactly as written in
   new_quote" (e.g. "$41,496.00/month"); verify must accept a value that is either a
   plain decimal or contains exactly one money token, compared with the quote's tokens.
2. A price finding never stores a target label (rev 2.2). A stray label that is not in
   the quote is discarded and logged as a ChangeCorrection; the finding is kept.
   Supersedes keeps the strict rule (the label is its target).
"""

import json
from pathlib import Path

from change_fakes import A1_ID, A3_ID, BASE_ID, real_doc

from og.change.types import ChainDoc, RawFinding
from og.change.verify import verify_findings

FIX = Path(__file__).parent / "fixtures" / "api" / "change_v1"
DOCS = {i: real_doc(i) for i in (BASE_ID, A1_ID, A3_ID)}


def chain(co):
    members = [ChainDoc(BASE_ID, DOCS[BASE_ID], "base")]
    if co == A3_ID:
        members.append(ChainDoc(A1_ID, DOCS[A1_ID], "prior_amendment"))
    members.append(ChainDoc(co, DOCS[co], "change_order"))
    return members


def recorded(co, category):
    payload = json.loads((FIX / f"{co}-{category}.json").read_text(encoding="utf-8"))
    assert payload["category"] == category
    return [RawFinding(**f) for f in payload["findings"]]


def run(co, category, items=None):
    return verify_findings(
        chain(co), category, items if items is not None else recorded(co, category)
    )


def test_1a_price_values_written_with_units_are_kept():
    res = run(A1_ID, "price")
    assert res.drops == []
    assert [f.new_value for f in res.findings] == [
        "0.00",
        "41496.00",
        "42741.00",
        "44023.00",
        "45344.00",
    ]
    for f in res.findings:
        assert f.kind == "price_change"
        assert (f.old, f.old_origin, f.old_value, f.delta) == (None, "unresolved", None, None)
        assert f.currency == "USD"
        assert f.target_label is None
        assert f.context is not None and f.context.agreement_id == A1_ID
        doc = DOCS[A1_ID]
        ev = f.context.evidence
        assert doc.text[ev.char_start : ev.char_end] == ev.span_text


def test_3a_price_stray_label_is_discarded_not_the_finding():
    res = run(A3_ID, "price")
    assert res.drops == []
    assert [f.new_value for f in res.findings] == ["35596.80", "36664.70", "37764.65"]
    assert all(f.target_label is None and f.old is None for f in res.findings)
    assert [(c.field, c.reason) for c in res.corrections] == [
        ("target_label", "target_label_not_in_quote")
    ] * 3


def test_3a_recorded_shifted_date_is_kept():
    res = run(A3_ID, "dates")
    assert res.drops == []
    [f] = res.findings
    assert (f.kind, f.old_origin, f.old_value, f.new_value, f.delta) == (
        "shifted_date",
        "self",
        "2018-06-30",
        "2020-06-30",
        "731",
    )


def test_supersedes_keeps_the_strict_label_rule():
    res = run(A1_ID, "sla")
    assert [d.reason for d in res.drops] == ["target_label_not_in_quote"]
    assert res.drops[0].raw.new_segment_id == "p0108"
    assert res.corrections == []


def test_3a_clipped_supersession_cue_still_drops():
    res = run(A3_ID, "parties_or_sites")
    assert [d.reason for d in res.drops] == ["no_supersession_cue"]
    assert res.findings == []


def _price(new_value, new_quote="$41,496.00/month", seg="p0044"):
    return RawFinding(
        new_quote=new_quote,
        new_segment_id=seg,
        kind="price_change",
        old_doc=None,
        old_quote=None,
        old_segment_id=None,
        old_value=None,
        new_value=new_value,
        target_label=None,
        context_quote=None,
        context_segment_id=None,
    )


def test_value_with_units_must_still_equal_a_quote_token():
    res = run(A1_ID, "price", [_price("$41,497.00/month")])
    assert [d.reason for d in res.drops] == ["new_value_not_in_quote"]


def test_value_with_two_amounts_is_ambiguous_and_drops():
    res = run(A1_ID, "price", [_price("$41,496.00/month or $5.00")])
    assert [d.reason for d in res.drops] == ["new_value_not_in_quote"]


def test_plain_decimal_value_still_accepted():
    res = run(A1_ID, "price", [_price("41496.00")])
    assert [f.new_value for f in res.findings] == ["41496.00"]
