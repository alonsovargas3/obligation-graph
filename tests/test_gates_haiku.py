"""HaikuGate (classifier tier) and JevGate (protocol slot), wave 3 Task 15.

All API traffic is SYNTHETIC (tests/change_fakes.py). The change order is the
REAL Third Amendment (3A) TextDoc. Pins plan rev 2 R5/R6 and rev 2.1 R2-3:
three samples, count_tokens on the complete request before every call, no
server-side fallback, usage settled before parsing, fail-open sample handling.
"""

import json
import socket
from pathlib import Path

import pytest
from change_fakes import (
    A1_ID,
    A3_ID,
    HAIKU,
    SENTINEL_KEY,
    FakeAnthropic,
    gate_message,
    message,
    real_doc,
    usage,
)

from og.budget import Budget
from og.gates.haiku import HaikuGate
from og.gates.jev import JevGate
from og.gates.types import GATE_POLICY, GateContext, GateDecision, load_questions

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = (ROOT / "prompts" / "gate_v1.md").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "prompts" / "gate_v1.schema.json").read_text(encoding="utf-8"))
QUESTIONS = {q.category: q for q in load_questions()}
CTX = GateContext(base_section_types={})
FORBIDDEN = (
    "temperature",
    "top_p",
    "top_k",
    "tools",
    "tool_choice",
    "thinking",
    "betas",
    "fallbacks",
)
ONE_SAMPLE_COST = (120 * 1.0 + 10 * 5.0) / 1e6  # default synthetic usage priced at Haiku rates


@pytest.fixture(scope="module")
def a3():
    return real_doc(A3_ID)


def run(responses_or_responder, doc, *, budget=None, count=1000, category="sla", timeout_s=30):
    if callable(responses_or_responder):
        client = FakeAnthropic(responder=responses_or_responder, count=count)
    else:
        client = FakeAnthropic(responses=responses_or_responder, count=count)
    budget = budget if budget is not None else Budget(limit_usd=None)
    gate = HaikuGate(client, HAIKU, budget, timeout_s=timeout_s)
    decision = gate.decide(QUESTIONS[category], doc, CTX)
    return decision, client, budget


def system_text(kwargs):
    system = kwargs["system"]
    if isinstance(system, str):
        return system
    return "".join(block["text"] for block in system)


def user_text(kwargs):
    [msg] = kwargs["messages"]
    assert msg["role"] == "user"
    content = msg["content"]
    if isinstance(content, str):
        return content
    return "".join(block["text"] for block in content if block.get("type") == "text")


def test_name_and_policy():
    assert GATE_POLICY == {"samples": 3, "skip": "unanimous_false"}
    assert HaikuGate(FakeAnthropic(), HAIKU, Budget(None)).name == "haiku"


def test_request_shape(a3):
    decision, client, _ = run([gate_message("no")] * 3, a3, timeout_s=17)
    assert len(client.calls) == GATE_POLICY["samples"] == 3
    for kw in client.calls:
        assert kw["model"] == HAIKU
        assert kw["max_tokens"] == 64
        assert kw["timeout"] == 17
        assert system_text(kw).strip() == SYSTEM.strip()
        assert kw["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
        for key in FORBIDDEN:
            assert key not in kw, key
        assert "extra_headers" not in kw
    assert decision.backend == "haiku"
    assert decision.tier == "classifier"
    assert decision.question == "touches_sla"
    assert decision.evidence == ()


def test_plain_messages_api_not_beta(a3):
    client = FakeAnthropic(responses=[gate_message("no")] * 3)
    beta_calls = []
    client.beta.messages.create = lambda **kw: beta_calls.append(kw)
    HaikuGate(client, HAIKU, Budget(None)).decide(QUESTIONS["sla"], a3, CTX)
    assert beta_calls == []
    assert len(client.calls) == 3


def test_user_message_has_definition_and_every_operative_segment(a3):
    _, client, _ = run([gate_message("no")] * 3, a3)
    text = user_text(client.calls[0])
    assert QUESTIONS["sla"].definition in text
    for seg in a3.segments:
        line = f"[{seg.id}] {a3.segment_text(seg.id)}"
        if 43 <= int(seg.id[1:]) <= 57:  # signature block p0043-p0057
            assert f"[{seg.id}]" not in text
        else:
            assert line in text, seg.id


def test_signature_block_excluded_and_exhibits_kept_on_1a():
    a1 = real_doc(A1_ID)
    _, client, _ = run([gate_message("no")] * 3, a1)
    text = user_text(client.calls[0])
    assert "[p0063]" not in text and "[p0084]" not in text
    assert f"[p0105] {a1.segment_text('p0105')}" in text


def test_count_tokens_precedes_every_create_with_the_complete_request(a3):
    log = []

    def count(kw):
        log.append(("count", kw))
        return 1000

    def responder(kw):
        log.append(("create", kw))
        return gate_message("no")

    run(responder, a3, count=count)
    assert [k for k, _ in log] == ["count", "create"] * 3
    for (_, ckw), (_, kw) in zip(log[0::2], log[1::2], strict=True):
        for key in ("model", "system", "messages", "output_config"):
            assert ckw[key] == kw[key], key


def test_unanimous_no(a3):
    d, _, budget = run([gate_message("no")] * 3, a3)
    assert d.samples == (False, False, False)
    assert d.answer is False
    assert d.confidence == 1.0
    assert d.error is None
    assert d.run_check is False
    assert (d.input_tokens, d.output_tokens) == (360, 30)
    assert d.cost_usd == pytest.approx(3 * ONE_SAMPLE_COST)
    assert budget.spent_usd == pytest.approx(3 * ONE_SAMPLE_COST)
    assert isinstance(d.latency_ms, int) and d.latency_ms >= 0


@pytest.mark.parametrize(
    ("answers", "samples", "answer", "confidence"),
    [
        (["yes", "yes", "yes"], (True, True, True), True, 1.0),
        (["no", "no", "yes"], (False, False, True), False, 2 / 3),
        (["yes", "no", "yes"], (True, False, True), True, 2 / 3),
    ],
)
def test_majority_and_confidence(a3, answers, samples, answer, confidence):
    d, _, _ = run([gate_message(a) for a in answers], a3)
    assert d.samples == samples
    assert d.answer is answer
    assert d.confidence == pytest.approx(confidence)
    assert d.run_check is True
    assert d.error is None


def test_tie_between_non_failed_samples_answers_yes(a3):
    refused = message(None, stop_reason="refusal", model=HAIKU)
    d, _, _ = run([gate_message("no"), refused, gate_message("yes")], a3)
    assert d.samples == (False, None, True)
    assert d.answer is True
    assert d.run_check is True


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        (message(None, stop_reason="refusal", model=HAIKU), "refused"),
        (message('{"answer": "no"}', stop_reason="max_tokens", model=HAIKU), "truncated"),
        (message("not json", model=HAIKU), "invalid"),
        (message('{"answer": "maybe"}', model=HAIKU), "invalid"),
        (TimeoutError("read timed out"), "timeout"),
        (RuntimeError(f"boom {SENTINEL_KEY}"), "RuntimeError"),
    ],
)
def test_failed_sample_is_none_and_fails_open(a3, bad, code):
    d, client, _ = run([gate_message("no"), bad, gate_message("no")], a3)
    assert len(client.calls) == 3
    assert d.samples == (False, None, False)
    assert d.answer is False
    assert d.confidence == pytest.approx(2 / 3)
    assert d.error == code
    assert d.run_check is True
    assert SENTINEL_KEY not in repr(d)


def test_api_timeout_error_maps_to_timeout(a3):
    import anthropic
    import httpx

    err = anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com"))
    d, _, _ = run([gate_message("no"), gate_message("no"), err], a3)
    assert d.samples == (False, False, None)
    assert d.error == "timeout"
    assert d.run_check is True


def test_first_error_code_is_kept(a3):
    d, _, _ = run([message("nope", model=HAIKU), TimeoutError(), gate_message("no")], a3)
    assert d.error == "invalid"


def test_usage_settled_before_parse_on_refusal(a3):
    refused = message(None, stop_reason="refusal", model=HAIKU, usage_=usage(inp=200, out=3))
    _, _, budget = run([gate_message("no"), refused, gate_message("no")], a3)
    expected = 2 * ONE_SAMPLE_COST + (200 * 1.0 + 3 * 5.0) / 1e6
    assert budget.spent_usd == pytest.approx(expected)
    assert budget.reserved_usd == pytest.approx(0.0, abs=1e-12)


def test_exception_charges_the_full_reservation(a3):
    _, _, budget = run([gate_message("no"), TimeoutError(), gate_message("no")], a3, count=1000)
    reservation = (1000 * 1.25 + 64 * 5.0) / 1e6
    assert budget.spent_usd == pytest.approx(2 * ONE_SAMPLE_COST + reservation)


def test_reservation_uses_count_and_max_tokens(a3):
    budget = Budget(limit_usd=(5000 * 1.25 + 64 * 5.0) / 1e6)
    d, client, _ = run([gate_message("no")] * 3, a3, budget=budget, count=5000)
    assert len(client.calls) == 1  # the second reservation no longer fits
    assert d.samples == (False, None, None)
    assert d.error == "budget_stop"
    assert d.run_check is True


def test_exhausted_budget_makes_no_call(a3):
    d, client, _ = run([gate_message("no")] * 3, a3, budget=Budget(limit_usd=0.0))
    assert client.calls == []
    assert d.samples == (None, None, None)
    assert d.answer is None
    assert d.confidence in (None, 0.0)
    assert d.error == "budget_stop"
    assert d.run_check is True


def test_count_tokens_failure_means_no_call(a3):
    budget = Budget(limit_usd=1.0)
    d, client, _ = run([gate_message("no")] * 3, a3, budget=budget, count=RuntimeError("down"))
    assert client.calls == []
    assert d.samples == (None, None, None)
    assert d.error == "budget_stop"
    assert d.run_check is True
    assert budget.exhausted is not None


def test_jev_unavailable_by_default(a3, monkeypatch):
    monkeypatch.delenv("OG_JEV_ENABLED", raising=False)
    monkeypatch.delenv("OG_JEV_URL", raising=False)
    gate = JevGate()
    assert gate.name == "jev"
    d = gate.decide(QUESTIONS["price"], a3, CTX)
    assert isinstance(d, GateDecision)
    assert d.answer is None
    assert d.error == "unavailable"
    assert d.run_check is True
    assert d.backend == "jev"
    assert d.samples == ()


@pytest.mark.parametrize(
    "env",
    [
        {"OG_JEV_ENABLED": "false", "OG_JEV_URL": "http://127.0.0.1:9"},
        {"OG_JEV_ENABLED": "true"},
        {"OG_JEV_ENABLED": "true", "OG_JEV_URL": "http://127.0.0.1:9"},
    ],
)
def test_jev_never_touches_the_network_in_this_wave(a3, monkeypatch, env):
    monkeypatch.delenv("OG_JEV_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    def no_socket(*a, **kw):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    d = JevGate().decide(QUESTIONS["price"], a3, CTX)
    assert d.error == "unavailable"
    assert d.run_check is True
