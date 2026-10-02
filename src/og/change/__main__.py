"""`python -m og.change`: gate, check, verify, and store every change order.

Each ``amends`` entry in data/sources.yaml is a change order. Its chain (the
base, then the corpus amendments of the same base filed earlier, then the
change order itself) is built against the current extraction snapshots; a
member without one exits 2 before any model call (run make extract). A run is
written only when every one of the six categories is a valid skip or an ok
check (plan rev 2 R5); otherwise the previous snapshot stays and the CLI exits
3. ``--mode both`` runs one paired evaluation: ungated first, then gated,
replaying the ungated run's check outcomes in memory (R7). ``--mode gated``
alone replays the stored ungated outcomes with an identical fingerprint. The
API budget is reserved before every call and sticky across documents and modes
(R6, rev 2.1 R2-3). Every run appends one allowlisted record to the JSONL log;
no credential, request header, or exception repr ever reaches a written file.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import anthropic
import yaml

from og.budget import Budget
from og.change.chain import BuiltChain, ChainError, build_gate_context, build_snapshot
from og.change.client import (
    Checker,
    build_request,
    prompt_version,
    request_fingerprint,
)
from og.change.types import ChangeRunInfo, Finding, SnapshotChanged
from og.change.verify import verify_findings
from og.change.writer import write_change_run
from og.gates.cascade import run_cascade
from og.gates.haiku import HaikuGate
from og.gates.rules import RulesGate
from og.gates.types import QUESTIONS_PATH, GateContext, GateDecision, Question, load_questions
from og.pricing import price
from og.store.db import connect

SOURCES_PATH = Path("data/sources.yaml")
LOG_PATH = Path("logs/change_runs.jsonl")
DEFAULT_DB = "data/graph.db"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAILED = 3

MODE_CHOICES = ("ungated", "gated", "both")

_CHAIN_MESSAGES = {
    "missing_extraction": "no current extraction run; run make extract first",
    "textdoc_changed": "extracted snapshot does not match data/text; re-run make extract",
    "missing_textdoc": "no TextDoc in data/text; run make ingest",
    "base_not_in_corpus": "base agreement is not pinned in data/sources.yaml",
}


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _new_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


def _question_set_sha256() -> str:
    return hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest()


def _budget_from_env() -> Budget | None:
    """None means the value is unusable (exit 2), not unlimited."""
    raw = os.environ.get("OG_BUDGET_USD")
    if raw is None or raw == "":
        return Budget(None)
    try:
        return Budget(float(raw))
    except ValueError:
        return None


def _append_log(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _attempt_record(attempt) -> dict[str, Any]:
    return {
        "model": attempt.model,
        "input_tokens": attempt.input_tokens,
        "output_tokens": attempt.output_tokens,
        "cache_read_tokens": attempt.cache_read_tokens,
        "cache_write_tokens": attempt.cache_write_tokens,
        "refused": attempt.refused,
    }


def _decision_record(decision: GateDecision) -> dict[str, Any]:
    return {
        "question": decision.question,
        "backend": decision.backend,
        "tier": decision.tier,
        "answer": decision.answer,
        "confidence": decision.confidence,
        "samples": list(decision.samples),
        "run_check": decision.run_check,
        "latency_ms": decision.latency_ms,
        "input_tokens": decision.input_tokens,
        "output_tokens": decision.output_tokens,
        "cost_usd": decision.cost_usd,
        "error": decision.error,
        "evidence": [
            {
                "rule": e.rule,
                "segment_id": e.segment_id,
                "char_start": e.char_start,
                "char_end": e.char_end,
            }
            for e in decision.evidence
        ],
    }


def _outcome_record(outcome) -> dict[str, Any]:
    return {
        "category": outcome.category,
        "status": outcome.status,
        "cache_hit": outcome.cache_hit,
        "latency_ms": outcome.latency_ms,
        "request_fingerprint": outcome.request_fingerprint,
        "error": outcome.error,
        "attempts": [_attempt_record(a) for a in outcome.attempts],
        "items": len(outcome.items),
    }


def _drop_record(drop) -> dict[str, Any]:
    return {
        "category": drop.category,
        "kind": drop.raw.kind,
        "reason": drop.reason,
        "new_segment_id": drop.raw.new_segment_id,
        "new_quote": drop.raw.new_quote[:200],
    }


def _sum_cost(values: list[float | None]) -> float | None:
    return None if any(v is None for v in values) else sum(v for v in values if v is not None)


def _run_costs(outcomes, decisions) -> tuple[float | None, float | None]:
    """(recorded cost of all usage, incremental cost of the calls this run made)."""
    recorded = price([a for o in outcomes for a in o.attempts])[0]
    real = price([a for o in outcomes if not o.cache_hit for a in o.attempts])[0]
    gates = _sum_cost([d.cost_usd for d in decisions])
    cost_usd = None if recorded is None or gates is None else recorded + gates
    incremental = None if real is None or gates is None else real + gates
    return cost_usd, incremental


@dataclass
class _StoredBaseline:
    run_id: str
    pair_id: str
    fingerprints: dict[str, str]


def _stored_baseline(con, change_order_id: str) -> _StoredBaseline | None:
    row = con.execute(
        "SELECT run_id, pair_id, fingerprints_json FROM change_run"
        " WHERE change_order_id = ? AND mode = 'ungated'",
        (change_order_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        fingerprints = json.loads(row[2])
    except ValueError:
        fingerprints = {}
    return _StoredBaseline(run_id=row[0], pair_id=row[1], fingerprints=fingerprints)


@dataclass
class _ModeResult:
    exit_code: int  # EXIT_OK, or EXIT_FAILED / EXIT_USAGE for this run
    error: str | None
    complete: bool
    run_id: str
    outcomes: dict[str, Any] = None  # category -> CheckOutcome (replay baseline)


def _run_mode(
    mode: str,
    *,
    con,
    built: BuiltChain,
    context: GateContext,
    questions: list[Question],
    rules: RulesGate,
    haiku: HaikuGate | None,
    checker: Checker,
    budget: Budget,
    question_set_sha256: str,
    log_path: Path,
    pair_id: str,
    baseline_outcomes: dict | None = None,
    baseline_run_id: str | None = None,
    stored: _StoredBaseline | None = None,
) -> _ModeResult:
    """One mode of one change order: decide, check, verify, write, log."""
    co_id = built.snapshot.change_order_id
    co_doc = built.docs[co_id]
    run_id = _new_id()
    error: str | None = None
    exit_code = EXIT_OK
    started = time.monotonic()

    if mode == "ungated":
        # The rules tier is free and never decides a skip: record it and run
        # all six checks (plan Task 19).
        decisions = [rules.decide(q, co_doc, context) for q in questions]
    else:
        decisions = run_cascade(questions, co_doc, context, rules, haiku)

    outcomes = []
    for question, decision in zip(questions, decisions, strict=True):
        if not decision.run_check:
            continue  # a valid skip under the pre-registered policy
        if mode == "gated" and baseline_outcomes is not None:
            # R7: replay the paired ungated run's outcome, even with --no-cache.
            outcome = baseline_outcomes.get(question.category)
            if outcome is None:
                error = "baseline_missing"
                exit_code = EXIT_USAGE
                break
            outcomes.append(replace(outcome, cache_hit=True))
            continue
        if mode == "gated":
            fingerprint = _fingerprint(checker, built, question)
            if (
                stored is None
                or stored.fingerprints.get(question.category) != fingerprint
                or checker.cache.get(fingerprint) is None
            ):
                error = "no_stored_outcome"
                exit_code = EXIT_USAGE
                break
        outcomes.append(checker.check(built.chain_docs, question.category, question))

    findings: list[Finding] = []
    drops = []
    if error is None and any(o.status != "ok" for o in outcomes):
        error = next(o.error or o.status for o in outcomes if o.status != "ok")
    if error is None:
        try:
            for outcome in outcomes:
                result = verify_findings(built.chain_docs, outcome.category, outcome.items)
                findings.extend(result.findings)
                drops.extend(result.drops)
        except Exception as exc:  # a short code only; never an exception repr
            error = type(exc).__name__
    complete = error is None
    if complete:
        cost_usd, incremental_cost_usd = _run_costs(outcomes, decisions)
        info = ChangeRunInfo(
            run_id=run_id,
            pair_id=pair_id,
            mode=mode,
            prompt_version=prompt_version(),
            question_set_sha256=question_set_sha256,
            model=checker.model,
            fingerprints={o.category: o.request_fingerprint for o in outcomes},
            baseline_run_id=baseline_run_id if mode == "gated" else None,
            cost_usd=cost_usd,
            incremental_cost_usd=incremental_cost_usd,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        try:
            write_change_run(
                con,
                info=info,
                snapshot=built.snapshot,
                docs=built.docs,
                findings=findings,
                decisions=decisions,
            )
        except SnapshotChanged as changed:
            complete = False
            error = str(changed.args[0]) if changed.args else "snapshot_changed"
            print(
                f"og.change: {co_id} {mode} failed: {error}; previous run kept",
                file=sys.stderr,
            )
    if not complete and exit_code == EXIT_OK:
        exit_code = EXIT_FAILED

    cost_usd, incremental_cost_usd = _run_costs(outcomes, decisions)
    record = {
        "run_id": run_id,
        "pair_id": pair_id,
        "mode": mode,
        "change_order_id": co_id,
        "baseline_run_id": baseline_run_id if mode == "gated" else None,
        "prompt_version": prompt_version(),
        "question_set_sha256": question_set_sha256,
        "model": checker.model,
        "complete": complete,
        "error": error,
        "chain": [{"agreement_id": m.agreement_id, "role": m.role} for m in built.snapshot.members],
        "skipped": [
            q.category for q, d in zip(questions, decisions, strict=True) if not d.run_check
        ],
        "decisions": [_decision_record(d) for d in decisions],
        "outcomes": [_outcome_record(o) for o in outcomes],
        "drops": [_drop_record(d) for d in drops],
        "verified": len(findings),
        "cost_usd": cost_usd,
        "incremental_cost_usd": incremental_cost_usd,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "budget_exhausted": budget.exhausted,
    }
    _append_log(log_path, record)
    if complete:
        cost_text = f"{cost_usd:.4f}" if cost_usd is not None else "?"
        print(f"{co_id} {mode} complete findings={len(findings)} cost_usd={cost_text}")
    elif error is not None and error != "no_stored_outcome":
        print(f"og.change: {co_id} {mode} failed: {error}; previous run kept", file=sys.stderr)
    return _ModeResult(
        exit_code=exit_code,
        error=error,
        complete=complete,
        run_id=run_id,
        outcomes={o.category: o for o in outcomes},
    )


def _fingerprint(checker: Checker, built: BuiltChain, question: Question) -> str:
    request = build_request(
        built.chain_docs,
        question.category,
        question,
        model=checker.model,
        effort=checker.effort,
        max_tokens=checker.max_tokens,
    )
    return request_fingerprint(request, built.chain_docs)


def _process_change_order(
    co_entry: dict[str, Any],
    *,
    con,
    built: BuiltChain,
    questions: list[Question],
    rules: RulesGate,
    checker: Checker,
    budget: Budget,
    gate_model: str,
    gate_timeout_s: float,
    question_set_sha256: str,
    log_path: Path,
    mode: str,
    client,
) -> int:
    co_id = built.snapshot.change_order_id
    context = build_gate_context(con, built.base_agreement_id)
    haiku = HaikuGate(client, model=gate_model, budget=budget, timeout_s=gate_timeout_s)
    stored = _stored_baseline(con, co_id)
    pair_id = _new_id()
    rc = EXIT_OK

    if mode == "gated" and stored is None:
        print(
            f"og.change: {co_id}: no stored ungated run; run --mode ungated or both first",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if mode in ("ungated", "both"):
        ungated = _run_mode(
            "ungated",
            con=con,
            built=built,
            context=context,
            questions=questions,
            rules=rules,
            haiku=None,
            checker=checker,
            budget=budget,
            question_set_sha256=question_set_sha256,
            log_path=log_path,
            pair_id=pair_id,
        )
        rc = ungated.exit_code
        if mode == "both":
            if ungated.complete:
                gated = _run_mode(
                    "gated",
                    con=con,
                    built=built,
                    context=context,
                    questions=questions,
                    rules=rules,
                    haiku=haiku,
                    checker=checker,
                    budget=budget,
                    question_set_sha256=question_set_sha256,
                    log_path=log_path,
                    pair_id=pair_id,
                    baseline_outcomes=ungated.outcomes,
                    baseline_run_id=ungated.run_id,
                )
                rc = gated.exit_code
            else:
                print(
                    f"og.change: {co_id}: gated run skipped; ungated run incomplete",
                    file=sys.stderr,
                )
    else:  # gated alone: replay the stored baseline with an identical fingerprint
        gated = _run_mode(
            "gated",
            con=con,
            built=built,
            context=context,
            questions=questions,
            rules=rules,
            haiku=haiku,
            checker=checker,
            budget=budget,
            question_set_sha256=question_set_sha256,
            log_path=log_path,
            pair_id=stored.pair_id,
            stored=stored,
            baseline_run_id=stored.run_id,
        )
        if gated.error == "no_stored_outcome":
            print(
                f"og.change: {co_id}: no stored ungated outcome with the current fingerprint;"
                " re-run --mode ungated",
                file=sys.stderr,
            )
        rc = gated.exit_code
    return rc


def main(argv: list[str] | None = None, *, client=None) -> int:
    parser = argparse.ArgumentParser(
        prog="og.change",
        description="Gate, check, verify, and store a change-order diff for every amendment",
    )
    parser.add_argument("--doc", default=None, help="process only this change order id")
    parser.add_argument("--mode", choices=MODE_CHOICES, default="both")
    parser.add_argument(
        "--no-cache", action="store_true", help="bypass the check cache for fresh calls"
    )
    parser.add_argument("--log", default=str(LOG_PATH), help="run log path (JSONL)")
    parser.add_argument("--db", default=DEFAULT_DB, help="graph db path")
    args = parser.parse_args(argv)

    if not SOURCES_PATH.exists():
        print("og.change: data/sources.yaml not found; run make fetch", file=sys.stderr)
        return EXIT_USAGE
    try:
        entries = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")).get("documents", [])
    except yaml.YAMLError as exc:
        name = type(exc).__name__
        print(f"og.change: data/sources.yaml is not valid YAML: {name}", file=sys.stderr)
        return EXIT_USAGE
    change_orders = [e for e in entries if e.get("amends")]
    if args.doc is not None:
        change_orders = [e for e in change_orders if e["id"] == args.doc]
        if not change_orders:
            print(f"og.change: unknown or non-amendment document {args.doc!r}", file=sys.stderr)
            return EXIT_USAGE
    change_orders.sort(key=lambda e: (str(e.get("filing_date") or ""), e["id"]))
    if not change_orders:
        print("og.change: no change orders pinned in data/sources.yaml")
        return EXIT_OK

    budget = _budget_from_env()
    if budget is None:
        print(f"og.change: bad OG_BUDGET_USD {os.environ.get('OG_BUDGET_USD')!r}", file=sys.stderr)
        return EXIT_USAGE
    try:
        gate_timeout_s = float(_env("OG_GATE_TIMEOUT_S", "30"))
    except ValueError:
        print(
            f"og.change: bad OG_GATE_TIMEOUT_S {_env('OG_GATE_TIMEOUT_S', '')!r}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    questions = load_questions()
    question_set_sha256 = _question_set_sha256()
    rules = RulesGate(questions)
    check_model = _env("OG_EXTRACT_MODEL", "claude-sonnet-5-5")
    gate_model = _env("OG_GATE_MODEL", "claude-haiku-4-5-20251001")
    effort = _env("OG_CHANGE_EFFORT", "high")
    log_path = Path(args.log)
    con = connect(args.db)
    rc = EXIT_OK
    if args.no_cache:
        context = tempfile.TemporaryDirectory(prefix="og-change-")
    else:
        context = contextlib.nullcontext(None)
    with context as scratch:
        cache_dir = scratch if args.no_cache else None
        for co_entry in change_orders:
            try:
                built = build_snapshot(con, entries, co_entry)
            except ChainError as chain_error:
                code = chain_error.code
                where = str(chain_error.args[1]) if len(chain_error.args) > 1 else co_entry["id"]
                detail = _CHAIN_MESSAGES.get(code, code)
                print(f"og.change: {where}: {detail}", file=sys.stderr)
                return EXIT_USAGE
            if client is None:  # credentials come from the environment, constructed lazily
                client = anthropic.Anthropic()
            checker_kwargs: dict[str, Any] = {
                "model": check_model,
                "effort": effort,
                "budget": budget,
            }
            if cache_dir is not None:
                checker_kwargs["cache_dir"] = cache_dir
            checker = Checker(client, **checker_kwargs)
            code = _process_change_order(
                co_entry,
                con=con,
                built=built,
                questions=questions,
                rules=rules,
                checker=checker,
                budget=budget,
                gate_model=gate_model,
                gate_timeout_s=gate_timeout_s,
                question_set_sha256=question_set_sha256,
                log_path=log_path,
                mode=args.mode,
                client=client,
            )
            if code == EXIT_USAGE:
                rc = EXIT_USAGE
            elif code == EXIT_FAILED:
                rc = rc if rc == EXIT_USAGE else EXIT_FAILED
            if budget.exhausted is not None:
                break  # sticky across documents and modes in one invocation
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
