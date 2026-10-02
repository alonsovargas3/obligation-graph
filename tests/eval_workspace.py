"""Test helper (wave 4 Task 34): a workspace built from the real graph fixture.

Copies tests/fixtures/graph/real_v4.db and its TextDocs, the committed reference sets,
and the committed wave 2 extraction summary into a tmp workspace, writes a SYNTHETIC
extraction run log whose run ids match the fixture's extraction runs, and writes the
results manifest (shape documented in tests/test_eval_all.py).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "graph"
BASE = "constantcontact-2011-ex1041"
A1 = "constantcontact-2012-ex101"
A3 = "endurance-2017-ex106"
SUMMARY = "eval/results/2026-10-02-extract-summary.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extraction_runs(db: Path) -> dict[str, str]:
    con = sqlite3.connect(db)
    try:
        return dict(con.execute("SELECT source_id, run_id FROM extraction_run").fetchall())
    finally:
        con.close()


def write_log(root: Path, runs: dict[str, str]) -> dict[str, int]:
    """One SYNTHETIC record per current run, plus a stale record that must be ignored."""
    records = []
    for doc_id, run_id in sorted(runs.items()):
        drops = [{"reason": "not_found_in_section", "segment_id": "p0001", "span_text": "x"}]
        if doc_id == BASE:
            drops.append({"reason": "unknown_segment", "segment_id": "p9999", "span_text": "y"})
        records.append(
            {
                "run_id": run_id,
                "doc_id": doc_id,
                "complete": True,
                "proposed": 10,
                "verified": 9,
                "drops": drops,
                "corrections": [],
                "chunks": [],
                "cost_usd": 0.01,
                "incremental_cost_usd": 0.0,
            }
        )
    records.insert(
        0,
        {
            "run_id": "stale-run",
            "doc_id": BASE,
            "complete": True,
            "drops": [{"reason": "should_not_count"}] * 5,
            "corrections": [],
            "chunks": [],
        },
    )
    path = root / "logs" / "extract_runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return {"not_found_in_section": len(runs), "unknown_segment": 1}


def manifest_dict(root: Path) -> dict:
    gold = f"eval/gold/{BASE}.yaml"
    return {
        "version": 1,
        "extraction": {
            "doc_id": BASE,
            "gold": gold,
            "gold_sha256": sha256_file(root / gold),
            "historical_summary": SUMMARY,
            "historical_summary_sha256": sha256_file(root / SUMMARY),
        },
        "change": [
            {
                "doc_id": co,
                "gold": f"eval/gold/change/{co}.yaml",
                "gold_sha256": sha256_file(root / f"eval/gold/change/{co}.yaml"),
            }
            for co in (A1, A3)
        ],
    }


def build(root: Path) -> dict:
    """Populate `root`; return {"manifest": path, "expected_drops": {...}, "runs": {...}}."""
    (root / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / "real_v4.db", root / "data" / "graph.db")
    shutil.copytree(FIX / "text", root / "data" / "text")
    shutil.copytree(REPO / "eval" / "gold", root / "eval" / "gold")
    (root / "eval" / "results").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / SUMMARY, root / SUMMARY)
    runs = extraction_runs(root / "data" / "graph.db")
    expected = write_log(root, runs)
    manifest = root / "eval" / "results" / "MANIFEST.json"
    manifest.write_text(json.dumps(manifest_dict(root), indent=2) + "\n", encoding="utf-8")
    return {"manifest": manifest, "expected_drops": expected, "runs": runs}
