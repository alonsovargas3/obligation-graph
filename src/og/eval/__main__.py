"""Score CLI: `python -m og.eval extract ...` writes an extraction results JSON.

The results record the score against the reference set plus the run's honesty
signals: proposal grounding, integrity, drops, corrections, cost, and calls.
Under a `sampled` reference set (rev 2.2 R2-8) precision and F1 cannot be
supported, so they are nulled and only a precision lower bound is reported
(unlabeled true obligations count as false positives).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from og.eval.gold import load_gold
from og.eval.score import pred_from_db, score
from og.store.db import connect
from og.textdoc import TextDoc

METRIC = "m1"


def _find_record(log_path: str, run_id: str) -> dict[str, Any] | None:
    """The log record whose run_id matches the DB's latest run for the doc."""
    path = Path(log_path)
    if not path.exists():
        return None
    found: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("run_id") == run_id:
            found = rec
    return found


def _calls(rec: dict[str, Any] | None) -> list[dict[str, Any]]:
    if rec is None:
        return []
    calls: list[dict[str, Any]] = []
    for chunk in rec.get("chunks", []):
        for attempt in chunk.get("attempts", []):
            calls.append(
                {
                    "chunk_id": chunk.get("chunk_id"),
                    "model": attempt.get("model"),
                    "input_tokens": attempt.get("input_tokens"),
                    "output_tokens": attempt.get("output_tokens"),
                    "cache_read_tokens": attempt.get("cache_read_tokens"),
                    "cache_write_tokens": attempt.get("cache_write_tokens"),
                    "refused": attempt.get("refused"),
                    "latency_ms": chunk.get("latency_ms"),
                    "cache_hit": chunk.get("cache_hit"),
                }
            )
    return calls


def _apply_sampled(score_dict: dict[str, Any]) -> None:
    """R2-8: null precision and F1, keep recall, add a precision lower bound."""
    lower = {
        "micro": score_dict["micro"]["precision"],
        "macro": score_dict["macro"]["precision"],
    }
    blocks = [score_dict["micro"], score_dict["macro"], *score_dict["per_type"].values()]
    for block in blocks:
        block["precision"] = None
        block["f1"] = None
    score_dict["precision_lower_bound"] = lower


def _run_extract(args: argparse.Namespace) -> int:
    text_path = args.text or f"data/text/{args.doc}.json"
    doc = TextDoc.load(text_path)
    con = connect(args.db)

    row = con.execute(
        "SELECT run_id, prompt_version, textdoc_sha256 FROM extraction_run"
        " WHERE source_id = ? ORDER BY id DESC LIMIT 1",
        (args.doc,),
    ).fetchone()
    if row is None:
        print(f"og.eval: no extraction run for {args.doc} in {args.db}", file=sys.stderr)
        return 2
    run_id, prompt_version, td_sha = row

    rec = _find_record(args.log, run_id)
    integrity = con.execute(
        "SELECT COUNT(*) FROM visible_obligation v WHERE v.agreement_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM clause_ref c WHERE c.obligation_id = v.id"
        " AND c.grounded = 1 AND c.agreement_id = v.agreement_id)",
        (args.doc,),
    ).fetchone()[0]

    out: dict[str, Any] = {
        "metric": METRIC,
        "prompt_version": prompt_version,
        "doc_id": args.doc,
        "textdoc_sha256": td_sha,
        "score": None,
        "proposal_grounding": None,
        "integrity": integrity,
        "drops_by_reason": {},
        "corrections_by_field": {},
        "cost_usd": None,
        "cost_basis": None,
        "calls": [],
    }
    if rec is not None:
        proposed = rec.get("proposed")
        verified = rec.get("verified")
        out["proposal_grounding"] = verified / proposed if proposed else None
        out["drops_by_reason"] = dict(
            Counter(
                d["reason"] for d in rec.get("drops", []) if isinstance(d, dict) and d.get("reason")
            )
        )
        out["corrections_by_field"] = dict(
            Counter(
                c["field"]
                for c in rec.get("corrections", [])
                if isinstance(c, dict) and c.get("field")
            )
        )
        out["cost_usd"] = rec.get("cost_usd")
        out["cost_basis"] = rec.get("cost_basis")
        out["calls"] = _calls(rec)

    if args.gold:
        try:
            gold = load_gold(args.gold, doc)
        except ValueError as e:
            print(f"og.eval: gold rejected: {e.args[0]}", file=sys.stderr)
            return 2
        score_dict = score(gold.obligations, pred_from_db(con, args.doc)).as_dict()
        if gold.scope == "sampled":
            _apply_sampled(score_dict)
        out["score"] = score_dict
    con.close()

    payload = json.dumps(out, indent=2) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="og.eval", description="Score extractions against the reference set"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="score one document's extraction snapshot")
    extract.add_argument("--doc", required=True, help="document id (source and agreement id)")
    extract.add_argument("--db", default="data/graph.db", help="graph db path")
    extract.add_argument("--text", default=None, help="TextDoc json (default data/text/<doc>.json)")
    extract.add_argument("--log", default="logs/extract_runs.jsonl", help="extraction run log")
    extract.add_argument(
        "--gold", default=None, help="reference set yaml (skips scoring if omitted)"
    )
    extract.add_argument("--out", default=None, help="results json path (default stdout)")
    args = parser.parse_args(argv)
    if args.command == "extract":
        return _run_extract(args)
    parser.error(f"unknown command: {args.command}")
    return 2
