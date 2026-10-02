"""Task 8: deterministic verification of model-proposed items (field-level grounding)."""

from decimal import Decimal

import pytest

from og.extract.types import Evidence, FieldCorrection, RawItem, VerifyResult
from og.extract.verify import verify
from og.textdoc import Page, Section, Segment, TextDoc

# ---------------------------------------------------------------- document builder

LEASE = [
    (
        None,
        "Preamble",
        [
            (
                "parties",
                "This DATACENTER LEASE is made between DIGITAL 55 MIDDLESEX, LLC, as Landlord,"
                " and CONSTANT CONTACT, INC., as Tenant.",
            ),
            ("dated", "This Lease is dated January 1, 2011."),
        ],
    ),
    (None, "Table of Contents", [("toc1", "3.1 Base Rent"), ("toc1p", "7")]),
    (
        "2.1",
        "Term",
        [
            ("commence", "2.1 Term. \u201cCommencement Date\u201d means [\u25cf]."),
            ("delivery_def", "\u201cDelivery Date\u201d means March 1, 2011."),
            ("term_end", "The Term shall end ten years after the Commencement Date."),
            (
                "twodefs",
                "\u201cDelivery Date\u201d and \u201cRent Date\u201d each mean March 1, 2011.",
            ),
        ],
    ),
    (
        "3.1",
        "Base Rent",
        [
            ("rent", "3.1 Base Rent. Tenant shall pay Landlord Base Rent of $54,000.00 per month."),
            ("invoice", "Tenant shall pay each invoice within 30 days."),
            (
                "fees",
                "Tenant shall pay the Installation Fee of $12,500 and the Cross Connect Fee"
                " of $1,000.",
            ),
            (
                "addl",
                "Tenant shall pay Additional Rent within thirty (30) days after the"
                " Commencement Date.",
            ),
            ("notice", "Landlord shall give notice 5 days prior to the Delivery Date."),
            ("extend", "Tenant may extend the Term by 30 months."),
            ("restore", "Landlord shall restore power within 10 business days after an outage."),
            ("neg", "The rent adjustment is -$5 per kW."),
            ("paren", "The credit is ($5.00) per cross connect."),
            ("dollars", "Tenant shall pay a security deposit of 2,500 dollars."),
            ("deposit", "Tenant shall pay the deposit on or before March 1, 2011."),
            ("executed", "This amendment was executed on March 1, 2011 and Tenant shall pay."),
            (
                "conflict",
                "Tenant shall pay by March 1, 2011 within 30 days after Commencement Date.",
            ),
            ("frac3", "The cross connect fee is $5.123 per unit."),
            ("badgroup", "The setup charge is $1,00 per rack."),
            ("longdays", "Tenant shall vacate within 1000 days after the Commencement Date."),
            ("cents", "Tenant shall pay a late fee of $1,000.50 per occurrence."),
        ],
    ),
    (
        "3.2",
        "Power Charge",
        [
            (
                "redacted",
                "3.2 Power Charge. Tenant shall pay $[***] per kW and a setup fee of $2,500.",
            ),
            ("default", "Upon an Event of Default, Tenant shall pay all Rent then due."),
        ],
    ),
    (
        "3.3",
        "Insurance",
        [
            (
                "insure",
                "Tenant shall carry commercial general liability insurance. The required limit"
                " is [***].",
            ),
            ("guarantor", "Guarantor shall pay any amount Tenant fails to pay."),
        ],
    ),
]


def build(spec, page_starts=()):
    """spec: [(number, heading, [(key, line), ...]), ...] -> (TextDoc, {key: segment id})."""
    lines, keys, sec_of_line = [], [], []
    for si, (_, _, rows) in enumerate(spec):
        for key, line in rows:
            lines.append(line)
            keys.append(key)
            sec_of_line.append(si)
    text = "\n".join(lines)
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    sec_starts = []
    for si in range(len(spec)):
        sec_starts.append(offsets[sec_of_line.index(si)])
    sections = []
    for si, (number, heading, _) in enumerate(spec):
        end = sec_starts[si + 1] if si + 1 < len(spec) else len(text)
        sections.append(Section(f"s{si:04d}", number, heading, sec_starts[si], end, None))
    starts = [0] + [offsets[keys.index(k)] for k in page_starts]
    pages = [
        Page(i + 1, s, starts[i + 1] if i + 1 < len(starts) else len(text))
        for i, s in enumerate(starts)
    ]
    ids, segments = {}, []
    for i, (key, line, start) in enumerate(zip(keys, lines, offsets, strict=True)):
        sid = f"p{i + 1:04d}"
        ids[key] = sid
        page = max(p.page for p in pages if p.char_start <= start)
        segments.append(Segment(sid, f"s{sec_of_line[i]:04d}", page, start, start + len(line)))
    d = TextDoc("lease", "0" * 64, text, sections, pages, segments)
    d.validate()
    return d, ids


DOC, IDS = build(LEASE, page_starts=("redacted",))
LINE = {k: line for _, _, rows in LEASE for k, line in rows}


def raw(seg_key=None, span=None, **kw):
    """A RawItem with obligation defaults. seg_key picks the cited segment; span defaults to it."""
    fields = dict(
        span_text=span if span is not None else LINE[seg_key],
        segment_id=IDS.get(seg_key, seg_key) if seg_key else "p0001",
        kind="obligation",
        type="payment",
        owed_by=None,
        owed_to=None,
        description=None,
        amount=None,
        currency=None,
        due_date=None,
        anchor_event=None,
        offset_days=None,
        trigger=None,
        status="active",
        name=None,
        date=None,
        role=None,
    )
    fields.update(kw)
    return RawItem(**fields)


def event(seg_key, name, date=None, span=None, status="active"):
    return raw(seg_key, span, kind="event", type=None, name=name, date=date, status=status)


def party(seg_key, name, role, span=None):
    return raw(seg_key, span, kind="party", type=None, name=name, role=role, status=None)


def run(*items):
    result = verify(DOC, list(items))
    assert isinstance(result, VerifyResult)
    return result


def only_obligation(result):
    assert len(result.obligations) == 1, (result.drops, result.obligations)
    return result.obligations[0]


def fields_corrected(result):
    return {c.field for c in result.corrections}


def has_correction(result, field, reason=None):
    return any(
        isinstance(c, FieldCorrection)
        and c.field == field
        and (reason is None or c.reason == reason)
        for c in result.corrections
    )


def drop_reasons(result):
    return [d.reason for d in result.drops]


# ---------------------------------------------------------------- rule 1: kind and fields


def test_obligation_requires_type():
    assert drop_reasons(run(raw("rent", type=None))) == ["missing_field:type"]


def test_obligation_type_must_be_known():
    assert drop_reasons(run(raw("rent", type="rent"))) == ["bad_enum:type"]


def test_event_requires_name():
    r = run(raw("delivery_def", kind="event", type=None, name=None))
    assert drop_reasons(r) == ["missing_field:name"]


def test_party_requires_role():
    assert drop_reasons(run(party("parties", "CONSTANT CONTACT, INC.", None))) == [
        "missing_field:role"
    ]


def test_party_role_must_be_known():
    assert drop_reasons(run(party("parties", "CONSTANT CONTACT, INC.", "owner"))) == [
        "bad_enum:role"
    ]


def test_unknown_kind_dropped():
    assert drop_reasons(run(raw("rent", kind="clause"))) == ["bad_enum:kind"]


def test_unknown_segment_dropped():
    r = run(raw(None, span=LINE["rent"], segment_id="p9999"))
    assert drop_reasons(r) == ["unknown_segment"]


# ---------------------------------------------------------------- rule 2: grounding


def test_exact_quote_grounds_with_full_evidence():
    ob = only_obligation(run(raw("rent")))
    ev = ob.evidence
    assert isinstance(ev, Evidence)
    assert ev.span_text == LINE["rent"]
    assert ev.span_text == DOC.text[ev.char_start : ev.char_end]
    assert (ev.segment_id, ev.section_id, ev.section_number) == (IDS["rent"], "s0003", "3.1")
    assert ev.page == 1


def test_evidence_page_comes_from_offsets():
    ob = only_obligation(run(raw("redacted", amount=2500)))
    assert ob.evidence.page == 2
    assert ob.evidence.section_number == "3.2"


def test_quote_not_in_text_dropped():
    r = run(raw("rent", span="Tenant shall pay Landlord a bonus."))
    assert drop_reasons(r) == ["not_found_in_section"]


def test_quote_from_other_section_not_grounded():
    r = run(raw("rent", span=LINE["guarantor"]))
    assert drop_reasons(r) == ["not_found_in_section"]
    assert r.obligations == []


def test_relocation_within_section_corrects_segment():
    r = run(raw("invoice", span=LINE["rent"]))
    ob = only_obligation(r)
    assert ob.evidence.segment_id == IDS["rent"]
    assert has_correction(r, "segment_id", "relocated")


def test_multi_segment_evidence_dropped():
    span = "per month.\nTenant shall pay each invoice"
    r = run(raw("rent", span=span))
    assert drop_reasons(r) == ["multi_segment_evidence"]


def test_toc_evidence_dropped():
    r = run(raw("toc1", type="payment"))
    assert drop_reasons(r) == ["toc_evidence"]


def test_quote_whitespace_variant_copies_source_slice():
    span = LINE["rent"].replace(" of ", "  of\n")
    ob = only_obligation(run(raw("rent", span=span)))
    assert ob.evidence.span_text == LINE["rent"]


# ---------------------------------------------------------------- rule 3: status


def test_active_status_without_markers():
    r = run(raw("rent"))
    assert only_obligation(r).status == "active"
    assert not has_correction(r, "status")


def test_redacted_quote_sets_status_redacted():
    ob = only_obligation(run(raw("redacted", status="redacted")))
    assert ob.status == "redacted"


def test_model_status_overridden_is_recorded():
    r = run(raw("rent", status="redacted"))
    assert only_obligation(r).status == "active"
    assert has_correction(r, "status", "model_status_overridden")


def test_model_active_on_redacted_quote_is_overridden():
    r = run(raw("redacted", status="active"))
    assert only_obligation(r).status == "redacted"
    assert has_correction(r, "status", "model_status_overridden")


def test_marker_outside_quote_flagged_status_unchanged():
    span = "Tenant shall carry commercial general liability insurance."
    r = run(raw("insure", span=span, type="insurance"))
    assert only_obligation(r).status == "active"
    assert has_correction(r, "status", "marker_in_segment_outside_quote")


def test_blank_event_date_nulled():
    r = run(event("commence", "Commencement Date", date="2026-01-01", status="active"))
    assert len(r.events) == 1
    ev = r.events[0]
    assert ev.status == "blank"
    assert ev.date is None
    assert "date" in fields_corrected(r)


def test_event_date_written_in_quote_kept():
    r = run(event("delivery_def", "Delivery Date", date="2011-03-01"))
    ev = r.events[0]
    assert (ev.name, ev.date, ev.status) == ("Delivery Date", "2011-03-01", "active")


def test_event_date_not_in_quote_nulled():
    r = run(event("delivery_def", "Delivery Date", date="2011-04-01"))
    assert r.events[0].date is None
    assert "date" in fields_corrected(r)


# ---------------------------------------------------------------- rules 4-5: amount, currency


def test_amount_with_dollar_evidence_kept():
    ob = only_obligation(run(raw("rent", amount=54000, currency="USD")))
    assert ob.amount == Decimal("54000")
    assert ob.currency == "USD"


def test_amount_must_match_exactly():
    r = run(raw("rent", amount=54000.004))
    assert only_obligation(r).amount is None
    assert has_correction(r, "amount", "amount_not_in_quote")


def test_amount_not_in_quote_nulled():
    r = run(raw("rent", amount=45000))
    assert only_obligation(r).amount is None
    assert has_correction(r, "amount", "amount_not_in_quote")


def test_day_count_is_not_an_amount():
    r = run(raw("invoice", amount=30))
    assert only_obligation(r).amount is None
    assert has_correction(r, "amount", "amount_not_in_quote")


def test_negative_dollar_amount_kept_with_sign():
    ob = only_obligation(run(raw("neg", amount=-5)))
    assert ob.amount == Decimal("-5")


def test_negative_dollar_amount_sign_mismatch_nulled():
    r = run(raw("neg", amount=5))
    assert only_obligation(r).amount is None
    assert has_correction(r, "amount", "amount_not_in_quote")


def test_parenthesized_amount_is_negative():
    ob = only_obligation(run(raw("paren", amount=-5)))
    assert ob.amount == Decimal("-5")


def test_amount_written_as_dollars_kept():
    ob = only_obligation(run(raw("dollars", amount=2500)))
    assert ob.amount == Decimal("2500")
    assert ob.currency == "USD"


def test_redacted_clause_keeps_separately_evidenced_amount():
    ob = only_obligation(run(raw("redacted", amount=2500, status="redacted")))
    assert ob.status == "redacted"
    assert ob.amount == Decimal("2500")


def test_redacted_clause_guessed_amount_nulled():
    r = run(raw("redacted", amount=1200, status="redacted"))
    assert only_obligation(r).amount is None
    assert has_correction(r, "amount", "amount_not_in_quote")


def test_two_payments_sharing_a_paragraph_both_kept():
    r = run(raw("fees", amount=12500), raw("fees", amount=1000))
    assert sorted(ob.amount for ob in r.obligations) == [Decimal("1000"), Decimal("12500")]


def test_currency_without_amount_is_null():
    r = run(raw("invoice", currency="USD"))
    assert only_obligation(r).currency is None
    assert "currency" in fields_corrected(r)


def test_currency_follows_evidence_not_model():
    r = run(raw("rent", amount=54000, currency="EUR"))
    assert only_obligation(r).currency == "USD"
    assert "currency" in fields_corrected(r)


def test_currency_null_when_amount_nulled():
    r = run(raw("rent", amount=45000, currency="USD"))
    assert only_obligation(r).currency is None


# ---------------------------------------------------------------- rules 6-7: offset, anchor


def test_calendar_days_after_named_anchor_kept():
    ob = only_obligation(run(raw("addl", offset_days=30, anchor_event="Commencement Date")))
    assert (ob.offset_days, ob.anchor_event) == (30, "Commencement Date")


def test_days_prior_to_stored_negative():
    ob = only_obligation(run(raw("notice", offset_days=-5, anchor_event="Delivery Date")))
    assert (ob.offset_days, ob.anchor_event) == (-5, "Delivery Date")


def test_days_prior_to_with_positive_model_value_nulled():
    r = run(raw("notice", offset_days=5, anchor_event="Delivery Date"))
    ob = only_obligation(r)
    assert (ob.offset_days, ob.anchor_event) == (None, None)
    assert "offset_days" in fields_corrected(r)


def test_days_without_direction_word_nulled():
    r = run(raw("invoice", offset_days=30))
    assert only_obligation(r).offset_days is None
    assert "offset_days" in fields_corrected(r)


def test_months_are_not_days():
    r = run(raw("extend", type="termination_right", offset_days=30))
    assert only_obligation(r).offset_days is None


def test_business_days_are_not_converted():
    r = run(raw("restore", type="sla", offset_days=10))
    assert only_obligation(r).offset_days is None
    assert "offset_days" in fields_corrected(r)


def test_anchor_not_named_in_quote_nulls_the_pair():
    r = run(raw("addl", offset_days=30, anchor_event="Delivery Date"))
    ob = only_obligation(r)
    assert ob.anchor_event is None
    assert ob.offset_days is None
    assert "anchor_event" in fields_corrected(r)


def test_anchor_without_offset_is_null():
    r = run(raw("term_end", type="other", anchor_event="Commencement Date"))
    ob = only_obligation(r)
    assert (ob.offset_days, ob.anchor_event) == (None, None)
    assert "anchor_event" in fields_corrected(r)


def test_anchor_match_ignores_case_and_spacing():
    ob = only_obligation(run(raw("addl", offset_days=30, anchor_event="commencement  date")))
    assert ob.offset_days == 30
    assert ob.anchor_event is not None


# ---------------------------------------------------------------- rule 8: due_date


def test_due_date_with_cue_kept():
    ob = only_obligation(run(raw("deposit", due_date="2011-03-01")))
    assert ob.due_date == "2011-03-01"


def test_execution_date_is_not_a_due_date():
    r = run(raw("executed", due_date="2011-03-01"))
    assert only_obligation(r).due_date is None
    assert "due_date" in fields_corrected(r)


def test_due_date_not_in_quote_nulled():
    r = run(raw("deposit", due_date="2011-03-02"))
    assert only_obligation(r).due_date is None


@pytest.mark.parametrize(
    "written",
    ["January 5, 2026", "Jan. 5, 2026", "5 January 2026", "1/5/2026", "2026-01-05"],
)
def test_due_date_written_forms(written):
    line = f"Tenant shall pay the fee by {written}."
    d, ids = build([("4.1", "Fees", [("fee", line)])])
    item = raw(None, span=line, segment_id=ids["fee"], due_date="2026-01-05")
    ob = verify(d, [item]).obligations[0]
    assert ob.due_date == "2026-01-05"


def test_due_date_wrong_day_nulled():
    line = "Tenant shall pay the fee by January 6, 2026."
    d, ids = build([("4.1", "Fees", [("fee", line)])])
    item = raw(None, span=line, segment_id=ids["fee"], due_date="2026-01-05")
    assert verify(d, [item]).obligations[0].due_date is None


# ---------------------------------------------------------------- rules 9-10: trigger, description


def test_trigger_verbatim_kept_as_source_text():
    ob = only_obligation(run(raw("default", trigger="Upon an  Event of Default")))
    assert ob.trigger == "Upon an Event of Default"


def test_trigger_paraphrase_nulled():
    r = run(raw("default", trigger="upon default"))
    assert only_obligation(r).trigger is None
    assert "trigger" in fields_corrected(r)


def test_trigger_case_must_match():
    assert only_obligation(run(raw("default", trigger="upon an event of default"))).trigger is None


def test_description_is_the_quote_not_the_paraphrase():
    ob = only_obligation(run(raw("rent", description="Tenant pays monthly base rent.")))
    assert ob.description == LINE["rent"] == ob.evidence.span_text


def test_description_with_numbers_from_quote_is_still_the_quote():
    ob = only_obligation(run(raw("rent", description="Tenant pays $54,000.00 each month.")))
    assert ob.description == LINE["rent"] == ob.evidence.span_text


def test_nulled_amount_still_in_description_replaced_by_quote():
    r = run(raw("rent", amount=45000, description="Tenant pays $45,000 each month."))
    ob = only_obligation(r)
    assert ob.amount is None
    assert ob.description == LINE["rent"]


def test_waiver_paraphrase_never_stored():
    ob = only_obligation(run(raw("rent", description="Landlord waives all rent forever.")))
    assert ob.description == ob.evidence.span_text == LINE["rent"]
    assert "waives" not in ob.description


def test_missing_description_falls_back_to_quote():
    ob = only_obligation(run(raw("rent", description=None)))
    assert ob.description == LINE["rent"]


# ---------------------------------------------------------------- rule 11: owed_by / owed_to


def test_role_word_in_agreement_kept():
    ob = only_obligation(run(raw("rent", owed_by="Tenant", owed_to="Landlord")))
    assert (ob.owed_by, ob.owed_to) == ("Tenant", "Landlord")


def test_party_name_in_agreement_kept():
    ob = only_obligation(run(raw("rent", owed_by="CONSTANT CONTACT, INC.")))
    assert ob.owed_by == "CONSTANT CONTACT, INC."


def test_unknown_party_name_nulled():
    r = run(raw("rent", owed_by="Acme Holdings"))
    assert only_obligation(r).owed_by is None
    assert "owed_by" in fields_corrected(r)


def test_role_word_absent_from_agreement_nulled():
    r = run(raw("rent", owed_to="Lender"))
    assert only_obligation(r).owed_to is None
    assert "owed_to" in fields_corrected(r)


def test_suffix_variant_is_a_different_party():
    r = run(raw("rent", owed_to="DIGITAL 55 MIDDLESEX, INC."))
    assert only_obligation(r).owed_to is None


# ---------------------------------------------------------------- rule 12: parties


def test_two_parties_in_one_sentence_both_kept():
    r = run(
        party("parties", "DIGITAL 55 MIDDLESEX, LLC", "landlord"),
        party("parties", "CONSTANT CONTACT, INC.", "tenant"),
    )
    assert sorted((p.name, p.role) for p in r.parties) == [
        ("CONSTANT CONTACT, INC.", "tenant"),
        ("DIGITAL 55 MIDDLESEX, LLC", "landlord"),
    ]
    assert all(p.evidence.span_text == LINE["parties"] for p in r.parties)


def test_party_suffix_variant_dropped():
    r = run(party("parties", "DIGITAL 55 MIDDLESEX, INC.", "landlord"))
    assert r.parties == []
    assert len(r.drops) == 1


def test_party_without_role_word_in_quote_dropped():
    r = run(
        party("parties", "DIGITAL 55 MIDDLESEX, LLC", "landlord", span="DIGITAL 55 MIDDLESEX, LLC")
    )
    assert r.parties == []
    assert len(r.drops) == 1


def test_party_role_word_must_match_role():
    r = run(party("parties", "DIGITAL 55 MIDDLESEX, LLC", "guarantor"))
    assert r.parties == []


# ---------------------------------------------------------------- rule 13: duplicates


def test_identical_payloads_collapse():
    r = run(raw("rent", amount=54000), raw("rent", amount=54000))
    assert len(r.obligations) == 1


def test_same_quote_different_type_kept():
    r = run(raw("rent", type="payment"), raw("rent", type="other"))
    assert len(r.obligations) == 2


# ---------------------------------------------------------------- review focus and invariants


def test_review_focus_fabricated_event_date_on_blank():
    r = run(event("commence", "Commencement Date", date="2026-01-01"))
    assert r.events[0].status == "blank" and r.events[0].date is None


def test_kinds_are_routed_to_their_lists():
    r = run(
        raw("rent", amount=54000),
        event("delivery_def", "Delivery Date", date="2011-03-01"),
        party("parties", "CONSTANT CONTACT, INC.", "tenant"),
    )
    assert (len(r.obligations), len(r.events), len(r.parties), len(r.drops)) == (1, 1, 1, 0)


def test_raw_values_never_leak_into_verified_fields():
    r = run(
        raw(
            "invoice",
            amount=30,
            currency="USD",
            due_date="2026-01-01",
            offset_days=30,
            anchor_event="Commencement Date",
            trigger="if late",
            owed_by="Nobody Inc.",
        )
    )
    ob = only_obligation(r)
    assert (ob.amount, ob.currency, ob.due_date, ob.offset_days, ob.anchor_event) == (
        None,
        None,
        None,
        None,
        None,
    )
    assert ob.trigger is None and ob.owed_by is None


def test_every_evidence_is_the_doc_slice():
    items = [raw(k) for k in LINE if k not in ("toc1", "toc1p")]
    items += [raw(k, span=LINE[k][: max(8, len(LINE[k]) // 2)].rstrip()) for k in IDS]
    r = verify(DOC, items)
    evidences = [x.evidence for x in (*r.obligations, *r.events, *r.parties)]
    assert evidences
    for ev in evidences:
        assert ev.span_text == DOC.text[ev.char_start : ev.char_end]
        seg = DOC.segment(ev.segment_id)
        assert seg.char_start <= ev.char_start < ev.char_end <= seg.char_end
        assert DOC.section_for(ev.char_start).heading != "Table of Contents"


def test_verify_is_deterministic():
    items = [raw("rent", amount=54000), raw("fees", amount=12500), raw("notice", offset_days=-5)]
    assert verify(DOC, items) == verify(DOC, items)


# ---------------------------------------------------------------- rev 2.2 (Astra wave-2 round 2)


def test_r2_2_swapped_event_name_dropped():
    r = run(event("delivery_def", "Commencement Date", date="2011-03-01"))
    assert r.events == []
    assert drop_reasons(r) == ["event_name_not_in_quote"]


def test_r2_2_event_name_as_quoted_term_kept_with_its_date():
    r = run(event("delivery_def", "Delivery Date", date="2011-03-01"))
    assert [(e.name, e.date) for e in r.events] == [("Delivery Date", "2011-03-01")]
    assert "\u201cDelivery Date\u201d" in r.events[0].evidence.span_text


def test_r2_2_date_not_bound_when_another_quoted_term_intervenes():
    r = run(event("twodefs", "Delivery Date", date="2011-03-01"))
    assert len(r.events) == 1 and r.events[0].date is None
    assert has_correction(r, "date", "date_not_bound_to_event")


def test_r2_2_date_bound_to_the_nearest_preceding_name():
    r = run(event("twodefs", "Rent Date", date="2011-03-01"))
    assert [(e.name, e.date) for e in r.events] == [("Rent Date", "2011-03-01")]


def test_r2_3_description_never_carries_model_prose():
    items = [
        raw("rent", description="Landlord waives all rent forever."),
        raw("fees", amount=12500, description="Fees are waived."),
    ]
    for ob in run(*items).obligations:
        assert ob.description == ob.evidence.span_text


def test_r2_4_swapped_roles_dropped():
    r = run(
        party("parties", "DIGITAL 55 MIDDLESEX, LLC", "tenant"),
        party("parties", "CONSTANT CONTACT, INC.", "landlord"),
    )
    assert r.parties == []
    assert drop_reasons(r) == ["role_not_bound_to_name", "role_not_bound_to_name"]


def test_r2_4_correct_roles_kept_beside_swapped():
    r = run(
        party("parties", "DIGITAL 55 MIDDLESEX, LLC", "landlord"),
        party("parties", "CONSTANT CONTACT, INC.", "landlord"),
    )
    assert [(p.name, p.role) for p in r.parties] == [("DIGITAL 55 MIDDLESEX, LLC", "landlord")]
    assert drop_reasons(r) == ["role_not_bound_to_name"]


def test_r2_5_deadline_conflict_keeps_due_date():
    r = run(
        raw("conflict", due_date="2011-03-01", offset_days=30, anchor_event="Commencement Date")
    )
    ob = only_obligation(r)
    assert ob.due_date == "2011-03-01"
    assert (ob.offset_days, ob.anchor_event) == (None, None)
    assert has_correction(r, "offset_days", "deadline_conflict")


def test_r2_5_offset_alone_still_kept_on_conflict_line():
    ob = only_obligation(run(raw("conflict", offset_days=30, anchor_event="Commencement Date")))
    assert (ob.offset_days, ob.anchor_event) == (30, "Commencement Date")


def test_r2_6_extra_decimal_digit_is_not_an_amount():
    r = run(raw("frac3", amount=5.12))
    assert only_obligation(r).amount is None
    assert has_correction(r, "amount", "amount_not_in_quote")


@pytest.mark.parametrize("amount", [1, 100, 1.0])
def test_r2_6_malformed_grouping_supports_nothing(amount):
    assert only_obligation(run(raw("badgroup", amount=amount))).amount is None


@pytest.mark.parametrize("offset", [0, 100, 1000])
def test_r2_6_day_count_suffix_is_not_an_offset(offset):
    r = run(raw("longdays", offset_days=offset, anchor_event="Commencement Date"))
    ob = only_obligation(r)
    assert (ob.offset_days, ob.anchor_event) == (None, None)


def test_r2_6_complete_money_token_with_cents_kept():
    ob = only_obligation(run(raw("cents", amount=1000.50)))
    assert ob.amount == Decimal("1000.50")
    assert ob.currency == "USD"


# --- Rev 2.3 (Astra wave-2 round 3): bound dates and bound roles -------------------------

R3 = [
    (
        None,
        "Preamble",
        [
            ("between", "This lease is between Landlord Alpha LLC and Tenant Beta Inc."),
            ("between_as", "This lease is between Alpha LLC and Beta Inc., as Tenant."),
            (
                "paren",
                "DIGITAL 55 MIDDLESEX, LLC, a Delaware limited liability company"
                " (“Landlord”), and CONSTANT CONTACT, INC., a Delaware corporation"
                " (“Tenant”).",
            ),
        ],
    ),
    (
        "1",
        "Dates",
        [
            (
                "two_dates",
                "“Commencement Date” means January 1, 2011. Rent is payable March 1, 2011.",
            ),
            ("abbrev", "“Delivery Date” means Jan. 5, 2026."),
        ],
    ),
]
R3_DOC, R3_IDS = build(R3)
R3_LINE = {k: line for _, _, rows in R3 for k, line in rows}


def r3(seg_key, **kw):
    return raw(span=R3_LINE[seg_key], segment_id=R3_IDS[seg_key], **kw)


def r3_run(*items):
    return verify(R3_DOC, list(items))


def r3_event(seg_key, name, date):
    return r3(seg_key, kind="event", type=None, name=name, date=date, status="active")


def r3_party(seg_key, name, role):
    return r3(seg_key, kind="party", type=None, name=name, role=role, status=None)


def test_r3_event_date_from_a_later_sentence_is_not_bound():
    res = r3_run(r3_event("two_dates", "Commencement Date", "2011-03-01"))
    assert len(res.events) == 1
    assert res.events[0].date is None
    assert any(c.field == "date" and c.reason == "date_not_bound_to_event" for c in res.corrections)


def test_r3_event_date_in_the_defining_sentence_is_kept():
    res = r3_run(r3_event("two_dates", "Commencement Date", "2011-01-01"))
    assert [e.date for e in res.events] == ["2011-01-01"]


def test_r3_month_abbreviation_is_not_a_sentence_boundary():
    res = r3_run(r3_event("abbrev", "Delivery Date", "2026-01-05"))
    assert [e.date for e in res.events] == ["2026-01-05"]


def test_r3_role_before_name_binds_and_next_party_role_does_not():
    res = r3_run(
        r3_party("between", "Alpha LLC", "tenant"),
        r3_party("between", "Alpha LLC", "landlord"),
        r3_party("between", "Beta Inc.", "tenant"),
    )
    assert sorted((p.name, p.role) for p in res.parties) == [
        ("Alpha LLC", "landlord"),
        ("Beta Inc.", "tenant"),
    ]
    assert "role_not_bound_to_name" in [d.reason for d in res.drops]


def test_r3_and_is_a_party_boundary():
    res = r3_run(
        r3_party("between_as", "Alpha LLC", "tenant"),
        r3_party("between_as", "Beta Inc.", "tenant"),
    )
    assert [(p.name, p.role) for p in res.parties] == [("Beta Inc.", "tenant")]
    assert [d.reason for d in res.drops] == ["role_not_bound_to_name"]


def test_r3_parenthetical_roles_bind_to_their_own_names():
    res = r3_run(
        r3_party("paren", "DIGITAL 55 MIDDLESEX, LLC", "landlord"),
        r3_party("paren", "CONSTANT CONTACT, INC.", "tenant"),
        r3_party("paren", "DIGITAL 55 MIDDLESEX, LLC", "tenant"),
        r3_party("paren", "CONSTANT CONTACT, INC.", "landlord"),
    )
    assert sorted((p.name, p.role) for p in res.parties) == [
        ("CONSTANT CONTACT, INC.", "tenant"),
        ("DIGITAL 55 MIDDLESEX, LLC", "landlord"),
    ]
    assert [d.reason for d in res.drops] == ["role_not_bound_to_name"] * 2


# --- Rev 2.4 (Astra wave-2 round 4): declaration grammar for event dates and party roles --

R4 = [
    (
        None,
        "Preamble",
        [
            (
                "designate",
                "Landlord and Tenant designate Alpha LLC as Landlord.",
            ),
            (
                "inside_name",
                "Landlord Holdings LLC, as Tenant, leases space from Alpha LLC, as Landlord.",
            ),
            ("crossing", "Alpha LLC leases space to Beta Inc., as Tenant."),
        ],
    ),
    (
        "1",
        "Dates",
        [
            (
                "relative",
                "“Commencement Date” means the date that is 30 days after March 1, 2011.",
            ),
            (
                "negated",
                "“Commencement Date” is not March 1, 2011; it is April 1, 2011.",
            ),
            (
                "later_of",
                "“Commencement Date” means the later of January 1, 2011 and March 1, 2011.",
            ),
            ("qualified", "“Delivery Date” means March 1, 2011, subject to Force Majeure."),
            ("shall_be", "The Expiration Date shall be December 31, 2020."),
        ],
    ),
]
R4_DOC, R4_IDS = build(R4)
R4_LINE = {k: line for _, _, rows in R4 for k, line in rows}


def r4(seg_key, **kw):
    return raw(span=R4_LINE[seg_key], segment_id=R4_IDS[seg_key], **kw)


def r4_event(seg_key, name, date):
    return r4(seg_key, kind="event", type=None, name=name, date=date, status="active")


def r4_party(seg_key, name, role):
    return r4(seg_key, kind="party", type=None, name=name, role=role, status=None)


@pytest.mark.parametrize(
    "seg_key,date",
    [
        ("relative", "2011-03-01"),
        ("negated", "2011-03-01"),
        ("negated", "2011-04-01"),
        ("later_of", "2011-01-01"),
        ("later_of", "2011-03-01"),
        ("qualified", "2011-03-01"),
    ],
)
def test_r4_non_literal_event_dates_are_null(seg_key, date):
    name = "Delivery Date" if seg_key == "qualified" else "Commencement Date"
    res = verify(R4_DOC, [r4_event(seg_key, name, date)])
    assert [e.date for e in res.events] == [None]
    assert any(c.field == "date" and c.reason == "date_not_bound_to_event" for c in res.corrections)


def test_r4_unquoted_name_with_shall_be_is_a_declaration():
    res = verify(R4_DOC, [r4_event("shall_be", "Expiration Date", "2020-12-31")])
    assert [e.date for e in res.events] == ["2020-12-31"]


def test_r4_explicit_as_role_after_earlier_conjunction_binds():
    res = verify(R4_DOC, [r4_party("designate", "Alpha LLC", "landlord")])
    assert [(p.name, p.role) for p in res.parties] == [("Alpha LLC", "landlord")]


def test_r4_role_word_inside_a_company_name_is_not_a_role_prefix():
    res = verify(
        R4_DOC,
        [
            r4_party("inside_name", "Holdings LLC", "landlord"),
            r4_party("inside_name", "Landlord Holdings LLC", "tenant"),
            r4_party("inside_name", "Alpha LLC", "landlord"),
        ],
    )
    assert sorted((p.name, p.role) for p in res.parties) == [
        ("Alpha LLC", "landlord"),
        ("Landlord Holdings LLC", "tenant"),
    ]
    assert [d.reason for d in res.drops] == ["role_not_bound_to_name"]


def test_r4_role_of_another_entity_is_not_bound_across_a_verb_phrase():
    res = verify(
        R4_DOC,
        [
            r4_party("crossing", "Alpha LLC", "tenant"),
            r4_party("crossing", "Beta Inc.", "tenant"),
        ],
    )
    assert [(p.name, p.role) for p in res.parties] == [("Beta Inc.", "tenant")]
    assert [d.reason for d in res.drops] == ["role_not_bound_to_name"]


# --- Rev 2.5 (Astra wave-2 round 5): source-sentence context, whole-name fields, finite descriptors

R5 = [
    (
        None,
        "Preamble",
        [
            ("silver", "Silver Cloud Holdings LLC, as Tenant."),
            ("noncorp", "Alpha LLC, a non-tenant company appointing Beta Inc. as Tenant."),
            ("not_designate", "The agreement does not designate Alpha LLC as Tenant."),
            ("xalpha", "XAlpha LLC, as Tenant."),
            ("delaware", "Gamma LLC, a Delaware limited liability company, as Landlord."),
        ],
    ),
    (
        "1",
        "Dates",
        [
            ("false_that", "It is false that “Commencement Date” is March 1, 2011."),
            (
                "provided",
                "“Commencement Date” means March 1, 2011; provided that Landlord first"
                " delivers possession.",
            ),
            (
                "unless",
                "“Commencement Date” means March 1, 2011 unless the premises are unavailable.",
            ),
            ("plain", "“Delivery Date” means March 1, 2011."),
        ],
    ),
]
R5_DOC, R5_IDS = build(R5)
R5_LINE = {k: line for _, _, rows in R5 for k, line in rows}


def r5(seg_key, span=None, **kw):
    return raw(
        span=span if span is not None else R5_LINE[seg_key], segment_id=R5_IDS[seg_key], **kw
    )


def r5_event(seg_key, name, date, span=None):
    return r5(seg_key, span, kind="event", type=None, name=name, date=date, status="active")


def r5_party(seg_key, name, role, span=None):
    return r5(seg_key, span, kind="party", type=None, name=name, role=role, status=None)


@pytest.mark.parametrize(
    "seg_key,span",
    [
        ("false_that", None),
        ("false_that", "“Commencement Date” is March 1, 2011."),
        ("provided", None),
        ("provided", "“Commencement Date” means March 1, 2011;"),
        ("unless", None),
    ],
)
def test_r5_governed_event_declarations_leave_the_date_null(seg_key, span):
    res = verify(R5_DOC, [r5_event(seg_key, "Commencement Date", "2011-03-01", span)])
    assert [e.date for e in res.events] == [None]
    assert any(c.field == "date" and c.reason == "date_not_bound_to_event" for c in res.corrections)


def test_r5_plain_declaration_still_binds():
    res = verify(R5_DOC, [r5_event("plain", "Delivery Date", "2011-03-01")])
    assert [e.date for e in res.events] == ["2011-03-01"]


@pytest.mark.parametrize(
    "seg_key,name,role,span",
    [
        ("silver", "Holdings LLC", "tenant", None),
        ("noncorp", "Alpha LLC", "tenant", None),
        ("not_designate", "Alpha LLC", "tenant", None),
        ("not_designate", "Alpha LLC", "tenant", "designate Alpha LLC as Tenant."),
        ("xalpha", "Alpha LLC", "tenant", None),
    ],
)
def test_r5_unsupported_party_declarations_bind_nothing(seg_key, name, role, span):
    res = verify(R5_DOC, [r5_party(seg_key, name, role, span)])
    assert res.parties == []
    assert [d.reason for d in res.drops] == ["role_not_bound_to_name"]


@pytest.mark.parametrize(
    "seg_key,name,role",
    [
        ("silver", "Silver Cloud Holdings LLC", "tenant"),
        ("delaware", "Gamma LLC", "landlord"),
    ],
)
def test_r5_whole_name_and_finite_descriptor_bind(seg_key, name, role):
    res = verify(R5_DOC, [r5_party(seg_key, name, role)])
    assert [(p.name, p.role) for p in res.parties] == [(name, role)]
