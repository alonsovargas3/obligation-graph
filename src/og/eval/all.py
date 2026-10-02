"""The pinned aggregate: `python -m og.eval all` (wave 4 Task 34, rev 2 W4-13).

Reads only the inputs listed in ``eval/results/MANIFEST.json`` (documents,
gold files, and the committed historical summary, each pinned by sha256),
scores the extraction reference lease and every listed change order against
the stored runs, joins the grounding drops of the current extraction runs,
and writes one aggregate JSON that the README tables are generated from.

Refusals (exit 2) never write a partial file: a stale change pair
(``stale_change_run``), a hash mismatch (``gold_sha_mismatch``), a missing
input (``missing_input``), or a current extraction run without a log record
(``log_run_mismatch``) all abort before anything is written.

An optional ``timing`` manifest block (wave 5 W5-9) adds one score per timing
reference set (``eval/gold/timing/<name>.yaml``), each pinned by sha256 and
scored by ``og.eval.timing_score`` against the visible timing projection.

``semantic_projection`` drops the volatile fields (dates, run ids, pair ids,
wall times, incremental spend, the manifest hash) at any depth, so a
fresh-clone replay is compared by its metrics and recorded costs only (C10).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from og.eval.change_gold import load_change_gold, read_change_chain
from og.eval.change_score import score_change
from og.eval.gold import load_gold
from og.eval.score import apply_sampled, pred_from_db, score
from og.eval.timing_gold import load_timing_gold
from og.eval.timing_score import score_timing
from og.textdoc import TextDoc

METRIC = "aggregate"

# Keys a fresh-clone comparison must ignore (C10 semantic projection): identity
# and timing fields whose values differ between machines and runs.
_VOLATILE_KEYS = frozenset(
    {
        "date",
        "run_id",
        "pair_id",
        "baseline_run_id",
        "extraction_run_ids",
        "incremental_usd",
        "incremental_cost_usd",
        "manifest_sha256",
    }
)


def semantic_projection(results: Any) -> Any:
    """Copy `results` without volatile keys, at any depth.

    Removes keys named date, run_id, pair_id, baseline_run_id,
    extraction_run_ids, incremental_usd, incremental_cost_usd, or
    manifest_sha256, and any key ending in "wall_ms". Keeps every metric,
    count, recorded cost, and recorded latency. The input is not mutated and
    the projection is idempotent.
    """
    if isinstance(results, dict):
        return {
            k: semantic_projection(v)
            for k, v in results.items()
            if k not in _VOLATILE_KEYS and not k.endswith("wall_ms")
        }
    if isinstance(results, list):
        return [semantic_projection(v) for v in results]
    return results


@dataclass(frozen=True)
class Refusal(Exception):
    """A pinned input is missing, tampered, stale, or unjoinable."""

    code: str
    message: str


def integrity_count(con: sqlite3.Connection, doc_id: str) -> int:
    """Visible obligations of the document without a grounded same-agreement citation.

    Checked through the citation projection (rev 2.2): every visible obligation
    carries at least one visible_obligation_clause row, so this is 0 unless a
    view or writer bug breaks the grounding invariant.
    """
    return con.execute(
        "SELECT count(*) FROM visible_obligation v WHERE v.agreement_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM visible_obligation_clause c"
        " WHERE c.obligation_id = v.id AND c.agreement_id = v.agreement_id)",
        (doc_id,),
    ).fetchone()[0]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pinned(root: Path, rel: str, sha: str, what: str) -> Path:
    """Resolve a workspace-relative manifest path and verify its sha256 pin."""
    path = Path(rel)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        raise Refusal("missing_input", f"{what} not found: {rel}")
    actual = _sha256_file(path)
    if actual != sha:
        raise Refusal("gold_sha_mismatch", f"{what} sha256 {actual} != pinned {sha}: {rel}")
    return path


def _current_extraction_runs(con: sqlite3.Connection) -> dict[str, str]:
    """The latest extraction run id per document (highest rowid wins)."""
    runs: dict[str, str] = {}
    for source_id, run_id in con.execute(
        "SELECT source_id, run_id FROM extraction_run ORDER BY id"
    ).fetchall():
        runs[source_id] = run_id
    return runs


def _log_records(log_path: Path) -> dict[str, dict[str, Any]]:
    if not log_path.is_file():
        raise Refusal("missing_input", f"extraction run log not found: {log_path}")
    records: dict[str, dict[str, Any]] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("run_id"), str):
            records[rec["run_id"]] = rec
    return records


def _drops_block(
    con: sqlite3.Connection, log_path: Path
) -> dict[str, dict[str, int] | dict[str, str]]:
    """Grounding drops summed over the current extraction run of every document.

    Every current run id must have a log record; a run without one is a broken
    join, not an empty drop count (log_run_mismatch).
    """
    runs = _current_extraction_runs(con)
    if not runs:
        raise Refusal("missing_input", "no extraction runs in the graph db")
    records = _log_records(log_path)
    by_reason: Counter[str] = Counter()
    for doc_id, run_id in sorted(runs.items()):
        rec = records.get(run_id)
        if rec is None:
            raise Refusal(
                "log_run_mismatch",
                f"extraction run {run_id} of {doc_id} has no record in {log_path}",
            )
        for drop in rec.get("drops", []):
            if isinstance(drop, dict) and drop.get("reason"):
                by_reason[drop["reason"]] += 1
    return {"by_reason": dict(sorted(by_reason.items())), "extraction_run_ids": runs}


def _extraction_block(
    con: sqlite3.Connection, manifest: dict[str, Any], root: Path, text_dir: Path
) -> dict[str, Any]:
    ext = manifest["extraction"]
    doc_id = ext["doc_id"]
    gold_path = _pinned(root, ext["gold"], ext["gold_sha256"], "extraction gold")
    summary_path = _pinned(
        root, ext["historical_summary"], ext["historical_summary_sha256"], "historical summary"
    )

    row = con.execute(
        "SELECT prompt_version, textdoc_sha256 FROM extraction_run"
        " WHERE source_id = ? ORDER BY id DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    if row is None:
        raise Refusal("missing_input", f"no extraction run for {doc_id} in the graph db")
    prompt_version, td_sha = row

    text_path = text_dir / f"{doc_id}.json"
    if not text_path.is_file():
        raise Refusal("missing_input", f"TextDoc not found: {text_path}")
    doc = TextDoc.load(text_path)
    try:
        gold = load_gold(gold_path, doc)
    except ValueError as e:
        raise Refusal("gold_rejected", f"{gold_path}: {e.args[0]}") from None

    preds = pred_from_db(con, doc_id)
    score_dict = score(gold.obligations, preds).as_dict()
    # The pinned reference set is sampled: precision is a lower bound (R2-8),
    # per type as well as micro and macro.
    apply_sampled(score_dict)

    return {
        "doc_id": doc_id,
        "prompt_version": prompt_version,
        "textdoc_sha256": td_sha,
        "integrity": integrity_count(con, doc_id),
        "score": score_dict,
        "historical": {
            "label": "historical",
            "source": ext["historical_summary"],
            "summary": json.loads(summary_path.read_text(encoding="utf-8")),
        },
    }


def _change_block(con: sqlite3.Connection, gold_path: Path, text_dir: Path) -> dict[str, Any]:
    try:
        chain = read_change_chain(gold_path)
        docs = {a: TextDoc.load(text_dir / f"{a}.json") for a in chain}
        gold = load_change_gold(gold_path, docs)
    except OSError as e:
        raise Refusal("missing_input", f"{gold_path}: {e}") from None
    except (ValueError, KeyError) as e:
        raise Refusal("gold_rejected", f"{gold_path}: {e}") from None

    try:
        result = score_change(con, gold)
    except ValueError as e:
        code = e.args[0]
        if code == "stale_change_run":
            raise Refusal("stale_change_run", f"{gold.change_order_id}: run make change") from None
        raise Refusal(code, f"{gold.change_order_id}: {code}") from None

    cost = result["cost"]
    return {
        "change_order_id": result["change_order_id"],
        "chain": result["chain"],
        "findings": result["findings"],
        "values": result["values"],
        "gates": result["gates"],
        "skips": result["skips"],
        "disagreements": result["disagreements"],
        "cost": {
            "recorded_usd": {m: cost[m]["cost_usd"] for m in ("ungated", "gated")},
            "incremental_usd": {m: cost[m]["incremental_cost_usd"] for m in ("ungated", "gated")},
            "recorded_latency_ms": {m: cost[m]["latency_ms"] for m in ("ungated", "gated")},
            "gate_cost_usd": cost["gate_cost_usd"],
        },
    }


def _timing_block(
    con: sqlite3.Connection, entry: dict[str, Any], root: Path, text_dir: Path
) -> dict[str, Any]:
    """Score one timing reference set (wave 5 W5-9): pinned gold, then score_timing."""
    gold_path = _pinned(root, entry["gold"], entry["gold_sha256"], f"timing gold {entry['name']}")
    try:
        raw = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise Refusal("gold_rejected", f"{gold_path}: {e}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("documents"), dict):
        raise Refusal("gold_rejected", f"{gold_path}: bad_format")

    docs: dict[str, TextDoc] = {}
    for agreement_id in sorted(raw["documents"]):
        text_path = text_dir / f"{agreement_id}.json"
        if not text_path.is_file():
            raise Refusal("missing_input", f"TextDoc not found: {text_path}")
        try:
            docs[agreement_id] = TextDoc.load(text_path)
        except (OSError, ValueError) as e:
            raise Refusal("missing_input", f"cannot load {text_path}: {e}") from None

    try:
        gold = load_timing_gold(gold_path, docs)
    except ValueError as e:
        raise Refusal("gold_rejected", f"{gold_path}: {e.args[0]}") from None
    return score_timing(con, gold)


def build_aggregate(
    *, manifest: Path, db: Path, text_dir: Path, log: Path, root: Path
) -> dict[str, Any]:
    """Score every pinned input and return the aggregate dict (nothing written)."""
    if not manifest.is_file():
        raise Refusal("missing_input", f"manifest not found: {manifest}")
    try:
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise Refusal("missing_input", f"manifest is not JSON: {e}") from None
    if not isinstance(manifest_data, dict) or manifest_data.get("version") != 1:
        raise Refusal("missing_input", 'manifest must be {"version": 1, ...}')

    if not db.is_file():
        raise Refusal("missing_input", f"graph db not found: {db}")

    con = sqlite3.connect(db, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        extraction = _extraction_block(con, manifest_data, root, text_dir)
        drops = _drops_block(con, log)
        change: dict[str, dict[str, Any]] = {}
        for entry in manifest_data.get("change", []):
            gold_path = _pinned(
                root, entry["gold"], entry["gold_sha256"], f"change gold {entry['doc_id']}"
            )
            change[entry["doc_id"]] = _change_block(con, gold_path, text_dir)
        timing: dict[str, dict[str, Any]] = {}
        for entry in manifest_data.get("timing", []):
            timing[entry["name"]] = _timing_block(con, entry, root, text_dir)
    finally:
        con.close()

    cost = {
        "recorded_usd": {m: 0.0 for m in ("ungated", "gated")},
        "incremental_usd": {m: 0.0 for m in ("ungated", "gated")},
        "recorded_latency_ms": {m: 0 for m in ("ungated", "gated")},
        "change_orders": len(change),
    }
    for block in change.values():
        for key in ("recorded_usd", "incremental_usd", "recorded_latency_ms"):
            for mode in ("ungated", "gated"):
                cost[key][mode] += block["cost"][key][mode]

    return {
        "metric": METRIC,
        "date": date.today().isoformat(),
        "manifest_sha256": _sha256_file(manifest),
        "extraction": extraction,
        "drops": drops,
        "change": change,
        "timing": timing,
        "cost": cost,
    }
