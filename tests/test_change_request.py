"""Task 16: request shape, budget reservation, outcome statuses, and the check cache."""

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from change_fakes import (
    HAIKU,
    SENTINEL_KEY,
    SONNET,
    FakeAnthropic,
    finding,
    findings_message,
    message,
    usage,
)
from extract_fakes import build_doc

from og.budget import Budget
from og.change.client import Checker, build_request, prompt_version
from og.change.types import ChainDoc, RawFinding
from og.gates.types import load_questions
from og.pricing import price

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "prompts" / "change_v1.md"
SCHEMA = ROOT / "prompts" / "change_v1.schema.json"
QUESTIONS = {q.category: q for q in load_questions()}
COUNT = 1000
RESERVE = (COUNT * 2.50 + 4096 * 10.00) / 1e6  # Sonnet: cache-write input tariff + max output


def chain(base_line="Tenant shall pay Base Rent of $1,000 per month."):
    base = build_doc([("1", "Rent", [base_line, "Landlord shall deliver."])], doc_id="base")
    a1 = build_doc([("1", "One", ["Suite 1 is renamed Suite 2."])], doc_id="a1")
    co = build_doc([("1", "Two", ["Section 1 of the Lease is hereby deleted."])], doc_id="co")
    return [
        ChainDoc("base", base, "base"),
        ChainDoc("a1", a1, "prior_amendment"),
        ChainDoc("co", co, "change_order"),
    ]


def req(ch=None, category="price", **over):
    kw = {"model": SONNET, "effort": "high", "max_tokens": 4096}
    kw.update(over)
    return build_request(ch or chain(), category, QUESTIONS[category], **kw)


def checker(client, tmp_path, budget=None, **over):
    kw = {"model": SONNET, "effort": "high", "max_tokens": 4096}
    kw.update(over)
    return Checker(
        client,
        budget=budget if budget is not None else Budget(None),
        cache_dir=tmp_path / "cache",
        **kw,
    )


def ok_client(items=None, **kw):
    return FakeAnthropic(responder=lambda _kw: findings_message(items or []), **kw)


# ---------------------------------------------------------------- request shape


def test_prompt_version_format_and_value():
    digest = hashlib.sha256(PROMPT.read_bytes() + SCHEMA.read_bytes()).hexdigest()[:8]
    assert prompt_version() == "change_v1@" + digest


def test_request_exact_kwargs_no_fallback_no_sampling():
    r = req()
    assert set(r) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert r["model"] == SONNET
    assert r["max_tokens"] == 4096
    assert r["system"] == [
        {
            "type": "text",
            "text": PROMPT.read_text(encoding="utf-8"),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert r["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": json.loads(SCHEMA.read_text())},
    }


def test_user_content_is_chain_then_change_order_then_category():
    r = req()
    assert len(r["messages"]) == 1 and r["messages"][0]["role"] == "user"
    blocks = r["messages"][0]["content"]
    assert len(blocks) == 3
    chain_block, co_block, tail = blocks
    assert chain_block == {
        "type": "text",
        "text": "## base (base)\n"
        "[base p0001] Tenant shall pay Base Rent of $1,000 per month.\n"
        "[base p0002] Landlord shall deliver.\n\n"
        "## a1 (prior_amendment)\n"
        "[a1 p0001] Suite 1 is renamed Suite 2.",
        "cache_control": {"type": "ephemeral"},
    }
    assert co_block == {
        "type": "text",
        "text": "## co (change_order)\n[co p0001] Section 1 of the Lease is hereby deleted.",
        "cache_control": {"type": "ephemeral"},
    }
    assert tail["type"] == "text" and "cache_control" not in tail
    assert "Category: price" in tail["text"]
    assert QUESTIONS["price"].definition in tail["text"]


def test_base_only_chain_still_has_three_blocks():
    ch = chain()
    r = req([ch[0], ch[2]])
    blocks = r["messages"][0]["content"]
    assert len(blocks) == 3
    assert blocks[0]["text"].startswith("## base (base)\n")
    assert "a1" not in blocks[0]["text"]


def test_category_block_follows_question():
    tail = req(category="sla")["messages"][0]["content"][2]["text"]
    assert "Category: sla" in tail and QUESTIONS["sla"].definition in tail


# ---------------------------------------------------------------- live call + budget


def test_count_tokens_first_with_identical_effective_request(tmp_path):
    client = ok_client()
    out = checker(client, tmp_path).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "ok"
    assert len(client.count_calls) == 1 and len(client.calls) == 1
    sent = client.calls[0]
    assert client.count_calls[0] == {
        k: sent[k] for k in ("model", "system", "messages", "output_config")
    }
    assert sent == req()


def test_ok_outcome_and_budget_settles_to_actual(tmp_path):
    item = finding(new_quote="Section 1 of the Lease is hereby deleted.", new_segment_id="p0001")
    client = ok_client([item], count=COUNT)
    budget = Budget(None)
    out = checker(client, tmp_path, budget).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "ok" and out.category == "price" and out.error is None
    assert out.items == [RawFinding(**item)]
    assert out.cache_hit is False
    assert isinstance(out.latency_ms, int) and out.latency_ms >= 0
    assert out.request_fingerprint
    assert budget.spent_usd == pytest.approx(price(out.attempts)[0])
    assert budget.reserved_usd == pytest.approx(0.0)
    assert budget.calls == 1


def test_reservation_boundary_admits_exact_amount(tmp_path):
    client = ok_client(count=COUNT)
    out = checker(client, tmp_path, Budget(RESERVE)).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "ok" and len(client.calls) == 1


def test_reservation_boundary_refuses_below_amount(tmp_path):
    client = ok_client(count=COUNT)
    budget = Budget(RESERVE - 0.000001)
    out = checker(client, tmp_path, budget).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "budget_stop"
    assert client.calls == []
    assert budget.exhausted is not None


def test_exhausted_budget_is_sticky(tmp_path):
    client = ok_client(count=COUNT)
    budget = Budget(RESERVE - 0.000001)
    ck = checker(client, tmp_path, budget)
    assert ck.check(chain(), "price", QUESTIONS["price"]).status == "budget_stop"
    budget.limit_usd = 100.0
    assert ck.check(chain(), "dates", QUESTIONS["dates"]).status == "budget_stop"
    assert client.calls == []


def test_count_tokens_error_means_budget_stop_and_no_call(tmp_path):
    client = ok_client(count=RuntimeError("count failed"))
    budget = Budget(10.0)
    out = checker(client, tmp_path, budget).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "budget_stop"
    assert client.calls == []
    assert budget.exhausted is not None


def test_unpriced_model_means_budget_stop(tmp_path):
    client = ok_client()
    out = checker(client, tmp_path, Budget(10.0), model="claude-unknown-9").check(
        chain(), "price", QUESTIONS["price"]
    )
    assert out.status == "budget_stop"
    assert client.calls == []


# ---------------------------------------------------------------- failure statuses


def test_refusal_is_refused_and_its_usage_is_charged(tmp_path):
    msg = message(None, stop_reason="refusal", usage_=usage(inp=100, out=5))
    client = FakeAnthropic(responses=[msg])
    budget = Budget(None)
    out = checker(client, tmp_path, budget).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "refused" and out.items == []
    assert [(a.model, a.input_tokens, a.output_tokens) for a in out.attempts] == [(SONNET, 100, 5)]
    assert budget.spent_usd == pytest.approx((100 * 2.0 + 5 * 10.0) / 1e6)


def test_max_tokens_is_truncated_and_its_usage_is_charged(tmp_path):
    msg = findings_message([finding()], stop_reason="max_tokens", usage_=usage(inp=200, out=4096))
    client = FakeAnthropic(responses=[msg])
    budget = Budget(None)
    out = checker(client, tmp_path, budget).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "truncated" and out.items == []
    assert [(a.input_tokens, a.output_tokens) for a in out.attempts] == [(200, 4096)]
    assert budget.spent_usd == pytest.approx((200 * 2.0 + 4096 * 10.0) / 1e6)


def test_schema_invalid_item_is_invalid(tmp_path):
    client = FakeAnthropic(responses=[findings_message([finding(kind="conflict")])])
    out = checker(client, tmp_path).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "invalid" and out.items == []


class Boom(Exception):
    pass


def test_exception_is_error_with_class_name_and_full_reservation_charged(tmp_path):
    client = FakeAnthropic(responder=lambda _kw: Boom("secret detail " + SENTINEL_KEY), count=COUNT)
    budget = Budget(None)
    out = checker(client, tmp_path, budget).check(chain(), "price", QUESTIONS["price"])
    assert out.status == "error"
    assert out.error == "Boom"
    assert budget.spent_usd == pytest.approx(RESERVE)
    assert budget.reserved_usd == pytest.approx(0.0)


def test_failures_are_not_cached(tmp_path):
    client = FakeAnthropic(responses=[message(None, stop_reason="refusal"), findings_message([])])
    ck = checker(client, tmp_path)
    assert ck.check(chain(), "price", QUESTIONS["price"]).status == "refused"
    again = ck.check(chain(), "price", QUESTIONS["price"])
    assert again.status == "ok" and again.cache_hit is False
    assert len(client.calls) == 2


# ---------------------------------------------------------------- cache


def test_cache_hit_makes_no_client_call(tmp_path):
    item = finding(new_quote="Section 1 of the Lease is hereby deleted.")
    first = checker(ok_client([item]), tmp_path).check(chain(), "price", QUESTIONS["price"])
    client = ok_client()
    hit = checker(client, tmp_path).check(chain(), "price", QUESTIONS["price"])
    assert client.calls == [] and client.count_calls == []
    assert hit.status == "ok" and hit.cache_hit is True
    assert hit.items == first.items
    assert hit.attempts == first.attempts
    assert hit.request_fingerprint == first.request_fingerprint


def _miss_after(tmp_path, first_kw, second_kw, first_chain=None, second_chain=None):
    first = dict(category="price", question=QUESTIONS["price"])
    first.update(first_kw.pop("call", {}))
    second = dict(category="price", question=QUESTIONS["price"])
    second.update(second_kw.pop("call", {}))
    checker(ok_client(), tmp_path, **first_kw).check(first_chain or chain(), **first)
    client = ok_client()
    out = checker(client, tmp_path, **second_kw).check(second_chain or chain(), **second)
    return client, out


@pytest.mark.parametrize(
    "second",
    [
        {"call": {"category": "dates", "question": QUESTIONS["dates"]}},
        {
            "call": {
                "question": dataclasses.replace(
                    QUESTIONS["price"], definition="Does it touch the rent?"
                )
            }
        },
        {"effort": "medium"},
        {"model": HAIKU},
        {"max_tokens": 2048},
    ],
)
def test_cache_key_covers_request_inputs(tmp_path, second):
    client, out = _miss_after(tmp_path, {}, dict(second))
    assert out.cache_hit is False and len(client.calls) == 1


def test_cache_key_covers_chain_textdoc(tmp_path):
    client, out = _miss_after(
        tmp_path, {}, {}, second_chain=chain("Tenant shall pay Base Rent of $2,000 per month.")
    )
    assert out.cache_hit is False and len(client.calls) == 1


def test_cache_files_are_allowlisted_and_never_hold_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    item = finding(new_quote="Section 1 of the Lease is hereby deleted.")
    checker(ok_client([item]), tmp_path).check(chain(), "price", QUESTIONS["price"])
    files = [p for p in (tmp_path / "cache").rglob("*") if p.is_file()]
    assert files
    for p in files:
        raw = p.read_bytes()
        assert SENTINEL_KEY.encode() not in raw
        payload = json.loads(raw)
        assert set(payload) <= {
            "findings",
            "attempts",
            "prompt_version",
            "category",
            "request_fingerprint",
            "latency_ms",
        }
        assert {"findings", "attempts"} <= set(payload)
