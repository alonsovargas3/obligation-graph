import hashlib

import pytest
import yaml

from og.eval.gold import load_gold
from og.textdoc import Page, Section, Segment, TextDoc

LINES = [
    "1. Tenant shall pay Base Rent of $54,000 per month.",
    "2. Landlord shall deliver the Tenant Space on or before March 1, 2011.",
]
TEXT = "\n".join(LINES)
S2 = TEXT.index("2.")
DOC = TextDoc(
    "d1",
    "raw-sha",
    TEXT,
    [Section("s0001", "1", "Rent", 0, S2, None), Section("s0002", "2", "Delivery", S2, len(TEXT))],
    [Page(1, 0, len(TEXT))],
    [Segment("p0001", "s0001", 1, 0, S2 - 1), Segment("p0002", "s0002", 1, S2, len(TEXT))],
)
TEXTDOC_SHA = hashlib.sha256(DOC.to_json().encode()).hexdigest()
RENT = "Tenant shall pay Base Rent of $54,000 per month."
DELIVER = "Landlord shall deliver the Tenant Space on or before March 1, 2011."


def item(quote, segment_id, **kw):
    start = TEXT.index(quote)
    base = {
        "segment_id": segment_id,
        "char_start": start,
        "char_end": start + len(quote),
        "span_text": quote,
        "type": "payment",
        "owed_by": "Tenant",
        "owed_to": "Landlord",
        "description": "Pay base rent monthly.",
        "amount": 54000,
        "currency": "USD",
        "due_date": None,
        "anchor_event": None,
        "offset_days": None,
        "trigger": None,
        "status": "active",
    }
    base.update(kw)
    return base


def gold_doc(**top):
    data = {
        "doc_id": "d1",
        "source_sha256": "raw-sha",
        "textdoc_sha256": TEXTDOC_SHA,
        "provenance": {
            "drafted_by": "gpt-6-astra",
            "adjudicated_by": "coordinator",
            "spot_checked": 10,
        },
        "scope": "full_agreement",
        "obligations": [
            item(RENT, "p0001"),
            item(
                DELIVER,
                "p0002",
                type="delivery",
                owed_by="Landlord",
                owed_to="Tenant",
                amount=None,
                currency=None,
                due_date="2011-03-01",
            ),
        ],
    }
    data.update(top)
    return data


def write(tmp_path, data):
    p = tmp_path / "gold.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


def test_valid_gold_loads(tmp_path):
    gold = load_gold(write(tmp_path, gold_doc()), DOC)
    assert gold.doc_id == "d1"
    assert gold.scope == "full_agreement"
    assert gold.provenance["drafted_by"] == "gpt-6-astra"
    assert [g.type for g in gold.obligations] == ["payment", "delivery"]
    first = gold.obligations[0]
    assert (first.char_start, first.char_end) == (TEXT.index(RENT), TEXT.index(RENT) + len(RENT))
    assert first.amount == 54000
    assert gold.obligations[1].due_date == "2011-03-01"


def mutate_item(index, **kw):
    data = gold_doc()
    data["obligations"][index] = {**data["obligations"][index], **kw}
    return data


@pytest.mark.parametrize(
    "data,code",
    [
        (gold_doc(doc_id="other"), "doc_id_mismatch"),
        (gold_doc(source_sha256="nope"), "source_sha_mismatch"),
        (gold_doc(textdoc_sha256="nope"), "textdoc_sha_mismatch"),
        (gold_doc(scope="most_of_it"), "bad_enum:scope"),
        (mutate_item(0, char_end=len(TEXT) + 5), "out_of_bounds"),
        (mutate_item(0, char_start=-1), "out_of_bounds"),
        (
            mutate_item(0, span_text="Tenant shall pay Base Rent of $45,000 per month."),
            "span_mismatch",
        ),
        (mutate_item(0, segment_id="p0002"), "span_outside_segment"),
        (mutate_item(0, segment_id="p0099"), "span_outside_segment"),
        (mutate_item(0, type="rent"), "bad_enum:type"),
        (mutate_item(0, status="maybe"), "bad_enum:status"),
        (mutate_item(1, due_date="2011-02-30"), "bad_date:due_date"),
        (mutate_item(1, due_date="March 1, 2011"), "bad_date:due_date"),
        (mutate_item(0, amount="lots"), "bad_number:amount"),
        (mutate_item(0, offset_days=1.5), "bad_number:offset_days"),
    ],
)
def test_invalid_gold_is_rejected(tmp_path, data, code):
    with pytest.raises(ValueError) as e:
        load_gold(write(tmp_path, data), DOC)
    assert e.value.args[0] == code
