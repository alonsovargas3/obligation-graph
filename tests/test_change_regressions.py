"""Task 17 real-text regressions (Astra wave-3 review rounds 1-3).

Every quote is sliced from the real ingested filings (public SEC exhibits) in
tests/fixtures/change/, never retyped, so nonbreaking spaces and curly quotes
are exact. Target ranges come from prompts/change_aliases_v1.yaml (the default).
"""

import pytest
from change_fakes import A1_ID, A3_ID, BASE_ID, real_doc

from og.change.types import ChainDoc, RawFinding
from og.change.verify import verify_findings

BASE = real_doc(BASE_ID)
A1 = real_doc(A1_ID)
A3 = real_doc(A3_ID)
CHAIN_1A = [ChainDoc(BASE_ID, BASE, "base"), ChainDoc(A1_ID, A1, "change_order")]
CHAIN_3A = [
    ChainDoc(BASE_ID, BASE, "base"),
    ChainDoc(A1_ID, A1, "prior_amendment"),
    ChainDoc(A3_ID, A3, "change_order"),
]


def cut(doc, seg, start, end=None):
    """The exact source substring of `seg` from `start` through `end` (inclusive).

    With no `end`, the quote is exactly `start` (asserted present in the source).
    """
    text = doc.segment_text(seg)
    assert start in text, (seg, start)
    i = text.index(start)
    if end is None:
        return start
    assert end in text[i:], (seg, end)
    return text[i : text.index(end, i) + len(end)]


def raw(**over):
    fields = dict(
        new_quote="",
        new_segment_id="",
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


def base_old(seg):
    return {"old_doc": BASE_ID, "old_quote": BASE.segment_text(seg), "old_segment_id": seg}


def one(chain, item, category="parties_or_sites"):
    res = verify_findings(chain, category, [item])
    assert res.drops == [], [d.reason for d in res.drops]
    assert len(res.findings) == 1
    return res.findings[0]


def reason(chain, item, category="parties_or_sites"):
    res = verify_findings(chain, category, [item])
    assert res.findings == []
    assert len(res.drops) == 1
    return res.drops[0].reason


RENT_P0455 = base_old("p0455")

# ---------------------------------------------------------------- targets

DEL_2A = cut(A3, "p0013", "Effective as of", "force or effect.")
EXHIBIT_A = cut(A1, "p0017", "Exhibit", "attached hereto")
ITEM_7 = cut(A1, "p0019", "Item", "as follows:")
TABLE_A = cut(A1, "p0037", "Table A of Exhibit", "incorporated herein")


def test_3a_deletion_of_missing_2a_section_is_kept_unresolved():
    f = one(CHAIN_3A, raw(new_quote=DEL_2A, new_segment_id="p0013"))
    assert f.old is None and f.old_origin == "unresolved"
    assert f.target_label == "Section 2.C of 2A"
    assert f.target_resolution == "unresolved"
    assert f.new.evidence.span_text == DEL_2A


def test_3a_deletion_of_missing_2a_section_rejects_a_base_clause():
    item = raw(new_quote=DEL_2A, new_segment_id="p0013", **RENT_P0455)
    assert reason(CHAIN_3A, item) == "target_not_in_corpus"


def test_1a_exhibit_a_replacement_resolves_to_its_range():
    f = one(CHAIN_1A, raw(new_quote=EXHIBIT_A, new_segment_id="p0017", **base_old("p0808")))
    assert f.target_label == "Exhibit “A” to the Lease"
    assert f.target_resolution == "range"
    assert f.old_origin == "chain" and f.old.agreement_id == BASE_ID
    assert f.old.evidence.segment_id == "p0808"


def test_1a_exhibit_a_replacement_rejects_base_rent():
    item = raw(new_quote=EXHIBIT_A, new_segment_id="p0017", **RENT_P0455)
    assert reason(CHAIN_1A, item) == "target_range_mismatch"


def test_1a_item_7_restatement_resolves_to_its_range():
    label = cut(A1, "p0019", "Item", "to the Lease")
    assert " " in label  # the source has a nonbreaking space after Item
    f = one(CHAIN_1A, raw(new_quote=ITEM_7, new_segment_id="p0019", **base_old("p0445")))
    assert f.target_label == label
    assert f.target_resolution == "range"


def test_1a_item_7_restatement_rejects_base_rent():
    item = raw(new_quote=ITEM_7, new_segment_id="p0019", **RENT_P0455)
    assert reason(CHAIN_1A, item) == "target_range_mismatch"


def test_1a_table_a_replacement_resolves_to_its_range():
    f = one(CHAIN_1A, raw(new_quote=TABLE_A, new_segment_id="p0037", **base_old("p0893")), "sla")
    assert f.target_label == "Table A of Exhibit “F” to the Original Lease"
    assert f.target_resolution == "range"


def test_1a_table_a_replacement_rejects_base_rent():
    item = raw(new_quote=TABLE_A, new_segment_id="p0037", **RENT_P0455)
    assert reason(CHAIN_1A, item, "sla") == "target_range_mismatch"


def test_1a_table_a_range_excludes_the_next_heading():
    item = raw(new_quote=TABLE_A, new_segment_id="p0037", **base_old("p0903"))
    assert reason(CHAIN_1A, item, "sla") == "target_range_mismatch"


# ---------------------------------------------------------------- self supersession (W3-2)

SELF_P0012 = cut(A3, "p0012", "For the avoidance of doubt", "Amended Surrender Date.")


def test_3a_self_restatement_is_a_clause_level_finding_with_self_origin():
    item = raw(
        new_quote=SELF_P0012,
        new_segment_id="p0012",
        old_doc="self",
        old_quote=SELF_P0012,
        old_segment_id="p0012",
    )
    f = one(CHAIN_3A, item, "dates")
    assert f.old_origin == "self"
    assert f.old.agreement_id == A3_ID


# ---------------------------------------------------------------- dates (3A p0011)

OLD_SURRENDER = cut(A3, "p0011", "Currently", "June 30, 2018")
NEW_EXPIRY = cut(A3, "p0011", "expiring June 30, 2020")
COMMENCING = cut(A3, "p0011", "commencing July 1, 2018")
COMMENCING_CLIPPED = cut(A3, "p0011", "commencing July 1, 2018 and expiring")
BARE_NEW = cut(A3, "p0011", "June 30, 2020")
WHOLE = A3.segment_text("p0011")


def shift(new, new_value, old_quote=OLD_SURRENDER, old_value="2018-06-30"):
    return raw(
        kind="shifted_date",
        new_quote=new,
        new_segment_id="p0011",
        old_doc="self",
        old_quote=old_quote,
        old_segment_id="p0011",
        old_value=old_value,
        new_value=new_value,
    )


def test_3a_surrender_extension_is_731_days():
    assert OLD_SURRENDER.startswith("Currently, the portion of the Premises located in Suite 409")
    f = one(CHAIN_3A, shift(NEW_EXPIRY, "2020-06-30"), "dates")
    assert f.old_origin == "self"
    assert (f.old_value, f.new_value, f.delta) == ("2018-06-30", "2020-06-30", "731")


def test_3a_reversed_pair_is_rejected():
    item = shift(OLD_SURRENDER, "2018-06-30", old_quote=NEW_EXPIRY, old_value="2020-06-30")
    assert reason(CHAIN_3A, item, "dates") == "old_state_cue_missing"


@pytest.mark.parametrize("new", [COMMENCING, COMMENCING_CLIPPED])
def test_3a_commencement_date_is_not_a_surrender_shift(new):
    assert reason(CHAIN_3A, shift(new, "2018-07-01"), "dates") == "date_role_mismatch"


def test_3a_role_word_outside_quote_is_rejected():
    assert reason(CHAIN_3A, shift(BARE_NEW, "2020-06-30"), "dates") == "date_role_outside_quote"


def test_3a_whole_paragraph_has_three_dates():
    assert reason(CHAIN_3A, shift(WHOLE, "2020-06-30"), "dates") == "date_token_count"


# ---------------------------------------------------------------- prices

AMOUNT = cut(A3, "p0018", "$35,596.80/month")
PERIOD = A3.segment_text("p0017")


def test_3a_extended_term_rent_is_a_price_added_with_period_context():
    item = raw(
        kind="price_change",
        new_quote=AMOUNT,
        new_segment_id="p0018",
        new_value="$35,596.80",
        context_quote=PERIOD,
        context_segment_id="p0017",
    )
    f = one(CHAIN_3A, item, "price")
    assert f.new_value == "35596.80" and f.currency == "USD"
    assert f.old is None and f.old_origin == "unresolved"
    assert f.old_value is None and f.delta is None
    assert f.context.evidence.segment_id == "p0017"
    assert f.context.evidence.span_text == PERIOD


def test_3a_rent_has_no_delta_against_base_suite_rent():
    item = raw(
        kind="price_change",
        new_quote=AMOUNT,
        new_segment_id="p0018",
        new_value="$35,596.80",
        old_value="$33,428.11",
        **RENT_P0455,
    )
    assert reason(CHAIN_3A, item, "price") == "old_value_forbidden"
