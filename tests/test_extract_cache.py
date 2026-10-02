import json

import anthropic
import pytest
from extract_fakes import (
    FakeClient,
    build_doc,
    echo_responder,
    extractable_lines,
    filler,
    item,
    max_tokens_message,
    ok_message,
    raw_text_message,
    refusal_message,
)

from og.extract.cache import ResponseCache
from og.extract.chunk import chunk_doc
from og.extract.client import Extractor
from og.extract.prompt import build_request, prompt_version, request_fingerprint

FP = "ab" + "0" * 62


def payload(**over):
    p = {
        "items": [item()],
        "attempts": [{"model": "claude-sonnet-5-5", "input_tokens": 1}],
        "prompt_version": "extract_v1@00000000",
        "doc_id": "d1",
        "chunk_id": "c0001",
    }
    p.update(over)
    return p


def json_files(root):
    return sorted(p for p in root.rglob("*.json")) if root.exists() else []


# ---------- ResponseCache ----------


def test_cache_roundtrip_and_layout(tmp_path):
    c = ResponseCache(tmp_path / "cache")
    assert c.get(FP) is None
    c.put(FP, payload())
    assert c.get(FP) == payload()
    path = tmp_path / "cache" / FP[:2] / f"{FP}.json"
    assert path.is_file()
    assert sorted(p.name for p in path.parent.iterdir()) == [f"{FP}.json"]


def test_cache_rejects_unexpected_keys(tmp_path):
    c = ResponseCache(tmp_path / "cache")
    with pytest.raises(ValueError):
        c.put(FP, payload(headers={"x-api-key": "nope"}))
    assert json_files(tmp_path / "cache") == []


def test_cache_corrupt_file_is_a_miss_and_set_aside(tmp_path):
    c = ResponseCache(tmp_path / "cache")
    c.put(FP, payload())
    path = tmp_path / "cache" / FP[:2] / f"{FP}.json"
    path.write_text("{not json", encoding="utf-8")
    assert c.get(FP) is None
    assert not path.exists()
    assert any(p.name.endswith(".corrupt") for p in path.parent.iterdir())


def test_cache_put_overwrites_atomically(tmp_path):
    c = ResponseCache(tmp_path / "cache")
    c.put(FP, payload(chunk_id="c0001"))
    c.put(FP, payload(chunk_id="c0002"))
    assert c.get(FP)["chunk_id"] == "c0002"
    assert len(list((tmp_path / "cache" / FP[:2]).iterdir())) == 1


# ---------- Extractor ----------


def four_chunk_doc():
    return build_doc(
        [
            (None, "Preamble", ["This LEASE is made between Landlord Co and Tenant Co."]),
            ("1.1", "Rent", [filler("r", 450)]),
            ("1.2", "Term", [filler("t", 450)]),
            ("1.3", "Notices", [filler("n", 450)]),
        ]
    )


def make(client, cache, **kw):
    kw.setdefault("model", "claude-sonnet-5-5")
    kw.setdefault("effort", "high")
    kw.setdefault("max_chars", 500)
    return Extractor(client, cache, **kw)


def test_extract_ok_calls_once_per_chunk_with_built_requests(tmp_path):
    d = four_chunk_doc()
    chunks = chunk_doc(d, max_chars=500)
    assert len(chunks) == 4
    client = FakeClient(responder=echo_responder)
    res = make(client, ResponseCache(tmp_path / "c")).extract(d)
    assert res.complete and res.doc_id == "d1" and res.prompt_version == prompt_version()
    assert [o.status for o in res.outcomes] == ["ok"] * 4
    assert [o.chunk_id for o in res.outcomes] == [c.chunk_id for c in chunks]
    expected = [build_request(c, model="claude-sonnet-5-5", effort="high") for c in chunks]
    assert client.calls == expected
    for o, req in zip(res.outcomes, expected, strict=True):
        assert o.request_fingerprint == request_fingerprint(req, d)
        assert o.cache_hit is False
        assert isinstance(o.latency_ms, int) and o.latency_ms >= 0
        assert o.attempts and o.attempts[0].model == "claude-sonnet-5-5"
    shall_lines = [t for r in expected for _, t in extractable_lines(r) if "shall" in t]
    assert [i.span_text for i in res.items] == shall_lines
    assert len(res.items) == 3


def test_cache_hit_avoids_calls(tmp_path):
    d = four_chunk_doc()
    cache = ResponseCache(tmp_path / "c")
    first = make(FakeClient(responder=echo_responder), cache).extract(d)
    client = FakeClient(responder=echo_responder)
    second = make(client, cache).extract(d)
    assert client.calls == []
    assert all(o.cache_hit for o in second.outcomes)
    assert second.items == first.items
    assert second.complete


def test_failure_statuses_and_nothing_failed_is_cached(tmp_path):
    d = four_chunk_doc()
    api_error = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
    client = FakeClient(
        [refusal_message(), max_tokens_message(), raw_text_message("not json"), api_error]
    )
    cache = ResponseCache(tmp_path / "c")
    res = make(client, cache).extract(d)
    assert [o.status for o in res.outcomes] == ["refused", "truncated", "invalid", "error"]
    assert res.outcomes[3].error == "APIConnectionError"
    assert all(o.items == [] for o in res.outcomes)
    assert not res.complete
    assert json_files(tmp_path / "c") == []
    again = FakeClient(responder=echo_responder)
    assert make(again, cache).extract(d).complete
    assert len(again.calls) == 4


def test_mixed_outcome_is_incomplete_but_ok_chunks_cached(tmp_path):
    d = four_chunk_doc()
    client = FakeClient([ok_message([]), refusal_message(), ok_message([]), ok_message([])])
    cache = ResponseCache(tmp_path / "c")
    res = make(client, cache).extract(d)
    assert [o.status for o in res.outcomes] == ["ok", "refused", "ok", "ok"]
    assert not res.complete
    assert len(json_files(tmp_path / "c")) == 3


def test_no_cache_bypasses_canonical_cache_and_archives(tmp_path):
    d = four_chunk_doc()
    cache = ResponseCache(tmp_path / "c")
    make(FakeClient(responder=echo_responder), cache).extract(d)
    before = [(p, p.read_bytes()) for p in json_files(tmp_path / "c")]
    client = FakeClient(responder=echo_responder)
    res = make(client, cache, no_cache=True, archive_dir=tmp_path / "arch").extract(d)
    assert len(client.calls) == 4
    assert res.complete and not any(o.cache_hit for o in res.outcomes)
    assert [(p, p.read_bytes()) for p in json_files(tmp_path / "c")] == before
    assert len(json_files(tmp_path / "arch")) >= 4


def test_no_cache_without_archive_writes_nothing(tmp_path):
    d = four_chunk_doc()
    cache = ResponseCache(tmp_path / "c")
    make(FakeClient(responder=echo_responder), cache, no_cache=True).extract(d)
    assert json_files(tmp_path / "c") == []


def test_cached_payload_holds_no_request_material(tmp_path):
    d = four_chunk_doc()
    make(FakeClient(responder=echo_responder), ResponseCache(tmp_path / "c")).extract(d)
    for p in json_files(tmp_path / "c"):
        data = json.loads(p.read_text(encoding="utf-8"))
        assert set(data) <= {"items", "attempts", "prompt_version", "doc_id", "chunk_id"}
        assert "system" not in p.read_text(encoding="utf-8")
