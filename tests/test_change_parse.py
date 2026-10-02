"""Task 16: parse_findings turns one SDK message into RawFindings or a typed failure."""

import json

import pytest
from change_fakes import SONNET, finding, findings_message, message, usage

from og.change.client import parse_findings
from og.change.types import RAW_FINDING_FIELDS, RawFinding
from og.extract.types import Attempt, BadResponse, Refused, TruncatedResponse


def test_ok_message_parses_every_field_in_order():
    item = finding(
        new_quote="Section 2.C of 2A is hereby deleted",
        new_segment_id="p0013",
        target_label="Section 2.C of 2A",
    )
    items, attempts = parse_findings(findings_message([item]))
    assert items == [RawFinding(**{f: item[f] for f in RAW_FINDING_FIELDS})]
    assert attempts == [Attempt(SONNET, 120, 10, 0, 0, False)]


def test_empty_findings_is_valid():
    items, attempts = parse_findings(findings_message([]))
    assert items == []
    assert len(attempts) == 1


def test_attempt_records_cache_usage_and_message_model():
    msg = findings_message([], usage_=usage(inp=50, out=7, cache_read=900, cache_write=30))
    _, attempts = parse_findings(msg)
    assert attempts == [Attempt(SONNET, 50, 7, 900, 30, False)]


def test_refusal_raises_refused():
    with pytest.raises(Refused):
        parse_findings(message(None, stop_reason="refusal"))


def test_max_tokens_raises_truncated_even_with_valid_json():
    with pytest.raises(TruncatedResponse):
        parse_findings(findings_message([finding()], stop_reason="max_tokens"))


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps([]),
        json.dumps({"items": []}),
        json.dumps({"findings": [], "extra": 1}),
        json.dumps({"findings": {}}),
    ],
)
def test_bad_shape_raises_bad_response(text):
    with pytest.raises(BadResponse):
        parse_findings(message(text))


def test_no_text_block_raises_bad_response():
    with pytest.raises(BadResponse):
        parse_findings(message(None))


@pytest.mark.parametrize("field", RAW_FINDING_FIELDS)
def test_missing_field_raises_bad_response(field):
    item = finding()
    del item[field]
    with pytest.raises(BadResponse):
        parse_findings(findings_message([item]))


def test_extra_field_raises_bad_response():
    item = finding(description="Tenant must pay.")
    with pytest.raises(BadResponse):
        parse_findings(findings_message([item]))


@pytest.mark.parametrize(
    "over",
    [
        {"kind": "conflict"},
        {"kind": None},
        {"new_quote": None},
        {"new_quote": 5},
        {"new_segment_id": None},
        {"old_doc": 3},
        {"old_quote": ["a"]},
        {"old_value": 2018},
        {"new_value": 35596.8},
        {"target_label": True},
        {"context_quote": {}},
    ],
)
def test_bad_field_type_or_enum_raises_bad_response(over):
    with pytest.raises(BadResponse):
        parse_findings(findings_message([finding(**over)]))
