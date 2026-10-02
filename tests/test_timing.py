"""Wave 5 Task 40: og.timing on SYNTHETIC documents (plan rev 2 / rev 2.1).

One test per grammar construction, relation and sign, unresolved reason and its
precedence, number form, and the resolve()/defined_dates() rules. Every quote below is
synthetic; the real-corpus behaviour is pinned in tests/test_timing_corpus.py.

Conventions pinned here (B5):
- an offsetless construction ("prior to", "on or before", "no later than", "upon", "on")
  has offset_days None or 0; resolve() treats a missing offset as 0;
- a trigger span starts at the construction and lies inside the obligation quote;
- defined names are compared after whitespace normalization (NBSP counts as a space);
- only lt / lte / eq relations become scheduled deadlines; gt / gte never do.
"""

import re

import pytest
from extract_fakes import build_doc

from og.extract.types import Evidence
from og.timing import (
    OFFSET_UNITS,
    RELATIONS,
    TIMING_KINDS,
    TRIGGER_KINDS,
    UNRESOLVED_REASONS,
    CitedAnchor,
    ParsedTiming,
    Timing,
    defined_dates,
    parse,
    resolve,
)

NBSP = " "


def norm(s):
    return re.sub(r"\s+", " ", s.replace(NBSP, " ")).strip()


def quote(text, lines=None):
    """A one-section doc whose segment p0001 is `text`; returns (doc, evidence)."""
    doc = build_doc([("1", "Rent", [text, *(lines or [])])])
    seg = doc.segment("p0001")
    ev = Evidence("p0001", "s0000", "1", 1, seg.char_start, seg.char_end, text)
    assert doc.text[ev.char_start : ev.char_end] == text
    return doc, ev


def p(text):
    doc, ev = quote(text)
    out = parse(doc, ev)
    assert isinstance(out, ParsedTiming)
    if out.trigger is not None:
        t = out.trigger
        assert doc.text[t.char_start : t.char_end] == t.span_text
        assert ev.char_start <= t.char_start < t.char_end <= ev.char_end
    if out.relation is not None:
        assert out.relation in RELATIONS
    if out.offset_unit is not None:
        assert out.offset_unit in OFFSET_UNITS
    if out.trigger_kind is not None:
        assert out.trigger_kind in TRIGGER_KINDS
    if out.reason is not None:
        assert out.reason in UNRESOLVED_REASONS
    return out


def offset0(parsed):
    return parsed.offset_days in (None, 0)


# --- constructions, relations, signs --------------------------------------------------


@pytest.mark.parametrize("connector", ["after", "following", "of", "from"])
def test_within_after_is_an_inclusive_upper_bound(connector):
    out = p(f"Tenant shall pay within 30 days {connector} receipt of an invoice therefor.")
    assert (out.construction, out.relation, out.offset_days, out.offset_unit) == (
        "within_after",
        "lte",
        30,
        "calendar",
    )
    assert out.trigger.span_text.startswith("within 30 days")
    assert out.trigger_kind == "invoice"
    assert out.anchor_name is None and out.reason is None


def test_no_later_than_n_days_following():
    out = p("Tenant shall pay no later than thirty (30) days following receipt of an invoice.")
    assert (out.construction, out.relation, out.offset_days, out.offset_unit) == (
        "no_later_than_after",
        "lte",
        30,
        "calendar",
    )
    assert out.trigger_kind == "invoice"


def test_count_prior_to_is_a_negative_offset_upper_bound():
    out = p("Tenant shall deliver the plans at least ten (10) days prior to the Commencement Date.")
    assert (out.construction, out.relation, out.offset_days, out.offset_unit) == (
        "count_prior_to",
        "lte",
        -10,
        "calendar",
    )
    assert out.anchor_name == "Commencement Date"
    assert out.trigger_kind == "defined_event"


def test_on_or_before_is_inclusive():
    out = p("Landlord shall complete the installations on or before the Delivery Date.")
    assert (out.construction, out.relation) == ("on_or_before", "lte")
    assert offset0(out)
    assert out.anchor_name == "Delivery Date"


def test_on_or_prior_to_is_inclusive():
    out = p("Landlord shall complete the work on or prior to the Delivery Date.")
    assert (out.construction, out.relation) == ("on_or_before", "lte")


def test_bare_no_later_than_is_inclusive():
    out = p("Tenant agrees to surrender the Premises no later than the Amended Surrender Date")
    assert (out.construction, out.relation) == ("no_later_than", "lte")
    assert offset0(out)
    assert out.anchor_name == "Amended Surrender Date"


@pytest.mark.parametrize("word", ["prior to", "before"])
def test_prior_to_is_strict(word):
    out = p(f"Landlord shall cause the installation to be completed {word} the Commencement Date.")
    assert (out.construction, out.relation) == ("prior_to", "lt")
    assert offset0(out)
    assert out.anchor_name == "Commencement Date"
    assert out.trigger_kind == "defined_event"


def test_upon_is_event_relative_eq():
    out = p("Landlord shall indemnify and defend upon demand with counsel acceptable to Tenant.")
    assert (out.construction, out.relation, out.trigger_kind) == ("upon", "eq", "demand")
    assert out.trigger.span_text.startswith("upon demand")
    assert out.anchor_name is None


def test_immediately_upon():
    out = p("Tenant shall pay the Excess Rent immediately upon its receipt thereof.")
    assert (out.construction, out.relation) == ("upon", "eq")
    assert out.trigger.span_text.startswith("immediately upon")


def test_on_a_defined_event_is_eq():
    out = p("Tenant shall deliver the certificate on the Commencement Date.")
    assert (out.construction, out.relation, out.anchor_name) == (
        "on_defined",
        "eq",
        "Commencement Date",
    )


def test_after_without_within_is_a_lower_bound():
    out = p("Tenant shall notify Landlord promptly after making any changes to the Datacenter.")
    assert (out.construction, out.relation) == ("after", "gt")
    assert out.trigger.span_text.startswith("promptly after")


def test_longer_construction_wins_over_its_suffix():
    out = p("Tenant shall pay within 10 days after the Commencement Date.")
    assert out.construction == "within_after"
    assert out.anchor_name == "Commencement Date"


# --- number forms and whitespace --------------------------------------------------------


@pytest.mark.parametrize(
    "count,expected",
    [("30", 30), ("thirty (30)", 30), ("fifteen", 15), ("one hundred twenty (120)", 120)],
)
def test_number_forms(count, expected):
    out = p(f"Tenant shall pay within {count} days after receipt of an invoice.")
    assert out.offset_days == expected


def test_nbsp_inside_the_construction_is_whitespace():
    out = p(f"Tenant shall pay within ten (10){NBSP}days after receipt of an invoice.")
    assert (out.relation, out.offset_days, out.offset_unit) == ("lte", 10, "calendar")
    assert NBSP in out.trigger.span_text


# --- immediate binding and trigger kinds ---------------------------------------------------


def test_a_dated_event_elsewhere_in_the_quote_does_not_bind():
    out = p(
        "Tenant shall pay within 10 days after receipt of an invoice for amounts accrued "
        "as of the Effective Date."
    )
    assert out.anchor_name is None
    assert out.trigger_kind == "invoice"


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Tenant shall pay within 10 days after receipt of an invoice.", "invoice"),
        ("Tenant shall cure within 10 days after written notice from Landlord.", "notice"),
        ("Tenant shall pay the costs within 10 days after Landlord's demand.", "demand"),
        ("Guarantor shall pay within 10 days following an Event of Default.", "default"),
        ("Tenant shall pay within 10 days after substantial completion of the work.", "completion"),
        (
            "Tenant shall remove its equipment within 30 days after the expiration of the Term.",
            "term_end",
        ),
        ("Landlord shall complete the work prior to the Commencement Date.", "defined_event"),
        (
            "Tenant shall give notice within three days of its alleged first occurrence.",
            "other_event",
        ),
    ],
)
def test_trigger_kind_lexicon(text, kind):
    assert p(text).trigger_kind == kind


# --- unresolved reasons ------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,reason",
    [
        (
            "Guarantor shall give notice within [***] days after the occurrence thereof.",
            "redacted_offset",
        ),
        (
            "On or prior to the date that is [***] after the date hereof, Guarantor shall deliver "
            "a letter of credit.",
            "redacted_offset",
        ),
        (
            "If the Conditions have not occurred prior to the Outside Completion Date, "
            "Tenant shall have the right to terminate this Lease.",
            "conditional_or_compound",
        ),
        (
            "Tenant notifies Landlord prior to the earlier to occur of: (1) completion of the "
            "work; or (2) ten (10) days after the Outside Completion Date.",
            "conditional_or_compound",
        ),
        ("$5,000.00 per month for months 13-24 of the Term.", "recurring_schedule"),
        (
            "Tenant shall remedy the overage within one hundred twenty (120) hours after notice.",
            "unsupported_unit",
        ),
        (
            "Tenant shall replace the unit within twelve (12) months after the Commencement Date.",
            "unsupported_unit",
        ),
        (
            "Revenue will be credited to the monthly invoice in the month that Host receives the "
            "program revenue",
            "month_granularity",
        ),
        (
            "Landlord shall cure such delinquency within the time allowed pursuant to Section "
            "16.1.1 of this Lease.",
            "cross_reference",
        ),
        (
            "Tenant shall execute the memorandum within ten (10) business days after the Effective "
            "Date.",
            "business_days",
        ),
        (
            "Landlord shall resolve billing disputes within thirty (30) calendar days.",
            "anchor_not_found",
        ),
        ("Tenant shall promptly repair any damage caused by its contractors.", "anchor_not_found"),
    ],
)
def test_unresolved_reasons(text, reason):
    out = p(text)
    assert out.reason == reason


def test_business_days_keep_the_trigger_quoted():
    out = p("Tenant shall execute it within ten (10) business days after the Effective Date.")
    assert out.reason == "business_days"
    assert out.offset_unit == "business"
    assert out.trigger is not None and "Effective Date" in out.trigger.span_text


def test_redacted_offset_never_falls_back_to_zero():
    out = p("Guarantor shall give notice within [***] days after the occurrence thereof.")
    assert out.reason == "redacted_offset"
    assert out.offset_days is None


@pytest.mark.parametrize(
    "text,reason",
    [
        # redacted_offset beats conditional_or_compound
        (
            "If a Springing Event occurs, Guarantor shall give notice within [***] days after "
            "the occurrence thereof.",
            "redacted_offset",
        ),
        # conditional_or_compound beats recurring_schedule
        (
            "If the Commencement Date has not occurred prior to the Outside Date, Tenant shall pay "
            "$1,000 per month.",
            "conditional_or_compound",
        ),
        # recurring_schedule beats unsupported_unit
        (
            "Tenant shall pay $10.00 per month, and shall remedy any overage within 24 hours after "
            "notice.",
            "recurring_schedule",
        ),
        # unsupported_unit beats cross_reference
        (
            "Tenant shall cure within 120 hours after notice or as provided in Section 15.1.",
            "unsupported_unit",
        ),
        # cross_reference beats business_days
        (
            "Tenant shall cure within ten (10) business days as provided in Section 4.1.",
            "cross_reference",
        ),
    ],
)
def test_reason_precedence(text, reason):
    assert p(text).reason == reason


def test_a_condition_does_not_capture_a_deadline_on_the_stated_duty():
    out = p(
        "If Tenant's audit reveals a delinquency, Landlord shall pay the shortfall within 30 "
        "days after receipt of an invoice."
    )
    assert out.reason is None
    assert (out.relation, out.offset_days, out.trigger_kind) == ("lte", 30, "invoice")


def test_untimed_only_without_any_timing_cue():
    out = p(
        "Tenant shall maintain commercial general liability insurance with a reputable insurer."
    )
    assert (out.construction, out.relation, out.trigger, out.reason) == (None, None, None, None)


# --- resolve() ----------------------------------------------------------------------------


def anchor(name, date, event_id=1, agreement="d1"):
    return CitedAnchor(event_id, agreement, name, date, clause_ref_id=100 + event_id)


def r(text, anchors=(), legacy_due=None):
    doc, ev = quote(text)
    out = resolve(parse(doc, ev), list(anchors), legacy_due)
    assert isinstance(out, Timing) and out.kind in TIMING_KINDS
    assert (out.kind == "unresolved") == (out.reason is not None)
    if out.kind != "scheduled":
        assert out.bound_date is None
    return out


def test_strict_bound_is_scheduled_without_conversion():
    out = r(
        "Landlord shall complete the work prior to the Commencement Date.",
        [anchor("Commencement Date", "2011-01-01")],
    )
    assert (out.kind, out.relation, out.bound_date, out.anchor_event_id) == (
        "scheduled",
        "lt",
        "2011-01-01",
        1,
    )


def test_inclusive_bound_adds_the_signed_calendar_offset():
    out = r(
        "Tenant shall pay within 10 days after the Commencement Date.",
        [anchor("Commencement Date", "2011-01-25")],
    )
    assert (out.kind, out.relation, out.bound_date) == ("scheduled", "lte", "2011-02-04")
    out = r(
        "Tenant shall deliver it at least ten (10) days prior to the Commencement Date.",
        [anchor("Commencement Date", "2011-01-01")],
    )
    assert (out.kind, out.relation, out.bound_date) == ("scheduled", "lte", "2010-12-22")


def test_eq_on_a_dated_event_is_scheduled():
    out = r(
        "Tenant shall deliver the certificate on the Commencement Date.",
        [anchor("Commencement Date", "2014-04-01")],
    )
    assert (out.kind, out.relation, out.bound_date) == ("scheduled", "eq", "2014-04-01")


def test_name_matching_ignores_nbsp():
    out = r(
        "Landlord shall satisfy the conditions prior to the Target Commencement Date.",
        [anchor(f"Target{NBSP}Commencement{NBSP}Date", "2014-04-01")],
    )
    assert (out.kind, out.bound_date) == ("scheduled", "2014-04-01")


def test_lower_bound_is_never_scheduled():
    out = r(
        "Tenant shall notify Landlord promptly after the Commencement Date.",
        [anchor("Commencement Date", "2011-01-01")],
    )
    assert out.kind != "scheduled"


@pytest.mark.parametrize(
    "text,reason",
    [
        (
            "Tenant shall sign it within ten (10) business days after the Commencement Date.",
            "business_days",
        ),
        ("Tenant shall cure within 120 hours after the Commencement Date.", "unsupported_unit"),
        (
            "Tenant shall replace it within 12 months after the Commencement Date.",
            "unsupported_unit",
        ),
    ],
)
def test_non_calendar_units_are_never_scheduled(text, reason):
    out = r(text, [anchor("Commencement Date", "2011-01-01")])
    assert (out.kind, out.reason) == ("unresolved", reason)


def test_business_unit_without_a_parse_reason_is_still_not_scheduled():
    parsed = ParsedTiming(
        "within_after", "lte", 10, "business", None, "defined_event", "Commencement Date", None
    )
    out = resolve(parsed, [anchor("Commencement Date", "2011-01-01")])
    assert out.kind == "unresolved" and out.reason == "business_days"


def test_conflicting_anchor_dates_are_unresolved():
    out = r(
        "Landlord shall complete the work prior to the Commencement Date.",
        [
            anchor("Commencement Date", "2011-01-01", 1),
            anchor("Commencement Date", "2011-02-01", 2),
        ],
    )
    assert (out.kind, out.reason) == ("unresolved", "conflicting_dates")


def test_equal_duplicate_anchor_dates_still_schedule():
    out = r(
        "Landlord shall complete the work prior to the Commencement Date.",
        [
            anchor("Commencement Date", "2011-01-01", 1),
            anchor("Commencement Date", "2011-01-01", 2),
        ],
    )
    assert (out.kind, out.bound_date) == ("scheduled", "2011-01-01")


def test_disagreeing_legacy_due_date_is_unresolved():
    out = r(
        "Landlord shall complete the work prior to the Commencement Date.",
        [anchor("Commencement Date", "2011-01-01")],
        legacy_due="2011-03-01",
    )
    assert (out.kind, out.reason) == ("unresolved", "conflicting_dates")


def test_agreeing_legacy_due_date_keeps_the_schedule():
    out = r(
        "Landlord shall complete the work on or before the Commencement Date.",
        [anchor("Commencement Date", "2011-01-01")],
        legacy_due="2011-01-01",
    )
    assert (out.kind, out.bound_date) == ("scheduled", "2011-01-01")


def test_external_trigger_without_anchor_is_contingent():
    out = r(
        "Tenant shall pay within 30 days after receipt of an invoice.",
        [anchor("Commencement Date", "2011-01-01")],
    )
    assert (out.kind, out.trigger_kind, out.relation, out.offset_days) == (
        "contingent",
        "invoice",
        "lte",
        30,
    )
    assert out.trigger is not None and out.anchor_event_id is None


def test_defined_event_without_a_dated_anchor_is_unresolved():
    out = r("Landlord shall complete the work prior to the Commencement Date.", [])
    assert (out.kind, out.reason) == ("unresolved", "anchor_without_date")
    out = r(
        "Landlord shall complete the work prior to the Commencement Date.",
        [anchor("Commencement Date", None)],
    )
    assert (out.kind, out.reason) == ("unresolved", "anchor_without_date")


def test_parse_reason_carries_through_resolve():
    out = r("Guarantor shall give notice within [***] days after the occurrence thereof.")
    assert (out.kind, out.reason, out.offset_days) == ("unresolved", "redacted_offset", None)


def test_untimed_resolves_untimed():
    out = r("Tenant shall maintain commercial general liability insurance.")
    assert out.kind == "untimed"
    assert (out.trigger, out.relation, out.anchor_event_id) == (None, None, None)


# --- defined_dates() ----------------------------------------------------------------------


def dd(sections):
    doc = build_doc(sections)
    out = defined_dates(doc)
    for d in out:
        e = d.evidence
        assert doc.text[e.char_start : e.char_end] == e.span_text
        assert d.form in ("bli_row", "declaration")
    return doc, {norm(d.name): d for d in out}


def test_bli_label_and_value_in_one_segment():
    _, got = dd([("4", "Dates", ["(a) Effective Date: January 1, 2011"])])
    d = got["Effective Date"]
    assert (d.date, d.form) == ("2011-01-01", "bli_row")
    assert "January 1, 2011" in d.evidence.span_text and "Effective Date" in d.evidence.span_text


def test_bli_label_and_value_in_adjacent_segments_of_one_section():
    doc, got = dd(
        [
            (
                "4",
                "Dates",
                [
                    "(a) Effective Date:",
                    "January 1, 2011",
                    "(b) Commencement Date:",
                    f"March{NBSP}1, 2012",
                ],
            )
        ]
    )
    assert got["Effective Date"].date == "2011-01-01"
    c = got["Commencement Date"]
    assert c.date == "2012-03-01"
    assert c.evidence.char_start == doc.segment("p0003").char_start
    assert c.evidence.char_end <= doc.segment("p0004").char_end


def test_bli_label_with_nbsp():
    _, got = dd(
        [("4", "Dates", [f"(b){NBSP}Target{NBSP}Commencement{NBSP}Date:", "April 1, 2014."])]
    )
    assert got["Target Commencement Date"].date == "2014-04-01"


def test_value_not_adjacent_does_not_bind():
    _, got = dd(
        [
            (
                "4",
                "Dates",
                ["(c) Outside Completion Date:", "See the schedule below.", "May 31, 2014."],
            )
        ]
    )
    assert "Outside Completion Date" not in got


def test_value_in_another_section_does_not_bind():
    _, got = dd(
        [("4", "Dates", ["(e) Outside Completion Date:"]), ("5", "Term", ["May 31, 2014."])]
    )
    assert "Outside Completion Date" not in got


def test_toc_and_cross_reference_rows_do_not_bind():
    _, got = dd(
        [
            (
                "0",
                "Contents",
                [
                    "(a) Effective Date .......... 4",
                    "(b) Commencement Date: as defined in Section 2.1",
                    "(f) Rent Start Date: May 1, 2012",
                ],
            )
        ]
    )
    assert got == {}


def test_as_of_declaration():
    _, got = dd(
        [
            (
                "3",
                "Premises",
                ["As of June 1, 2012 (the “Expansion Date”), Suite 418A shall be deemed expanded."],
            )
        ]
    )
    d = got["Expansion Date"]
    assert (d.date, d.form) == ("2012-06-01", "declaration")


def test_expiring_declaration_binds_its_own_date_only():
    _, got = dd(
        [
            (
                "1",
                "Term",
                [
                    "The Term shall be extended, commencing July 1, 2018 and "
                    "expiring June 30, 2020 (the “Amended Surrender Date”)."
                ],
            )
        ]
    )
    d = got["Amended Surrender Date"]
    assert d.date == "2020-06-30"
    assert "2018" not in d.evidence.span_text
