import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml
from extract_fakes import SENTINEL_KEY, FakeClient, echo_responder, refusal_message

from og.extract.__main__ import main
from og.ingest import parse_html

FIX = Path(__file__).parent / "fixtures" / "ingest" / "lease_small.htm"
SHA = "c" * 64
DOC_ID = "lease_small"
RUN_KEYS = {
    "run_id",
    "doc_id",
    "prompt_version",
    "textdoc_sha256",
    "complete",
    "chunks",
    "drops",
    "corrections",
    "stats",
}
CHUNK_KEYS = {"chunk_id", "status", "cache_hit", "latency_ms", "attempts"}


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    monkeypatch.setenv("OG_EXTRACT_CHUNK_CHARS", "300")
    monkeypatch.delenv("OG_EXTRACT_MODEL", raising=False)
    monkeypatch.delenv("OG_EXTRACT_EFFORT", raising=False)
    doc = parse_html(FIX.read_text(encoding="utf-8"), DOC_ID, SHA)
    Path("data/text").mkdir(parents=True)
    doc.save(Path("data/text") / f"{DOC_ID}.json")
    write_sources(SHA)
    return tmp_path


def write_sources(sha):
    entry = {
        "id": DOC_ID,
        "url": "https://www.sec.gov/Archives/example/lease_small.htm",
        "filer": "Example Co",
        "form": "10-K",
        "filing_date": "2011-03-09",
        "exhibit": "10.1",
        "title": "Lease (synthetic fixture)",
        "is_form": False,
        "local_path": f"data/raw/{DOC_ID}.htm",
        "sha256": sha,
        "agreement_type": "lease",
        "amends": None,
        "effective_date": None,
    }
    Path("data").mkdir(exist_ok=True)
    Path("data/sources.yaml").write_text(yaml.safe_dump({"documents": [entry]}), encoding="utf-8")


def visible(db="data/graph.db"):
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT count(*) FROM visible_obligation").fetchone()[0]
    finally:
        con.close()


def runs(db="data/graph.db"):
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT run_id FROM extraction_run").fetchall()
    finally:
        con.close()


def log_records():
    path = Path("logs/extract_runs.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_complete_run_writes_graph_and_log(workdir):
    client = FakeClient(responder=echo_responder)
    assert main([], client=client) == 0
    assert len(client.calls) >= 2
    assert visible() == 2
    [rec] = log_records()
    assert set(rec) >= RUN_KEYS
    assert rec["doc_id"] == DOC_ID and rec["complete"] is True
    assert rec["chunks"] and all(set(c) >= CHUNK_KEYS for c in rec["chunks"])
    assert all(c["status"] == "ok" for c in rec["chunks"])


def test_rerun_replaces_snapshot_from_cache(workdir):
    assert main([], client=FakeClient(responder=echo_responder)) == 0
    first = runs()
    client = FakeClient(responder=echo_responder)
    assert main([], client=client) == 0
    assert client.calls == []
    assert visible() == 2
    assert len(runs()) == 1 and runs() != first
    a, b = log_records()
    assert a["run_id"] != b["run_id"]
    assert all(c["cache_hit"] for c in b["chunks"])


def test_refused_chunk_keeps_previous_snapshot(workdir):
    assert main([], client=FakeClient(responder=echo_responder)) == 0
    before = runs()
    shutil.rmtree("data/cache")
    calls = {"n": 0}

    def responder(kwargs):
        calls["n"] += 1
        return refusal_message() if calls["n"] == 2 else echo_responder(kwargs)

    assert main([], client=FakeClient(responder=responder)) == 3
    assert visible() == 2
    assert runs() == before
    last = log_records()[-1]
    assert last["complete"] is False
    assert "refused" in [c["status"] for c in last["chunks"]]


def test_pin_mismatch_fails_without_write(workdir):
    write_sources("d" * 64)
    client = FakeClient(responder=echo_responder)
    assert main([], client=client) == 3
    assert client.calls == []
    assert not Path("data/graph.db").exists() or visible() == 0


def test_no_cache_sample_is_isolated(workdir):
    client = FakeClient(responder=echo_responder)
    assert main(["--no-cache", "--runs-dir", "eval/runs/s1"], client=client) == 0
    assert not Path("data/graph.db").exists()
    assert visible(f"eval/runs/s1/{DOC_ID}.db") == 2
    assert not list(Path("data").rglob("cache/**/*.json"))


def test_doc_filter(workdir):
    client = FakeClient(responder=echo_responder)
    assert main(["--doc", "not-a-doc"], client=client) != 0
    assert client.calls == []


def test_sentinel_key_never_written(workdir):
    assert main([], client=FakeClient(responder=echo_responder)) == 0
    shutil.rmtree("data/cache")
    calls = {"n": 0}

    def responder(kwargs):
        calls["n"] += 1
        return refusal_message() if calls["n"] == 1 else echo_responder(kwargs)

    main([], client=FakeClient(responder=responder))
    main(["--no-cache", "--runs-dir", "eval/runs/s2"], client=FakeClient(responder=echo_responder))
    written = [p for p in workdir.rglob("*") if p.is_file()]
    assert written
    for p in written:
        assert SENTINEL_KEY.encode() not in p.read_bytes(), p
