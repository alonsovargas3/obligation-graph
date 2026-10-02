"""Task 34: `python -m og.eval all` (make eval), the pinned aggregate (wave 4 rev 2 W4-13).

THE RESULTS MANIFEST BELOW IS THE CONTRACT FOR eval/results/MANIFEST.json:

  {
    "version": 1,
    "extraction": {
      "doc_id": "<agreement id scored against the extraction reference set>",
      "gold": "<workspace-relative path>", "gold_sha256": "<sha256 of the gold file>",
      "historical_summary": "<workspace-relative path of the committed wave 2 summary>",
      "historical_summary_sha256": "<sha256>"
    },
    "change": [{"doc_id": "<change order id>", "gold": "<path>", "gold_sha256": "<sha256>"}]
  }

CLI: og.eval all --manifest PATH [--db data/graph.db] [--text-dir data/text]
[--log logs/extract_runs.jsonl] [--out eval/results/<date>-aggregate.json]; every default
resolves from the workspace (og.paths). Exit 0 on success; exit 2 with one of these codes
in stderr on refusal: gold_sha_mismatch, missing_input, log_run_mismatch (a current
extraction run id has no log record), stale_change_run.

THE AGGREGATE SCHEMA (required keys; more are allowed):

  metric: "aggregate"; date; manifest_sha256
  extraction: {doc_id, prompt_version, textdoc_sha256, integrity,
               score: {micro, macro, per_type, fields, precision_lower_bound},
                      # sampled reference: micro/macro precision null;
                      # every per_type[t] has "precision_lower_bound";
                      # every fields[f] has "coverage"
               historical: {label: "historical", source: <summary path>, summary: <its JSON>}}
  drops: {by_reason: {reason: count}, extraction_run_ids: {doc_id: run_id}}
         # summed over the log records of the CURRENT extraction run of every document
  change: {<change order id>: {findings, gates, skips, disagreements,
           cost: {recorded_usd: {ungated, gated}, incremental_usd: {ungated, gated}}}}
  cost: {recorded_usd: {ungated, gated}, incremental_usd: {ungated, gated}}  # sums

semantic_projection(results) removes, at any depth, keys named date, run_id, pair_id,
baseline_run_id, extraction_run_ids, incremental_usd, incremental_cost_usd, manifest_sha256,
and any key ending in "wall_ms"; everything else (metrics, counts, recorded cost,
recorded latency) is kept. C10 compares fresh-clone results by this projection.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from eval_workspace import A1, A3, BASE, SUMMARY, build, manifest_dict

from og.eval.__main__ import main
from og.eval.all import semantic_projection


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OG_WORKSPACE", str(tmp_path))
    info = build(tmp_path)
    info["root"] = tmp_path
    return info


def run_all(ws, *extra):
    out = ws["root"] / "agg.json"
    rc = main(["all", "--manifest", str(ws["manifest"]), "--out", str(out), *extra])
    return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


def change_runs(root):
    con = sqlite3.connect(root / "data" / "graph.db")
    try:
        rows = con.execute(
            "SELECT change_order_id, mode, cost_usd, incremental_cost_usd FROM change_run"
        ).fetchall()
    finally:
        con.close()
    return {(co, mode): (cost, inc) for co, mode, cost, inc in rows}


def test_aggregate_schema(ws):
    rc, agg = run_all(ws)
    assert rc == 0
    assert agg["metric"] == "aggregate"
    assert set(agg) >= {"date", "manifest_sha256", "extraction", "drops", "change", "cost"}

    ext = agg["extraction"]
    assert ext["doc_id"] == BASE
    assert set(ext) >= {"prompt_version", "textdoc_sha256", "integrity", "score", "historical"}
    assert ext["integrity"] == 0
    score = ext["score"]
    assert set(score) >= {"micro", "macro", "per_type", "fields", "precision_lower_bound"}
    assert score["micro"]["precision"] is None and score["macro"]["precision"] is None
    assert score["per_type"]
    for block in score["per_type"].values():
        assert "precision_lower_bound" in block
    for block in score["fields"].values():
        assert "coverage" in block

    hist = ext["historical"]
    assert hist["label"] == "historical"
    assert hist["source"] == SUMMARY
    assert hist["summary"] == json.loads((ws["root"] / SUMMARY).read_text(encoding="utf-8"))

    assert set(agg["change"]) == {A1, A3}
    for block in agg["change"].values():
        assert set(block) >= {"findings", "gates", "skips", "disagreements", "cost"}


def test_drops_join_the_current_runs_only(ws):
    rc, agg = run_all(ws)
    assert rc == 0
    assert agg["drops"]["by_reason"] == ws["expected_drops"]
    assert agg["drops"]["extraction_run_ids"] == ws["runs"]


def test_change_metrics_and_costs_come_from_the_paired_runs(ws):
    rc, agg = run_all(ws)
    assert rc == 0
    assert agg["change"][A1]["findings"]["ungated"]["overall"]["tp"] == 8
    assert agg["change"][A3]["findings"]["ungated"]["overall"]["tp"] == 4
    kinds = {s["kind"] for co in (A1, A3) for s in agg["change"][co]["skips"]}
    assert kinds == {"confirmed_safe_skip"}
    runs = change_runs(ws["root"])
    for co in (A1, A3):
        cost = agg["change"][co]["cost"]
        for mode in ("ungated", "gated"):
            assert cost["recorded_usd"][mode] == pytest.approx(runs[(co, mode)][0])
            assert cost["incremental_usd"][mode] == pytest.approx(runs[(co, mode)][1])
    for mode in ("ungated", "gated"):
        assert agg["cost"]["recorded_usd"][mode] == pytest.approx(
            sum(runs[(co, mode)][0] for co in (A1, A3))
        )
        assert agg["cost"]["incremental_usd"][mode] == pytest.approx(
            sum(runs[(co, mode)][1] for co in (A1, A3))
        )


def test_default_output_path(ws):
    rc = main(["all", "--manifest", str(ws["manifest"])])
    assert rc == 0
    outs = sorted((ws["root"] / "eval" / "results").glob("*-aggregate.json"))
    assert len(outs) == 1


def rewrite_manifest(ws, mutate):
    data = manifest_dict(ws["root"])
    mutate(data)
    ws["manifest"].write_text(json.dumps(data), encoding="utf-8")


def test_gold_sha_mismatch_is_refused(ws, capsys):
    rewrite_manifest(ws, lambda d: d["change"][0].update(gold_sha256="0" * 64))
    rc, agg = run_all(ws)
    assert rc == 2 and agg is None
    assert "gold_sha_mismatch" in capsys.readouterr().err


def test_missing_input_is_refused(ws, capsys):
    rewrite_manifest(
        ws, lambda d: d["extraction"].update(historical_summary="eval/results/no.json")
    )
    rc, agg = run_all(ws)
    assert rc == 2 and agg is None
    assert "missing_input" in capsys.readouterr().err


def test_log_without_the_current_run_is_refused(ws, capsys):
    log = ws["root"] / "logs" / "extract_runs.jsonl"
    lines = [
        line
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["run_id"] != ws["runs"][A3]
    ]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rc, agg = run_all(ws)
    assert rc == 2 and agg is None
    assert "log_run_mismatch" in capsys.readouterr().err


def test_stale_change_run_is_refused(ws, capsys):
    con = sqlite3.connect(ws["root"] / "data" / "graph.db")
    con.execute(
        "UPDATE extraction_run SET textdoc_sha256 = ? WHERE source_id = ?", ("0" * 64, BASE)
    )
    con.commit()
    con.close()
    rc, agg = run_all(ws)
    assert rc == 2 and agg is None
    assert "stale_change_run" in capsys.readouterr().err


def test_semantic_projection():
    results = {
        "metric": "aggregate",
        "date": "2026-10-02",
        "manifest_sha256": "a" * 64,
        "extraction": {"score": {"micro": {"recall": 0.8}}, "run_id": "r1"},
        "drops": {"by_reason": {"x": 2}, "extraction_run_ids": {"d": "r1"}},
        "change": {
            "co": {
                "pair_id": "p1",
                "baseline_run_id": "r2",
                "cost": {
                    "recorded_usd": {"gated": 0.3},
                    "incremental_usd": {"gated": 0.0},
                    "incremental_cost_usd": 0.0,
                    "recorded_latency_ms": 120,
                    "replay_wall_ms": 9,
                },
                "runs": [{"run_id": "r3", "tp": 4, "wall_ms": 5}],
            }
        },
    }
    projected = semantic_projection(results)
    assert projected == {
        "metric": "aggregate",
        "extraction": {"score": {"micro": {"recall": 0.8}}},
        "drops": {"by_reason": {"x": 2}},
        "change": {
            "co": {
                "cost": {"recorded_usd": {"gated": 0.3}, "recorded_latency_ms": 120},
                "runs": [{"tp": 4}],
            }
        },
    }
    assert semantic_projection(projected) == projected
    other = json.loads(json.dumps(results))
    other["date"] = "2027-01-01"
    other["change"]["co"]["cost"]["replay_wall_ms"] = 400
    other["change"]["co"]["cost"]["incremental_usd"]["gated"] = 1.0
    assert semantic_projection(other) == projected
    assert results["date"] == "2026-10-02"  # the input is not mutated
    other["change"]["co"]["cost"]["recorded_usd"]["gated"] = 0.31
    assert semantic_projection(other) != projected


def test_projection_of_real_aggregate_drops_volatile_fields(ws):
    rc, agg = run_all(ws)
    assert rc == 0
    text = json.dumps(semantic_projection(agg))
    for run_id in ws["runs"].values():
        assert run_id not in text
    assert "incremental_usd" not in text and '"date"' not in text
    assert Path(ws["root"] / "agg.json").exists()
