import hashlib
import json

import pytest
import yaml

from og.eval.__main__ import main
from og.store.db import connect
from og.textdoc import Page, Section, Segment, TextDoc

TEXT = "1. Tenant shall pay Base Rent of $54,000 per month."
QUOTE = "Tenant shall pay Base Rent of $54,000 per month."
Q0 = TEXT.index(QUOTE)
DOC = TextDoc(
    "d1",
    "raw-sha",
    TEXT,
    [Section("s0001", "1", "Rent", 0, len(TEXT), None)],
    [Page(1, 0, len(TEXT))],
    [Segment("p0001", "s0001", 1, 0, len(TEXT))],
)
TEXTDOC_SHA = hashlib.sha256(DOC.to_json().encode()).hexdigest()

ATTEMPT = {
    "model": "claude-sonnet-5-5",
    "input_tokens": 1000,
    "output_tokens": 200,
    "cache_read_tokens": 0,
    "cache_write_tokens": 900,
    "refused": False,
}


def log_record(run_id, **kw):
    rec = {
        "run_id": run_id,
        "doc_id": "d1",
        "prompt_version": "extract_v1@abc12345",
        "textdoc_sha256": TEXTDOC_SHA,
        "complete": True,
        "proposed": 5,
        "verified": 3,
        "chunks": [
            {
                "chunk_id": "c0001",
                "status": "ok",
                "cache_hit": False,
                "latency_ms": 1200,
                "attempts": [ATTEMPT],
            }
        ],
        "drops": [
            {"reason": "not_found_in_section", "segment_id": "p0001", "span_text": "a"},
            {"reason": "not_found_in_section", "segment_id": "p0001", "span_text": "b"},
            {"reason": "unknown_segment", "segment_id": "p0099", "span_text": "c"},
        ],
        "corrections": [
            {"field": "amount", "reason": "amount_not_in_quote", "segment_id": "p0001"}
        ],
        "stats": {"obligations": 1},
        "cost_usd": 0.0123,
        "cost_basis": "PRICES_2026_10",
    }
    rec.update(kw)
    return rec


@pytest.fixture
def setup(tmp_path):
    db = tmp_path / "g.db"
    con = connect(db)
    con.execute("INSERT INTO source(id,url,local_path,sha256) VALUES('d1','u','p','raw-sha')")
    con.execute("INSERT INTO agreement(id,title,type,source_id) VALUES('d1','Lease','lease','d1')")
    con.execute(
        "INSERT INTO extraction_run(run_id,source_id,prompt_version,model,textdoc_sha256)"
        " VALUES('r1','d1','extract_v1@abc12345','claude-sonnet-5-5',?)",
        (TEXTDOC_SHA,),
    )
    oid = con.execute(
        "INSERT INTO obligation(agreement_id,type,description,amount,currency,status)"
        " VALUES('d1','payment','pay rent',54000.0,'USD','active')"
    ).lastrowid
    con.execute(
        "INSERT INTO clause_ref(obligation_id,agreement_id,section,page,char_start,char_end,"
        "span_text,grounded) VALUES(?,'d1','1',1,?,?,?,1)",
        (oid, Q0, Q0 + len(QUOTE), QUOTE),
    )
    con.close()
    text = tmp_path / "d1.json"
    DOC.save(text)
    gold = tmp_path / "gold.yaml"
    gold.write_text(
        yaml.safe_dump(
            {
                "doc_id": "d1",
                "source_sha256": "raw-sha",
                "textdoc_sha256": TEXTDOC_SHA,
                "provenance": {"drafted_by": "m", "adjudicated_by": "c", "spot_checked": 0},
                "scope": "full_agreement",
                "obligations": [
                    {
                        "segment_id": "p0001",
                        "char_start": Q0,
                        "char_end": Q0 + len(QUOTE),
                        "span_text": QUOTE,
                        "type": "payment",
                        "owed_by": "Tenant",
                        "owed_to": "Landlord",
                        "description": "Pay rent.",
                        "amount": 54000,
                        "currency": "USD",
                        "due_date": None,
                        "anchor_event": None,
                        "offset_days": None,
                        "trigger": None,
                        "status": "active",
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    log = tmp_path / "extract_runs.jsonl"
    log.write_text(
        "\n".join(json.dumps(r) for r in [log_record("r0", proposed=9), log_record("r1")]) + "\n",
        encoding="utf-8",
    )
    return {"db": db, "text": text, "gold": gold, "log": log, "out": tmp_path / "out.json"}


def run_cli(s, gold=True):
    argv = ["extract", "--doc", "d1", "--db", str(s["db"]), "--text", str(s["text"])]
    argv += ["--log", str(s["log"]), "--out", str(s["out"])]
    if gold:
        argv += ["--gold", str(s["gold"])]
    assert main(argv) == 0
    return json.loads(s["out"].read_text(encoding="utf-8"))


def test_results_shape(setup):
    out = run_cli(setup)
    assert set(out) >= {
        "metric",
        "prompt_version",
        "doc_id",
        "textdoc_sha256",
        "score",
        "proposal_grounding",
        "integrity",
        "drops_by_reason",
        "corrections_by_field",
        "cost_usd",
        "cost_basis",
        "calls",
    }
    assert out["metric"] == "m1"
    assert out["doc_id"] == "d1"
    assert out["prompt_version"] == "extract_v1@abc12345"
    assert out["textdoc_sha256"] == TEXTDOC_SHA


def test_results_use_the_db_run_record(setup):
    out = run_cli(setup)
    assert out["proposal_grounding"] == pytest.approx(0.6)  # r1: 3 verified of 5 proposed
    assert out["drops_by_reason"] == {"not_found_in_section": 2, "unknown_segment": 1}
    assert out["corrections_by_field"] == {"amount": 1}
    assert out["cost_usd"] == pytest.approx(0.0123)
    assert out["cost_basis"] == "PRICES_2026_10"
    assert out["calls"] == [
        {
            "chunk_id": "c0001",
            "model": "claude-sonnet-5-5",
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_read_tokens": 0,
            "cache_write_tokens": 900,
            "refused": False,
            "latency_ms": 1200,
            "cache_hit": False,
        }
    ]


def test_score_and_integrity(setup):
    out = run_cli(setup)
    assert out["integrity"] == 0
    assert out["score"]["micro"]["tp"] == 1
    assert out["score"]["fields"]["amount"]["both_known_equal"] == 1


def test_without_gold_score_is_null(setup):
    assert run_cli(setup, gold=False)["score"] is None


def test_missing_run_record_gives_nulls(setup):
    setup["log"].write_text(json.dumps(log_record("r9")) + "\n", encoding="utf-8")
    out = run_cli(setup)
    assert out["proposal_grounding"] is None
    assert out["drops_by_reason"] == {}
    assert out["corrections_by_field"] == {}
    assert out["calls"] == []
    assert out["cost_usd"] is None
