"""Task 33: recorded-response replay (wave 4 rev 2 W4-4, W4-5; ADR-010).

Recorded model responses live under <workspace>/eval/recorded/{extract,change,gate}/
(og.replay.cache_dir). OG_REPLAY selects the mode: "on" (default) replays and records
misses; "strict" turns any miss into ReplayMiss / exit code 4 before any client is
constructed and never writes; "off" bypasses the recordings.

Behaviour tests use SYNTHETIC documents and the SYNTHETIC fakes in tests/extract_fakes.py
and tests/change_fakes.py. The conftest points OG_WORKSPACE at each test's tmp dir.

THE MANIFEST SHAPE BELOW IS THE CONTRACT FOR eval/recorded/MANIFEST.json (written in C9):

  {
    "version": 1,
    "documents": {
      "<doc_id>": {
        "source_sha256": "<sources.yaml pin>",
        "textdoc_sha256": "<canonical TextDoc hash, og.eval.gold.textdoc_sha256>",
        "settings": {"model": str, "effort": str, "chunk_chars": int, "max_tokens": int},
        "fingerprints": {"extract": [fp, ...], "change": [fp, ...], "gate": [fp, ...]}
      }
    },
    "payloads": {"<kind>/<fingerprint>": "<sha256 of the payload file bytes>"}
  }

Change and gate fingerprints are listed under the change order that produced them.

Latency and cost (W4-4): GateDecision.latency_ms is the sum of its samples' model-call
latencies (measured live, or the recorded latency_ms on replay). A change run record
carries recorded_latency_ms = sum of its check outcomes' latency_ms plus the latency_ms
of its classifier-tier gate decisions, and replay_wall_ms = this invocation's wall time.
cost_usd always includes the recorded gate cost; incremental_cost_usd counts only gate
decisions with cache_hit False and checks that were not cache hits. OG_REPLAY=off neither
reads nor writes recordings and needs no --runs-dir.
test_committed_manifest_lists_every_recorded_payload is a coordinator acceptance test:
it is red until C9 records the gate samples and writes the manifest.
"""

import hashlib
import json
import shutil
from pathlib import Path

import anthropic
import pytest
import yaml
from change_fakes import HAIKU, SENTINEL_KEY, FakeAnthropic, gate_message
from extract_fakes import FakeClient, echo_responder
from test_change_cli import (
    BASE,
    BASE_DOC,
    CO,
    CO_DOC,
    SKIP_ALL_CLASSIFIED,
    Router,
    records,
    write_sources,
)

from og.budget import Budget
from og.change.__main__ import main as change_main
from og.eval.gold import textdoc_sha256
from og.extract.__main__ import main as extract_main
from og.gates.haiku import GateCache, HaikuGate, gate_fingerprint
from og.gates.types import GateContext, load_questions
from og.pricing import price
from og.replay import ReplayMiss, cache_dir
from og.textdoc import TextDoc

REPO = Path(__file__).resolve().parents[1]
QUESTIONS = {q.category: q for q in load_questions()}
CONTEXT = GateContext(base_section_types={})


def payloads(kind):
    root = cache_dir(kind)
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.json") if not p.name.endswith(".corrupt"))


class Exploding:
    """A client whose every attribute access fails: proof that nothing touched it."""

    def __getattr__(self, name):
        raise AssertionError(f"client used in replay: {name}")


@pytest.fixture
def no_client_construction(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("anthropic.Anthropic constructed during replay")

    monkeypatch.setattr(anthropic, "Anthropic", refuse)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    monkeypatch.setenv("OG_EXTRACT_CHUNK_CHARS", "300")
    for var in (
        "OG_EXTRACT_MODEL",
        "OG_EXTRACT_EFFORT",
        "OG_GATE_MODEL",
        "OG_CHANGE_EFFORT",
        "OG_BUDGET_USD",
        "OG_JEV_ENABLED",
        "OG_JEV_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    Path("data/text").mkdir(parents=True)
    BASE_DOC.save(Path("data/text") / f"{BASE}.json")
    CO_DOC.save(Path("data/text") / f"{CO}.json")
    write_sources()
    return tmp_path


def extract_live():
    assert extract_main([], client=FakeClient(responder=echo_responder)) == 0


def change_live(router=None):
    router = router or Router(gate=SKIP_ALL_CLASSIFIED)
    client = FakeAnthropic(responder=router, count=1000)
    assert change_main(["--mode", "both"], client=client) == 0
    return client


# --- default directories (Task 33) -------------------------------------------------------


def test_extraction_records_under_the_workspace(workdir):
    extract_live()
    assert payloads("extract"), "extraction did not record under eval/recorded/extract"
    assert cache_dir("extract") == workdir / "eval" / "recorded" / "extract"
    assert not Path("data/cache").exists()


def test_change_records_checks_and_gate_samples(workdir):
    extract_live()
    change_live()
    assert len(payloads("change")) == 6  # one per category, ungated
    # Three classified categories reach Haiku, three samples each.
    assert len(payloads("gate")) == 9
    for p in payloads("gate"):
        data = json.loads(p.read_text(encoding="utf-8"))
        assert set(data) <= {"answer_text", "stop_reason", "attempts", "latency_ms"}
        assert set(data) >= {"answer_text", "attempts"}
        assert SENTINEL_KEY not in p.read_text(encoding="utf-8")


# --- mode "on": lazy client, $0 replay ------------------------------------------------------


def test_full_replay_constructs_no_client(workdir, no_client_construction):
    extract_live()
    first = change_live()
    assert first.calls
    shutil.rmtree("logs")
    Path("data/graph.db").unlink()
    assert extract_main([]) == 0
    assert change_main(["--mode", "both"]) == 0
    for rec in records():
        assert rec["incremental_cost_usd"] == 0.0
    extract_log = [
        json.loads(line)
        for line in Path("logs/extract_runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(r["incremental_cost_usd"] == 0.0 for r in extract_log)


def test_replayed_gated_run_keeps_recorded_cost_and_latency(workdir, no_client_construction):
    extract_live()
    change_live()
    live_ungated, live_gated = records()
    assert change_main(["--mode", "both"]) == 0
    replay_ungated, replay_gated = records()[-2:]
    for live, replay in ((live_ungated, replay_ungated), (live_gated, replay_gated)):
        assert replay["cost_usd"] == pytest.approx(live["cost_usd"])
        assert replay["incremental_cost_usd"] == 0.0
        assert replay["recorded_latency_ms"] == live["recorded_latency_ms"]
        assert isinstance(replay["replay_wall_ms"], int) and replay["replay_wall_ms"] >= 0
    # Gate overhead stays in the recorded cost of the gated run, never in its spend.
    assert live_gated["incremental_cost_usd"] > 0
    gate_decisions = [d for d in replay_gated["decisions"] if d["backend"] == "haiku"]
    assert gate_decisions and all(d["cache_hit"] for d in gate_decisions)


# --- mode "strict" --------------------------------------------------------------------------


def test_strict_extraction_miss_exits_4_before_any_client(
    workdir, monkeypatch, no_client_construction, capsys
):
    monkeypatch.setenv("OG_REPLAY", "strict")
    rc = extract_main([], client=Exploding())
    assert rc == 4
    assert "replay_miss " in capsys.readouterr().err
    assert not payloads("extract")
    assert not Path("eval/recorded").exists() or not any(Path("eval/recorded").rglob("*.json"))


def test_strict_change_miss_exits_4(workdir, monkeypatch, no_client_construction, capsys):
    extract_live()
    change_live()
    for p in payloads("gate"):
        p.unlink()
    before = sorted(str(p) for p in Path("eval/recorded").rglob("*"))
    monkeypatch.setenv("OG_REPLAY", "strict")
    rc = change_main(["--mode", "both"], client=Exploding())
    assert rc == 4
    assert "replay_miss " in capsys.readouterr().err
    assert sorted(str(p) for p in Path("eval/recorded").rglob("*")) == before


def test_strict_full_replay_succeeds(workdir, monkeypatch, no_client_construction):
    extract_live()
    change_live()
    monkeypatch.setenv("OG_REPLAY", "strict")
    Path("data/graph.db").unlink()
    assert extract_main([], client=Exploding()) == 0
    assert change_main(["--mode", "both"], client=Exploding()) == 0


# --- mode "off" -----------------------------------------------------------------------------


def test_off_bypasses_recordings(workdir, monkeypatch):
    extract_live()
    monkeypatch.setenv("OG_REPLAY", "off")
    before = [p.read_bytes() for p in payloads("extract")]
    client = FakeClient(responder=echo_responder)
    assert extract_main([], client=client) == 0
    assert client.calls, "OG_REPLAY=off must not replay recorded responses"
    assert [p.read_bytes() for p in payloads("extract")] == before


# --- the gate cache (W4-4) ------------------------------------------------------------------


def gate(client, budget, cache):
    return HaikuGate(client, model=HAIKU, budget=budget, timeout_s=30, cache=cache)


def test_gate_cache_hit_makes_no_reservation_and_no_call(tmp_path):
    cache = GateCache(tmp_path / "gate")
    live_client = FakeAnthropic(responses=[gate_message("no")] * 3, count=500)
    live = gate(live_client, Budget(None), cache).decide(QUESTIONS["sla"], CO_DOC, CONTEXT)
    assert len(live_client.calls) == 3 and live.cache_hit is False
    assert len(list((tmp_path / "gate").rglob("*.json"))) == 3

    budget = Budget(1.0)
    replay_client = FakeAnthropic(responses=[], count=500)
    replay = gate(replay_client, budget, cache).decide(QUESTIONS["sla"], CO_DOC, CONTEXT)
    assert replay_client.calls == [] and replay_client.count_calls == []
    assert budget.calls == 0 and budget.spent_usd == 0.0
    assert replay.cache_hit is True
    assert replay.samples == live.samples == (False, False, False)
    assert replay.run_check is False  # a replayed unanimous "no" is still a valid skip
    assert replay.input_tokens == live.input_tokens
    assert replay.output_tokens == live.output_tokens
    assert replay.cost_usd == pytest.approx(live.cost_usd)
    recorded = [json.loads(p.read_text()) for p in (tmp_path / "gate").rglob("*.json")]
    assert replay.latency_ms == sum(r["latency_ms"] for r in recorded)


def test_gate_partial_hit_is_not_a_cache_hit(tmp_path):
    cache = GateCache(tmp_path / "gate")
    gate(FakeAnthropic(responses=[gate_message("no")] * 3), Budget(None), cache).decide(
        QUESTIONS["sla"], CO_DOC, CONTEXT
    )
    sorted(p for p in (tmp_path / "gate").rglob("*.json"))[0].unlink()
    client = FakeAnthropic(responses=[gate_message("no")])
    decision = gate(client, Budget(None), cache).decide(QUESTIONS["sla"], CO_DOC, CONTEXT)
    assert len(client.calls) == 1
    assert decision.cache_hit is False


def test_failed_gate_samples_are_never_recorded(tmp_path):
    cache = GateCache(tmp_path / "gate")
    client = FakeAnthropic(responses=[gate_message("no"), TimeoutError("slow"), gate_message("no")])
    gate(client, Budget(None), cache).decide(QUESTIONS["sla"], CO_DOC, CONTEXT)
    assert len(list((tmp_path / "gate").rglob("*.json"))) == 2


def test_strict_gate_miss_raises_before_any_call(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_REPLAY", "strict")
    client = FakeAnthropic(responses=[])
    with pytest.raises(ReplayMiss):
        gate(client, Budget(None), GateCache(tmp_path / "gate")).decide(
            QUESTIONS["sla"], CO_DOC, CONTEXT
        )
    assert client.calls == [] and client.count_calls == []
    assert not (tmp_path / "gate").exists() or not any((tmp_path / "gate").rglob("*.json"))


def test_gate_fingerprint_identity():
    request = {
        "model": HAIKU,
        "system": "s",
        "messages": [{"role": "user", "content": "q"}],
        "output_config": {"format": {"type": "json_schema", "schema": {}}},
        "max_tokens": 64,
    }
    sha = "d" * 64
    keys = [gate_fingerprint(request, sha, i) for i in range(3)]
    assert len(set(keys)) == 3
    assert keys == [gate_fingerprint(dict(request), sha, i) for i in range(3)]
    assert gate_fingerprint({**request, "model": "other"}, sha, 0) != keys[0]
    assert gate_fingerprint({**request, "max_tokens": 65}, sha, 0) != keys[0]
    assert gate_fingerprint(request, "e" * 64, 0) != keys[0]
    assert all(len(k) == 64 and int(k, 16) >= 0 for k in keys)


def test_gate_recorded_cost_prices_its_attempts(tmp_path):
    cache = GateCache(tmp_path / "gate")
    decision = gate(FakeAnthropic(responses=[gate_message("no")] * 3), Budget(None), cache).decide(
        QUESTIONS["guarantee"], CO_DOC, CONTEXT
    )
    from og.extract.types import Attempt

    attempts = []
    for p in (tmp_path / "gate").rglob("*.json"):
        attempts += [Attempt(**a) for a in json.loads(p.read_text())["attempts"]]
    assert decision.cost_usd == pytest.approx(price(attempts)[0])


# --- the committed manifest (coordinator acceptance, C9) -----------------------------------


ALLOWED_KEYS = {
    "extract": {"items", "attempts", "prompt_version", "doc_id", "chunk_id"},
    "change": {
        "findings",
        "attempts",
        "prompt_version",
        "category",
        "request_fingerprint",
        "latency_ms",
    },
    "gate": {"answer_text", "stop_reason", "attempts", "latency_ms"},
}


def test_committed_manifest_lists_every_recorded_payload():
    root = REPO / "eval" / "recorded"
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    listed = manifest["payloads"]
    on_disk = {}
    for kind in ("extract", "change", "gate"):
        for p in sorted((root / kind).rglob("*.json")):
            assert not p.name.endswith(".corrupt"), p
            on_disk[f"{kind}/{p.stem}"] = hashlib.sha256(p.read_bytes()).hexdigest()
            data = json.loads(p.read_text(encoding="utf-8"))
            assert set(data) <= ALLOWED_KEYS[kind], p
            assert "sk-ant" not in p.read_text(encoding="utf-8"), p
    assert listed == on_disk
    assert any(k.startswith("gate/") for k in on_disk), "C9 records the gate samples"

    sources = yaml.safe_load((REPO / "data" / "sources.yaml").read_text(encoding="utf-8"))
    pins = {e["id"]: e["sha256"] for e in sources["documents"]}
    assert set(manifest["documents"]) == set(pins)
    texts = REPO / "tests" / "fixtures" / "graph" / "text"
    referenced = set()
    for doc_id, entry in manifest["documents"].items():
        assert entry["source_sha256"] == pins[doc_id]
        assert entry["textdoc_sha256"] == textdoc_sha256(TextDoc.load(texts / f"{doc_id}.json"))
        assert set(entry["settings"]) == {"model", "effort", "chunk_chars", "max_tokens"}
        for kind, fps in entry["fingerprints"].items():
            assert kind in ALLOWED_KEYS
            for fp in fps:
                assert f"{kind}/{fp}" in listed
                referenced.add(f"{kind}/{fp}")
    assert referenced == set(listed), "every payload belongs to a document"
