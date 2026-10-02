import json

import pytest
from extract_fakes import (
    MODEL,
    item,
    iteration,
    max_tokens_message,
    message,
    ok_message,
    refusal_message,
    text_block,
    thinking_block,
    usage,
)

from og.extract.client import parse_response
from og.extract.types import RAW_FIELDS, Attempt, BadResponse, RawItem, Refused, TruncatedResponse


def raw_text(text, **kw):
    return message([text_block(text)], **kw)


def test_ok_items_parsed_in_order():
    a = item(span_text="Tenant shall pay rent.", segment_id="p0001", amount=100)
    b = item(kind="party", type=None, status=None, name="Landlord Co", role="landlord")
    items, attempts = parse_response(ok_message([a, b]))
    assert [i.segment_id for i in items] == ["p0001", "p0001"]
    assert isinstance(items[0], RawItem)
    assert items[0].amount == 100
    assert items[1].kind == "party" and items[1].role == "landlord" and items[1].type is None


def test_empty_items_is_valid():
    items, _ = parse_response(ok_message([]))
    assert items == []


def test_refusal_raises_even_with_text():
    with pytest.raises(Refused):
        parse_response(refusal_message())
    m = ok_message([item()])
    m.stop_reason = "refusal"
    with pytest.raises(Refused):
        parse_response(m)


def test_max_tokens_checked_before_parsing():
    with pytest.raises(TruncatedResponse):
        parse_response(max_tokens_message())
    with pytest.raises(TruncatedResponse):
        parse_response(raw_text('{"items": [', stop_reason="max_tokens"))


def test_thinking_blocks_ignored():
    m = message([thinking_block(), text_block(json.dumps({"items": [item()]}))])
    items, _ = parse_response(m)
    assert len(items) == 1


@pytest.mark.parametrize(
    "blocks",
    [[], [thinking_block()], [text_block("{}"), text_block('{"items": []}')]],
)
def test_no_single_text_block_is_no_text(blocks):
    with pytest.raises(BadResponse) as e:
        parse_response(message(blocks))
    assert e.value.args[0] == "no_text"


def _with(**over):
    return raw_text(json.dumps({"items": [item(**over)]}))


def _missing(field):
    d = item()
    del d[field]
    return raw_text(json.dumps({"items": [d]}))


@pytest.mark.parametrize(
    "msg",
    [
        raw_text("not json"),
        raw_text('{"items": {}}'),
        raw_text("[]"),
        raw_text('{"items": [], "extra": 1}'),
        _missing("span_text"),
        _missing("role"),
        raw_text(json.dumps({"items": [dict(item(), surprise=1)]})),
        _with(kind="clause"),
        _with(type="rent"),
        _with(status="maybe"),
        _with(role="owner", kind="party"),
        _with(span_text=None),
        _with(segment_id=7),
        _with(amount="54000"),
        _with(amount=True),
        _with(offset_days=1.5),
        _with(offset_days=True),
        _with(due_date="2026-02-30"),
        _with(due_date="03/01/2026"),
        _with(date="2026-13-01", kind="event", type=None, name="Commencement Date"),
        raw_text(
            '{"items": [' + json.dumps(item()).replace('"amount": null', '"amount": NaN') + "]}"
        ),
    ],
)
def test_invalid_payloads_are_bad_response(msg):
    with pytest.raises(BadResponse) as e:
        parse_response(msg)
    assert isinstance(e.value.args[0], str) and e.value.args[0]


def test_valid_dates_and_numbers_accepted():
    items, _ = parse_response(_with(due_date="2028-02-29", amount=54000.5, offset_days=-30))
    assert items[0].due_date == "2028-02-29"
    assert items[0].offset_days == -30


def test_single_attempt_from_top_level_usage():
    m = ok_message([item()], usage_=usage(inp=500, out=60, cache_read=400, cache_write=0))
    _, attempts = parse_response(m)
    assert attempts == [
        Attempt(
            model=MODEL,
            input_tokens=500,
            output_tokens=60,
            cache_read_tokens=400,
            cache_write_tokens=0,
            refused=False,
        )
    ]


def test_attempts_from_usage_iterations_on_fallback():
    its = [
        iteration("message", "claude-sonnet-5-5", inp=300, out=0),
        iteration("fallback_message", "claude-opus-5-5", inp=310, out=80),
    ]
    m = ok_message([item()], model="claude-opus-5-5", usage_=usage(inp=310, out=80, iterations=its))
    _, attempts = parse_response(m)
    assert [a.model for a in attempts] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    assert [a.refused for a in attempts] == [True, False]
    assert [a.output_tokens for a in attempts] == [0, 80]


def test_missing_cache_fields_are_none():
    u = usage()
    del u.cache_read_input_tokens
    del u.cache_creation_input_tokens
    _, attempts = parse_response(ok_message([item()], usage_=u))
    assert attempts[0].cache_read_tokens is None and attempts[0].cache_write_tokens is None


def test_sdk_model_objects_parse():
    from anthropic.types import Message, TextBlock, Usage

    m = Message.model_construct(
        id="msg_synthetic",
        type="message",
        role="assistant",
        model=MODEL,
        content=[TextBlock.model_construct(type="text", text=json.dumps({"items": [item()]}))],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage.model_construct(input_tokens=10, output_tokens=5),
    )
    items, attempts = parse_response(m)
    assert len(items) == 1 and attempts[0].model == MODEL


def test_raw_item_fields_match_schema_order():
    import dataclasses

    assert tuple(f.name for f in dataclasses.fields(RawItem)) == RAW_FIELDS
