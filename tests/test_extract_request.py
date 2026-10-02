import dataclasses
import hashlib
import json
import re
from pathlib import Path

from extract_fakes import build_doc

from og.extract.prompt import build_request, prompt_version, request_fingerprint
from og.extract.types import Chunk

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "prompts" / "extract_v1.md"
SCHEMA = ROOT / "prompts" / "extract_v1.schema.json"
CHUNK = Chunk("c0001", "d1", ["p0001"], "[p0001] Tenant shall pay rent.\n")


def req(**over):
    kw = {"model": "claude-sonnet-5-5", "effort": "high"}
    kw.update(over)
    return build_request(CHUNK, **kw)


def doc():
    return build_doc([(None, "Preamble", ["Tenant shall pay rent.", "Landlord shall deliver."])])


def test_prompt_version_format_and_value():
    v = prompt_version()
    assert re.fullmatch(r"extract_v1@[0-9a-f]{8}", v)
    digest = hashlib.sha256(PROMPT.read_bytes() + SCHEMA.read_bytes()).hexdigest()[:8]
    assert v == "extract_v1@" + digest


def test_build_request_exact_kwargs():
    r = req()
    assert set(r) == {
        "model",
        "max_tokens",
        "system",
        "messages",
        "output_config",
        "betas",
        "fallbacks",
    }
    assert r["model"] == "claude-sonnet-5-5"
    assert r["max_tokens"] == 16000
    assert r["system"] == [
        {
            "type": "text",
            "text": PROMPT.read_text(encoding="utf-8"),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert r["messages"] == [{"role": "user", "content": CHUNK.text}]
    assert r["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": json.loads(SCHEMA.read_text())},
    }
    assert r["betas"] == ["server-side-fallback-2026-07-01"]
    assert r["fallbacks"] == "default"


def test_build_request_never_sends_forbidden_params():
    r = req()
    for key in ("temperature", "top_p", "top_k", "thinking", "tools", "tool_choice", "stream"):
        assert key not in r


def test_build_request_passes_model_and_effort():
    r = req(model="claude-opus-5-5", effort="medium")
    assert r["model"] == "claude-opus-5-5"
    assert r["output_config"]["effort"] == "medium"


def test_build_request_is_json_serializable_and_stable():
    assert json.dumps(req(), sort_keys=True) == json.dumps(req(), sort_keys=True)


def test_fingerprint_stable():
    d = doc()
    assert request_fingerprint(req(), d) == request_fingerprint(req(), d)
    assert re.fullmatch(r"[0-9a-f]{64}", request_fingerprint(req(), d))


def test_fingerprint_sensitive_to_request():
    d = doc()
    assert request_fingerprint(req(), d) != request_fingerprint(req(effort="medium"), d)
    other = build_request(
        Chunk("c0001", "d1", ["p0001"], "[p0001] Tenant shall pay more rent.\n"),
        model="claude-sonnet-5-5",
        effort="high",
    )
    assert request_fingerprint(req(), d) != request_fingerprint(other, d)


def test_fingerprint_sensitive_to_source_pin():
    d = doc()
    d2 = dataclasses.replace(d, source_sha256="b" * 64)
    assert request_fingerprint(req(), d) != request_fingerprint(req(), d2)


def test_fingerprint_sensitive_to_textdoc_content():
    d = doc()
    d2 = dataclasses.replace(d, text=d.text.replace("rent", "Rent"))
    assert request_fingerprint(req(), d) != request_fingerprint(req(), d2)
