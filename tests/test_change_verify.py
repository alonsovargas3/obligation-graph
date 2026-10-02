"""Task 17: deterministic change verify, one test per rule (synthetic chain).

Rules: plan rev 1 Task 17, rev 2 R1-R3 and R9, rev 2.1 R2-1 and R2-2. Real-text
regressions live in tests/test_change_regressions.py.
"""

import pytest
import yaml
from extract_fakes import build_doc

from og.change.types import ChainDoc, RawFinding
from og.change.verify import verify_findings
from og.eval.gold import textdoc_sha256

BASE = build_doc(
    [
        ("7.2", "Notices", ["Notices to Landlord shall be sent to 1 Main Street."]),  # p0001
        ("7.2.1", "Copies", ["Copies shall be sent to counsel."]),  # p0002
        ("7.20", "Records", ["Landlord shall keep records."]),  # p0003
        ("8.1", "Rent", ["Tenant shall pay rent of $1,000 per month."]),  # p0004
        ("9", "Term", ["The Term shall expire on June 30, 2018."]),  # p0005
        (None, "Exhibit B", ["EXHIBIT “B”", "DEPICTION OF THE CAGE"]),  # p0006-7
        (None, "Exhibit C", ["EXHIBIT “C”", "PATHWAY PLAN"]),  # p0008-9
        (None, "Exhibit D", ["EXHIBIT “D”", "GENERATOR PLAN"]),  # p0010-11
    ],
    doc_id="base",
)
CO_LINES = [
    "Section 7.2 of the Lease is hereby deleted in its entirety.",  # p0001
    "Exhibit “B” to the Lease is hereby replaced by Exhibit “B-1”.",  # p0002
    "Exhibit “C” to the Lease is hereby deleted.",  # p0003
    "Exhibit “D” to the Lease is hereby deleted.",  # p0004
    "Section 3.1 of 2A is hereby deleted.",  # p0005
    "Currently, the Term is scheduled to expire on June 30, 2018. "
    "The Term is hereby extended and shall expire on June 30, 2020.",  # p0006
    "Tenant shall pay rent of $1,250.00 per month.",  # p0007
    "Period: July 1, 2018 to June 30, 2019",  # p0008
    "Landlord shall maintain the cage.",  # p0009
    "Tenant shall pay rent monthly in advance.",  # p0010
    "The parking rider is hereby deleted.",  # p0011
]
CO = build_doc([(str(i + 1), f"H{i}", [line]) for i, line in enumerate(CO_LINES)], doc_id="co")
CHAIN = [ChainDoc("base", BASE, "base"), ChainDoc("co", CO, "change_order")]


@pytest.fixture
def aliases(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": "test",
                "chains": [
                    {
                        "base": "base",
                        "aliases": {"base": ["Lease", "Original Lease"], "a1": ["1A"]},
                        "unresolved": ["2A"],
                        "targets": [
                            {
                                "doc": "base",
                                "textdoc_sha256": textdoc_sha256(BASE),
                                "kind": "Exhibit",
                                "id": "B",
                                "first": "p0006",
                                "last": "p0007",
                            },
                            {
                                "doc": "base",
                                "textdoc_sha256": "0" * 64,  # pinned to other text: unusable
                                "kind": "Exhibit",
                                "id": "C",
                                "first": "p0008",
                                "last": "p0009",
                            },
                        ],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def co(seg):
    return CO.segment_text(seg)


def base(seg):
    return BASE.segment_text(seg)


def raw(**over):
    fields = dict(
        new_quote=co("p0001"),
        new_segment_id="p0001",
        kind="supersedes",
        old_doc=None,
        old_quote=None,
        old_segment_id=None,
        old_value=None,
        new_value=None,
        target_label=None,
        context_quote=None,
        context_segment_id=None,
    )
    fields.update(over)
    return RawFinding(**fields)


def old(seg, doc="base"):
    src = BASE if doc == "base" else CO
    return {"old_doc": doc, "old_quote": src.segment_text(seg), "old_segment_id": seg}


def run(aliases, *items, category="dates"):
    return verify_findings(CHAIN, category, list(items), aliases_path=aliases)


def one(aliases, item, category="dates"):
    res = run(aliases, item, category=category)
    assert res.drops == [], [d.reason for d in res.drops]
    assert len(res.findings) == 1
    return res.findings[0]


def dropped(aliases, item, category="dates"):
    res = run(aliases, item, category=category)
    assert res.findings == []
    assert len(res.drops) == 1
    d = res.drops[0]
    assert d.raw == item and d.category == category
    return d.reason


# ---------------------------------------------------------------- new side


def test_new_side_evidence_is_the_source_slice(aliases):
    f = one(aliases, raw(**old("p0001")))
    ev = f.new.evidence
    assert f.new.agreement_id == "co" and f.kind == "supersedes" and f.category == "dates"
    assert ev.segment_id == "p0001" and ev.section_number == "1" and ev.page == 1
    assert CO.text[ev.char_start : ev.char_end] == ev.span_text == co("p0001")


def test_whitespace_normalized_quote_grounds_to_source_text(aliases):
    quote = co("p0001").replace(" ", "  ")
    f = one(aliases, raw(new_quote=quote, **old("p0001")))
    assert f.new.evidence.span_text == co("p0001")


def test_unknown_new_segment(aliases):
    assert dropped(aliases, raw(new_segment_id="p0099", **old("p0001"))) == "unknown_segment"


def test_new_quote_not_in_cited_segment(aliases):
    item = raw(new_quote=co("p0002"), new_segment_id="p0001", **old("p0001"))
    assert dropped(aliases, item) == "not_found_in_section"


def test_unknown_kind(aliases):
    assert dropped(aliases, raw(kind="conflict", **old("p0001"))) == "unknown_kind"


# ---------------------------------------------------------------- old side


@pytest.mark.parametrize("doc", ["co", "zzz"])
def test_old_doc_must_be_an_earlier_chain_document(aliases, doc):
    item = raw(old_doc=doc, old_quote=co("p0001"), old_segment_id="p0001")
    assert dropped(aliases, item) == "old_doc_not_in_chain"


def test_old_segment_unknown(aliases):
    item = raw(old_doc="base", old_quote=base("p0001"), old_segment_id="p0099")
    assert dropped(aliases, item) == "unknown_segment"


def test_old_quote_not_in_old_segment(aliases):
    item = raw(old_doc="base", old_quote=base("p0002"), old_segment_id="p0001")
    assert dropped(aliases, item) == "not_found_in_section"


@pytest.mark.parametrize(
    "over",
    [
        {"old_doc": "base", "old_quote": None, "old_segment_id": "p0001"},
        {"old_doc": "base", "old_quote": "Notices", "old_segment_id": None},
        {"old_doc": None, "old_quote": "Notices", "old_segment_id": None},
        {"old_doc": None, "old_quote": None, "old_segment_id": "p0001"},
    ],
)
def test_old_side_must_be_complete_or_absent(aliases, over):
    item = raw(new_quote=co("p0011"), new_segment_id="p0011", target_label="parking rider", **over)
    assert dropped(aliases, item) == "old_side_incomplete"


def test_chain_old_side_is_stored_with_origin_chain(aliases):
    f = one(aliases, raw(**old("p0001")))
    assert f.old_origin == "chain"
    assert f.old.agreement_id == "base"
    assert f.old.evidence.span_text == base("p0001")
    assert f.old.evidence.section_number == "7.2"


# ---------------------------------------------------------------- targets (rev 2 R1, rev 2.1 R2-1)


@pytest.mark.parametrize("seg", ["p0001", "p0002"])
def test_section_target_accepts_the_section_and_its_subsections(aliases, seg):
    f = one(aliases, raw(**old(seg)))
    assert f.target_label == "Section 7.2 of the Lease"
    assert f.target_resolution == "section"


@pytest.mark.parametrize("seg", ["p0003", "p0004"])
def test_section_target_rejects_other_sections(aliases, seg):
    assert dropped(aliases, raw(**old(seg))) == "target_section_mismatch"


def test_range_target_accepts_old_span_inside_range(aliases):
    f = one(aliases, raw(new_quote=co("p0002"), new_segment_id="p0002", **old("p0007")))
    assert f.target_label == "Exhibit “B” to the Lease"
    assert f.target_resolution == "range"
    assert f.old_origin == "chain"


def test_range_target_rejects_old_span_outside_range(aliases):
    item = raw(new_quote=co("p0002"), new_segment_id="p0002", **old("p0004"))
    assert dropped(aliases, item) == "target_range_mismatch"


def test_range_pinned_to_other_text_is_not_used(aliases):
    item = raw(new_quote=co("p0003"), new_segment_id="p0003", **old("p0009"))
    assert dropped(aliases, item) == "target_clause_unresolved"


def test_document_only_target_rejects_any_old_clause(aliases):
    item = raw(new_quote=co("p0004"), new_segment_id="p0004", **old("p0011"))
    assert dropped(aliases, item) == "target_clause_unresolved"


def test_document_only_target_kept_without_old_side(aliases):
    f = one(aliases, raw(new_quote=co("p0004"), new_segment_id="p0004"))
    assert f.old is None and f.old_origin == "unresolved"
    assert f.target_label == "Exhibit “D” to the Lease"
    assert f.target_resolution == "document"


def test_unresolved_alias_kept_without_old_side(aliases):
    f = one(aliases, raw(new_quote=co("p0005"), new_segment_id="p0005"))
    assert f.old is None and f.old_origin == "unresolved"
    assert f.target_label == "Section 3.1 of 2A"
    assert f.target_resolution == "unresolved"


def test_unresolved_alias_rejects_a_corpus_old_side(aliases):
    item = raw(new_quote=co("p0005"), new_segment_id="p0005", **old("p0004"))
    assert dropped(aliases, item) == "target_not_in_corpus"


def test_target_label_must_be_copied_from_new_quote(aliases):
    item = raw(target_label="Section 9.9 of the Lease", **old("p0001"))
    assert dropped(aliases, item) == "target_label_not_in_quote"


def test_unresolved_supersession_requires_a_target_label(aliases):
    item = raw(new_quote=co("p0011"), new_segment_id="p0011")
    assert dropped(aliases, item) == "target_label_required"


# ---------------------------------------------------------------- supersedes


def test_supersedes_requires_a_cue(aliases):
    item = raw(new_quote=co("p0009"), new_segment_id="p0009", **old("p0004"))
    assert dropped(aliases, item) == "no_supersession_cue"


@pytest.mark.parametrize("over", [{"new_value": "2020-06-30"}, {"old_value": "2018-06-30"}])
def test_supersedes_carries_no_values(aliases, over):
    assert dropped(aliases, raw(**over, **old("p0001"))) == "values_forbidden"


def test_supersedes_values_are_null(aliases):
    f = one(aliases, raw(**old("p0001")))
    assert (f.old_value, f.new_value, f.delta, f.currency, f.context) == (
        None,
        None,
        None,
        None,
        None,
    )


# ---------------------------------------------------------------- shifted_date (R3, R2-2)

OLD_SELF = "Currently, the Term is scheduled to expire on June 30, 2018"
NEW_EXT = "shall expire on June 30, 2020"


def shift(new=NEW_EXT, old_quote=OLD_SELF, old_doc="self", old_seg="p0006", **over):
    assert new in co("p0006")
    fields = dict(
        kind="shifted_date",
        new_quote=new,
        new_segment_id="p0006",
        old_doc=old_doc,
        old_quote=old_quote,
        old_segment_id=old_seg,
        old_value="2018-06-30",
        new_value="2020-06-30",
    )
    fields.update(over)
    return raw(**fields)


def test_shifted_date_self_positive(aliases):
    f = one(aliases, shift())
    assert f.kind == "shifted_date"
    assert f.old_origin == "self"
    assert f.old.agreement_id == "co"
    assert (f.old_value, f.new_value, f.delta) == ("2018-06-30", "2020-06-30", "731")
    assert f.currency is None


def test_shifted_date_chain_positive_needs_no_prior_state_cue(aliases):
    f = one(aliases, shift(old_doc="base", old_seg="p0005", old_quote=base("p0005")))
    assert f.old_origin == "chain" and f.delta == "731"


def test_shifted_date_requires_an_old_side(aliases):
    item = shift(old_doc=None, old_quote=None, old_seg=None, old_value=None)
    assert dropped(aliases, item) == "old_side_required"


def test_shifted_date_new_value_must_be_the_quoted_date(aliases):
    assert dropped(aliases, shift(new_value="2020-07-01")) == "new_value_not_in_quote"


def test_shifted_date_old_value_must_be_the_quoted_date(aliases):
    assert dropped(aliases, shift(old_value="2018-07-01")) == "old_value_not_in_quote"


def test_shifted_date_quotes_hold_exactly_one_date(aliases):
    assert dropped(aliases, shift(new=co("p0006"))) == "date_token_count"


def test_shifted_date_dates_must_differ(aliases):
    item = shift(
        new=OLD_SELF,
        new_value="2018-06-30",
        old_doc="base",
        old_seg="p0005",
        old_quote=base("p0005"),
    )
    assert dropped(aliases, item) == "dates_equal"


def test_shifted_date_role_word_must_be_inside_the_quote(aliases):
    assert dropped(aliases, shift(new="June 30, 2020")) == "date_role_outside_quote"


def test_shifted_date_self_old_side_needs_prior_state_cue(aliases):
    item = shift(
        new=OLD_SELF,
        new_value="2018-06-30",
        old_quote=NEW_EXT,
        old_value="2020-06-30",
    )
    assert dropped(aliases, item) == "old_state_cue_missing"


# ---------------------------------------------------------------- price_change (R3)

RENT = "Tenant shall pay rent of $1,250.00 per month."


def priced(**over):
    fields = dict(
        kind="price_change", new_quote=RENT, new_segment_id="p0007", new_value="$1,250.00"
    )
    fields.update(over)
    return raw(**fields)


def test_price_added_positive(aliases):
    f = one(aliases, priced(), category="price")
    assert f.kind == "price_change" and f.category == "price"
    assert f.new_value == "1250.00" and f.currency == "USD"
    assert f.old is None and f.old_origin == "unresolved"
    assert f.old_value is None and f.delta is None
    assert f.target_label is None
    assert f.context is None


def test_price_context_is_a_grounded_change_order_span(aliases):
    item = priced(context_quote=co("p0008"), context_segment_id="p0008")
    f = one(aliases, item, category="price")
    assert f.context.agreement_id == "co"
    assert f.context.evidence.segment_id == "p0008"
    assert f.context.evidence.span_text == co("p0008")


@pytest.mark.parametrize(
    "over",
    [
        {"context_quote": "July 4", "context_segment_id": "p0008"},
        {"context_quote": co("p0008"), "context_segment_id": "p0099"},
        {"context_quote": co("p0008"), "context_segment_id": None},
        {"context_quote": None, "context_segment_id": "p0008"},
    ],
)
def test_price_context_must_ground(aliases, over):
    assert dropped(aliases, priced(**over), category="price") == "context_not_found"


def test_price_new_value_must_be_a_money_token_of_the_quote(aliases):
    item = priced(new_value="$15,000.00")
    assert dropped(aliases, item, category="price") == "new_value_not_in_quote"


def test_price_old_value_is_forbidden(aliases):
    item = priced(old_value="$1,000", **old("p0004"))
    assert dropped(aliases, item, category="price") == "old_value_forbidden"


def test_price_old_side_is_forbidden(aliases):
    assert dropped(aliases, priced(**old("p0004")), category="price") == "old_side_forbidden"


# ---------------------------------------------------------------- potential_conflict


def conflict(**over):
    fields = dict(kind="potential_conflict", new_quote=co("p0010"), new_segment_id="p0010")
    fields.update(over)
    return raw(**fields)


def test_potential_conflict_positive(aliases):
    f = one(aliases, conflict(**old("p0004")), category="price")
    assert f.kind == "potential_conflict" and f.old_origin == "chain"


def test_potential_conflict_requires_a_chain_old_side(aliases):
    assert dropped(aliases, conflict(), category="price") == "old_side_required"


def test_potential_conflict_rejects_a_self_old_side(aliases):
    item = conflict(**old("p0007", doc="self"))
    assert dropped(aliases, item, category="price") == "old_side_forbidden"


def test_potential_conflict_carries_no_values(aliases):
    item = conflict(new_value="$1,250.00", **old("p0004"))
    assert dropped(aliases, item, category="price") == "values_forbidden"


# ---------------------------------------------------------------- dedupe


def test_duplicate_findings_are_dropped(aliases):
    item = raw(**old("p0001"))
    res = run(aliases, item, item)
    assert len(res.findings) == 1
    assert [d.reason for d in res.drops] == ["duplicate"]
