"""Replay of real recorded responses (C1). Offline; fixtures under tests/fixtures/api/extract_v1."""

import json
import re
from pathlib import Path

import pytest
from anthropic.types.beta import BetaMessage

from og.extract.client import parse_response

FIX = Path(__file__).parent / "fixtures" / "api" / "extract_v1"
NAMES = sorted(p.stem for p in FIX.glob("*.json"))
LINE = re.compile(r"^\[(p\d{4})\] (.*)$")


def load(name):
    body = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    chunk = (FIX / f"{name}.chunk.txt").read_text(encoding="utf-8")
    return BetaMessage.model_validate(body), body, chunk


def chunk_lines(chunk):
    """Extractable [pNNNN] lines only; [ctx ...] context lines are excluded."""
    out = {}
    for line in chunk.splitlines():
        m = LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def test_fixtures_present():
    assert len(NAMES) == 3


@pytest.mark.parametrize("name", NAMES)
def test_recorded_response_parses(name):
    msg, body, _ = load(name)
    items, attempts = parse_response(msg)
    assert items, "a recorded chunk with operative text should yield items"
    assert body["stop_reason"] == "end_turn"


@pytest.mark.parametrize("name", NAMES)
def test_attempt_model_falls_back_to_message_model(name):
    """The live API reports usage.iterations[].model = null when no fallback ran."""
    msg, body, _ = load(name)
    assert body["usage"]["iterations"][0]["model"] is None
    _, attempts = parse_response(msg)
    assert [a.model for a in attempts] == [body["model"]]
    assert attempts[0].refused is False
    assert attempts[0].input_tokens == body["usage"]["input_tokens"]
    assert attempts[0].cache_read_tokens == body["usage"]["cache_read_input_tokens"]


@pytest.mark.parametrize("name", NAMES)
def test_recorded_quotes_come_from_their_cited_line(name):
    """Most proposals quote verbatim from the cited extractable line (whitespace-normalized).

    This measures the raw model behavior that verify() later enforces; it is not the
    invariant itself (verify drops anything that fails).
    """
    msg, _, chunk = load(name)
    items, _ = parse_response(msg)
    lines = chunk_lines(chunk)
    norm = lambda s: " ".join(s.split())  # noqa: E731
    ok = [
        i for i in items if i.segment_id in lines and norm(i.span_text) in norm(lines[i.segment_id])
    ]
    assert len(ok) >= 0.8 * len(items), [(i.segment_id, i.span_text[:60]) for i in items]
