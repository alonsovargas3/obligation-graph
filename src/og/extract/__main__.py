"""`python -m og.extract`: extract, verify, and store every pinned document.

Each pinned source that has a TextDoc is extracted (one cached API call per
chunk), verified deterministically, and written as one grounded snapshot. An
incomplete document keeps its previous snapshot and fails the run. Every
document-run appends one allowlisted record to logs/extract_runs.jsonl; no
credential, request header, or exception repr ever reaches a written file.

Wave 4 (Task 33): recorded model responses live under ``eval/recorded/extract/``
(``og.replay.cache_dir``), selected by ``OG_REPLAY`` (on / strict / off). The
API client is constructed lazily, on the first cache miss outside strict mode,
so a full replay runs without credentials. A strict miss exits 4 with
``replay_miss <fingerprint>`` and writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import anthropic
import yaml

from og import replay
from og.extract.cache import ResponseCache
from og.extract.client import Extractor
from og.extract.prompt import prompt_version
from og.extract.types import (
    Attempt,
    ChunkOutcome,
    ExtractResult,
    RunInfo,
    VerifyResult,
    WriteRefused,
)
from og.extract.verify import verify
from og.store.db import connect
from og.store.writer import write_snapshot
from og.textdoc import TextDoc

SOURCES_PATH = Path("data/sources.yaml")
TEXT_DIR = Path("data/text")
LOG_PATH = Path("logs/extract_runs.jsonl")

# Dated price table, USD per million tokens. A model missing from the table
# gets no cost computed rather than a wrong one (cost None, unknown_model).
PRICES_2026_10: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {
        "input": 2.00,
        "output": 10.00,
        "cache_read": 0.20,
        "cache_write": 2.50,
    },
}
PRICE_BASIS = "PRICES_2026_10"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAILED = 3
EXIT_REPLAY_MISS = 4


class _LazyClient:
    """Constructs the real client on first use; a full replay never uses it."""

    def __init__(self):
        self._client = None

    def __getattr__(self, name: str):
        if self._client is None:
            self._client = anthropic.Anthropic()  # credentials come from the environment
        return getattr(self._client, name)


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _new_run_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


def _attempt_record(attempt: Attempt) -> dict[str, Any]:
    return {
        "model": attempt.model,
        "input_tokens": attempt.input_tokens,
        "output_tokens": attempt.output_tokens,
        "cache_read_tokens": attempt.cache_read_tokens,
        "cache_write_tokens": attempt.cache_write_tokens,
        "refused": attempt.refused,
    }


def _chunk_record(outcome: ChunkOutcome) -> dict[str, Any]:
    return {
        "chunk_id": outcome.chunk_id,
        "status": outcome.status,
        "cache_hit": outcome.cache_hit,
        "latency_ms": outcome.latency_ms,
        "attempts": [_attempt_record(a) for a in outcome.attempts],
    }


def _cost(attempts: list[Attempt]) -> tuple[float | None, str]:
    """Sum priced token usage across attempts; unknown model means no cost."""
    total = 0.0
    for attempt in attempts:
        prices = PRICES_2026_10.get(attempt.model) if attempt.model is not None else None
        if prices is None:
            return None, "unknown_model"
        total += (attempt.input_tokens or 0) * prices["input"]
        total += (attempt.output_tokens or 0) * prices["output"]
        total += (attempt.cache_read_tokens or 0) * prices["cache_read"]
        total += (attempt.cache_write_tokens or 0) * prices["cache_write"]
    return total / 1_000_000, PRICE_BASIS


def _agreement_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "title": entry.get("title") or entry["id"],
        "type": entry.get("agreement_type"),
        "effective_date": entry.get("effective_date"),
        "base_agreement_id": entry.get("amends"),
        "is_form": bool(entry.get("is_form", False)),
    }


def _base_first(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Base agreements before their amendments, so anchors resolve at write time."""
    ids = {entry["id"] for entry in entries}
    ordered: list[dict[str, Any]] = []
    placed: set[str] = set()
    pending = list(entries)
    while pending:
        ready = [
            e
            for e in pending
            if not e.get("amends") or e["amends"] not in ids or e["amends"] in placed
        ]
        if not ready:  # an amends cycle; keep file order rather than loop forever
            ordered.extend(pending)
            break
        for e in ready:
            ordered.append(e)
            placed.add(e["id"])
        pending = [e for e in pending if e["id"] not in placed]
    return ordered


def _append_log(record: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _process_doc(
    entry: dict[str, Any],
    *,
    extractor: Extractor,
    db_path: str,
    runs_dir: str | None,
    model: str,
) -> bool:
    """Run one document end to end and append its log record. True on success."""
    doc_id = entry["id"]
    doc = TextDoc.load(TEXT_DIR / f"{doc_id}.json")
    run_id = _new_run_id()
    textdoc_sha256 = hashlib.sha256(doc.to_json().encode("utf-8")).hexdigest()
    record: dict[str, Any] = {
        "run_id": run_id,
        "doc_id": doc_id,
        "prompt_version": prompt_version(),
        "textdoc_sha256": textdoc_sha256,
        "complete": False,
        "proposed": 0,
        "verified": 0,
        "chunks": [],
        "drops": [],
        "corrections": [],
        "stats": None,
        "cost_usd": None,
        "cost_basis": None,
        "incremental_cost_usd": None,
        "error": None,
    }
    error: str | None = None
    result: ExtractResult | None = None
    if doc.source_sha256 != entry.get("sha256"):
        error = "pin_mismatch"  # fail before any call or row (CLI defaults, rev 2.1)
    else:
        try:
            result = extractor.extract(doc)
        except replay.ReplayMiss:
            raise  # a strict miss is exit 4, not a failed document run
        except Exception as exc:  # a short code only; never an exception repr
            error = type(exc).__name__
        if result is not None:
            record["chunks"] = [_chunk_record(o) for o in result.outcomes]
            record["proposed"] = len(result.items)
            if not result.complete:
                error = "incomplete"
            else:
                error = _verify_and_write(
                    record,
                    entry=entry,
                    doc=doc,
                    result=result,
                    run_id=run_id,
                    textdoc_sha256=textdoc_sha256,
                    db_path=db_path,
                    runs_dir=runs_dir,
                    model=model,
                )
    outcomes = result.outcomes if result is not None else []
    record["cost_usd"], record["cost_basis"] = _cost([a for o in outcomes for a in o.attempts])
    # R7-3: incremental cost prices only the chunks that really called the API;
    # cache replays are free at the margin (0.0 when every chunk hit).
    record["incremental_cost_usd"] = _cost(
        [a for o in outcomes if not o.cache_hit for a in o.attempts]
    )[0]
    record["error"] = error
    _append_log(record)
    if error is None:
        stats = record["stats"]
        assert isinstance(stats, dict)
        print(f"{doc_id} complete obligations={stats['obligations']}")
    else:
        print(f"og.extract: {doc_id} failed: {error}", file=sys.stderr)
    return error is None


def _verify_and_write(
    record: dict[str, Any],
    *,
    entry: dict[str, Any],
    doc: TextDoc,
    result: ExtractResult,
    run_id: str,
    textdoc_sha256: str,
    db_path: str,
    runs_dir: str | None,
    model: str,
) -> str | None:
    """Verify the complete result and replace the snapshot. None, or a short code."""
    try:
        verified: VerifyResult = verify(doc, result.items)
    except Exception as exc:  # a short code only; never an exception repr
        return type(exc).__name__
    record["verified"] = len(verified.obligations) + len(verified.events) + len(verified.parties)
    record["drops"] = [
        {
            "reason": drop.reason,
            "segment_id": drop.raw.segment_id,
            "span_text": drop.raw.span_text[:200],
        }
        for drop in verified.drops
    ]
    record["corrections"] = [
        {
            "field": correction.field,
            "reason": correction.reason,
            "segment_id": correction.raw.segment_id,
        }
        for correction in verified.corrections
    ]
    target = Path(runs_dir) / f"{doc.doc_id}.db" if runs_dir is not None else Path(db_path)
    try:
        con = connect(target)
        try:
            stats = write_snapshot(
                con,
                source=entry,
                agreement=_agreement_entry(entry),
                doc=doc,
                run=RunInfo(
                    run_id=run_id,
                    prompt_version=result.prompt_version,
                    model=model,
                    textdoc_sha256=textdoc_sha256,
                    attempts=[a for o in result.outcomes for a in o.attempts],
                ),
                result=verified,
            )
        finally:
            con.close()
    except WriteRefused as refused:
        return refused.args[0]
    except Exception as exc:  # a short code only; never an exception repr
        return type(exc).__name__
    record["stats"] = asdict(stats)
    record["complete"] = True
    return None


def main(argv: list[str] | None = None, *, client=None) -> int:
    parser = argparse.ArgumentParser(
        prog="og.extract",
        description="Extract, verify, and store obligations for every pinned document",
    )
    parser.add_argument("--doc", default=None, help="process only this document id")
    parser.add_argument("--db", default="data/graph.db", help="graph db path")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="uncached sample run, written to its own database under --runs-dir",
    )
    parser.add_argument(
        "--runs-dir", default=None, help="sample output directory (required with --no-cache)"
    )
    args = parser.parse_args(argv)

    if not SOURCES_PATH.exists():
        print("og.extract: data/sources.yaml not found; run make fetch", file=sys.stderr)
        return EXIT_USAGE
    entries = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")).get("documents", [])
    selected = [e for e in entries if e.get("sha256") and (TEXT_DIR / f"{e['id']}.json").is_file()]
    if args.doc is not None:
        selected = [e for e in selected if e["id"] == args.doc]
        if not selected:
            print(f"og.extract: unknown or uningested document {args.doc!r}", file=sys.stderr)
            return EXIT_USAGE
    selected = _base_first(selected)
    if args.no_cache:
        if args.runs_dir is None:
            print("og.extract: --no-cache requires --runs-dir", file=sys.stderr)
            return EXIT_USAGE
        amendments = [e["id"] for e in selected if e.get("amends")]
        if amendments:  # rev 2.2 R2-7: samples are standalone documents only
            print(
                "og.extract: --no-cache samples are limited to standalone documents:"
                f" {', '.join(amendments)} amend another agreement",
                file=sys.stderr,
            )
            return EXIT_USAGE
    try:
        max_chars = int(_env("OG_EXTRACT_CHUNK_CHARS", "12000"))
    except ValueError:
        print(
            f"og.extract: bad OG_EXTRACT_CHUNK_CHARS {_env('OG_EXTRACT_CHUNK_CHARS', '')!r}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        replay_mode = replay.mode()
    except ValueError as exc:
        print(f"og.extract: {exc}", file=sys.stderr)
        return EXIT_USAGE

    cache = (
        None
        if args.no_cache or replay_mode == "off"
        else ResponseCache(replay.cache_dir("extract"))
    )
    extractor = Extractor(
        client if client is not None else _LazyClient(),
        cache,
        model=_env("OG_EXTRACT_MODEL", "claude-sonnet-5-5"),
        effort=_env("OG_EXTRACT_EFFORT", "high"),
        no_cache=args.no_cache,
        archive_dir=args.runs_dir if args.no_cache else None,
        max_chars=max_chars,
        strict=replay_mode == "strict" and not args.no_cache,
    )
    failed = False
    try:
        for entry in selected:
            failed |= not _process_doc(
                entry,
                extractor=extractor,
                db_path=args.db,
                runs_dir=args.runs_dir,
                model=extractor.model,
            )
    except replay.ReplayMiss as miss:
        print(f"og.extract: replay_miss {miss.args[0]}", file=sys.stderr)
        return EXIT_REPLAY_MISS
    return EXIT_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
