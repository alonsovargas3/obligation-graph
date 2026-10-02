"""Score CLI: ``python -m og.eval {extract,change,all,readme-tables}``.

`extract` writes an extraction results JSON: the score against the reference
set plus the run's honesty signals (proposal grounding, integrity, drops,
corrections, cost, and calls). Under a `sampled` reference set (rev 2.2 R2-8)
precision and F1 cannot be supported, so they are nulled and only a precision
lower bound is reported (unlabeled true obligations count as false
positives).

`change` (Task 20) scores one change order's paired ungated/gated runs
against the change reference set: findings per mode with cross-category
deduplication, value accuracy, gate metrics per backend with a
Clopper-Pearson bound, honest skip naming, disagreements, and cost. A stale
pair is refused (``stale_change_run``), never scored as an empty check.

`all` (Task 34, W4-13) builds the pinned aggregate from
eval/results/MANIFEST.json: extraction score and field coverage, grounding
drops joined to the current extraction runs, per-change-order findings, gate
metrics, honest skips, disagreements, and recorded vs incremental cost. It
refuses (exit 2) on a hash mismatch, a missing input, a run without a log
record, or a stale change run, and prints the same sections as tables.

`readme-tables` (W4-13/W4-14) renders the README's generated tables from an
aggregate file: `--check README` exits 1 on drift, `--write README` replaces
only the marked block.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from og.eval.all import Refusal, build_aggregate, integrity_count
from og.eval.change_gold import load_change_gold, read_change_chain
from og.eval.change_score import score_change
from og.eval.gold import load_gold
from og.eval.readme import END, START, render_tables
from og.eval.score import apply_sampled, pred_from_db, score
from og.paths import workspace
from og.store.db import connect
from og.textdoc import TextDoc

METRIC = "m1"
CHANGE_METRIC = "change"


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
    """R2-8: delegate to og.eval.score.apply_sampled (single implementation)."""
    apply_sampled(score_dict)


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
    integrity = integrity_count(con, args.doc)

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


def _run_change(args: argparse.Namespace) -> int:
    gold_path = args.gold or f"eval/gold/change/{args.doc}.yaml"
    try:
        chain = read_change_chain(gold_path)
    except (OSError, ValueError) as e:
        print(f"og.eval: cannot read gold: {e}", file=sys.stderr)
        return 2
    try:
        docs = {a: TextDoc.load(Path(args.text_dir) / f"{a}.json") for a in chain}
        gold = load_change_gold(gold_path, docs)
    except (OSError, ValueError, KeyError) as e:
        print(f"og.eval: gold rejected: {e}", file=sys.stderr)
        return 2

    con = connect(args.db)
    try:
        result = score_change(con, gold)
    except ValueError as e:
        print(f"og.eval: {e.args[0]}", file=sys.stderr)
        con.close()
        return 2
    con.close()

    out: dict[str, Any] = {
        "metric": CHANGE_METRIC,
        **result,
        "provenance": gold.provenance,
        "scope": gold.scope,
        "textdoc_sha256": gold.textdoc_sha256,
        "disclosures": [
            "the corpus has two related chain documents from one counterparty pair",
            "labels were drafted blind by one model and adjudicated by the coordinator;"
            " gate answers were user-spot-checked only where provenance says so",
            "the skip rule (unanimous 3/3 no) was pre-registered, not tuned on this set;"
            " there is no held-out calibration set",
            "old-side matching is by segment identity: a checker citing a different"
            " segment inside the same target range is scored as a mismatch",
        ],
    }
    payload = json.dumps(out, indent=2) + "\n"
    out_path = args.out or f"eval/results/{date.today().isoformat()}-change-{args.doc}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(payload, encoding="utf-8")
    return 0


def _workspace_path(value: str | None, default: str) -> Path:
    """Resolve a CLI path against the workspace (og.paths), not the cwd."""
    path = Path(value) if value else Path(default)
    return path if path.is_absolute() else workspace() / path


def _run_all(args: argparse.Namespace) -> int:
    """Build the pinned aggregate (W4-13); refuse before writing anything."""
    manifest = _workspace_path(args.manifest, args.manifest)
    db = _workspace_path(args.db, "data/graph.db")
    text_dir = _workspace_path(args.text_dir, "data/text")
    log = _workspace_path(args.log, "logs/extract_runs.jsonl")
    out = _workspace_path(args.out, f"eval/results/{date.today().isoformat()}-aggregate.json")
    try:
        agg = build_aggregate(
            manifest=manifest, db=db, text_dir=text_dir, log=log, root=workspace()
        )
    except Refusal as e:
        print(f"og.eval: {e.code}: {e.message}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(render_tables(agg))
    print(f"og.eval: aggregate written to {out}")
    return 0


def _latest_aggregate() -> Path:
    results_dir = workspace() / "eval" / "results"
    candidates = sorted(results_dir.glob("*-aggregate.json"))
    if not candidates:
        raise SystemExit(f"og.eval: no eval/results/*-aggregate.json under {workspace()}")
    return candidates[-1]


def _run_readme_tables(args: argparse.Namespace) -> int:
    """Render, check, or write the README's generated tables block (W4-14)."""
    results = _workspace_path(args.results, str(_latest_aggregate()))
    if not results.is_file():
        print(f"og.eval: results file not found: {results}", file=sys.stderr)
        return 2
    rendered = render_tables(json.loads(results.read_text(encoding="utf-8")))
    if args.check is None and args.write is None:
        sys.stdout.write(rendered)
        return 0
    target = Path(args.check or args.write)
    if not target.is_file():
        print(f"og.eval: README not found: {target}", file=sys.stderr)
        return 2
    text = target.read_text(encoding="utf-8")
    i0 = text.find(START)
    i1 = text.find(END, i0 + len(START)) if i0 != -1 else -1
    if args.write is not None:
        if i0 != -1 and i1 != -1:
            text = text[:i0] + START + "\n" + rendered + END + text[i1 + len(END) :]
        else:
            separator = (
                ""
                if not text or text.endswith("\n\n")
                else ("\n" if text.endswith("\n") else "\n\n")
            )
            text = text + separator + START + "\n" + rendered + END + "\n"
        target.write_text(text, encoding="utf-8")
        return 0
    if i0 == -1 or i1 == -1:
        print(f"og.eval: generated tables block missing from {target}", file=sys.stderr)
        return 1
    if text[i0 + len(START) : i1] != "\n" + rendered:
        print(
            f"og.eval: README tables differ from {results};"
            " run: python -m og.eval readme-tables --write",
            file=sys.stderr,
        )
        return 1
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
    change = sub.add_parser("change", help="score a change order's paired runs against the gold")
    change.add_argument("--doc", required=True, help="change order id (source and agreement id)")
    change.add_argument("--db", default="data/graph.db", help="graph db path")
    change.add_argument(
        "--gold", default=None, help="change gold yaml (default eval/gold/change/<doc>.yaml)"
    )
    change.add_argument(
        "--text-dir", default="data/text", help="directory of <agreement>.json TextDocs"
    )
    change.add_argument(
        "--out",
        default=None,
        help="results json path (default eval/results/<date>-change-<doc>.json)",
    )
    aggregate = sub.add_parser("all", help="build the pinned aggregate from the results manifest")
    aggregate.add_argument("--manifest", required=True, help="eval/results/MANIFEST.json")
    aggregate.add_argument("--db", default="data/graph.db", help="graph db path")
    aggregate.add_argument("--text-dir", default="data/text", help="directory of TextDocs")
    aggregate.add_argument("--log", default="logs/extract_runs.jsonl", help="extraction run log")
    aggregate.add_argument(
        "--out",
        default=None,
        help="results json path (default eval/results/<date>-aggregate.json)",
    )
    readme = sub.add_parser(
        "readme-tables", help="render, check, or write the README's generated tables"
    )
    readme.add_argument(
        "--results",
        default=None,
        help="aggregate json (default: latest eval/results/*-aggregate.json)",
    )
    readme.add_argument("--check", default=None, help="README to compare against (exit 1 on drift)")
    readme.add_argument("--write", default=None, help="README whose tables block to replace")
    args = parser.parse_args(argv)
    if args.command == "extract":
        return _run_extract(args)
    if args.command == "change":
        return _run_change(args)
    if args.command == "all":
        return _run_all(args)
    if args.command == "readme-tables":
        return _run_readme_tables(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
