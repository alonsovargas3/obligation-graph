"""The change-run writer: verified findings in, one grounded change run out.

With og.store.writer this is the only code that sets grounded = 1. Everything
it writes is re-checked inside the write transaction (rev 2 R4): the chain
snapshot against the current extraction runs, every TextDoc against its pinned
canonical hash, and every cited span against the document text. On any
mismatch it raises SnapshotChanged, nothing is written, and the previous run
stays. Supersedes edges are written by ungated runs only (rev 2 R2).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict

from og.change.types import ChainSnapshot, ChangeRunInfo, CitedSpan, Finding, SnapshotChanged
from og.eval.gold import textdoc_sha256
from og.gates.types import GateDecision
from og.store.writer import delete_change_runs
from og.textdoc import TextDoc

# Edges need a clause-resolved target (rev 2.1 R2-1): "document" and
# "unresolved" name a document, not a clause, so no obligation can be pinned.
_EDGE_TARGET_RESOLUTIONS = ("section", "range")


def write_change_run(
    con: sqlite3.Connection,
    *,
    info: ChangeRunInfo,
    snapshot: ChainSnapshot,
    docs: Mapping[str, TextDoc],
    findings: Sequence[Finding],
    decisions: Sequence[GateDecision],
) -> None:
    """Replace this (change order, mode) run with one transaction's write."""
    _check_chain_shape(snapshot)
    con.execute("BEGIN IMMEDIATE")
    try:
        _check_snapshot(con, snapshot)
        chain_docs = _check_docs(snapshot, docs)
        positions = {m.agreement_id: i for i, m in enumerate(snapshot.members)}
        for f in findings:
            _check_finding(f, snapshot, chain_docs, positions)
        if info.mode == "gated":
            _check_baseline(con, info, snapshot)
        _replace_previous(con, snapshot.change_order_id, info.mode)
        run_row_id = _insert_run(con, info=info, snapshot=snapshot)
        inserted = _insert_findings(con, run_row_id, findings)
        if info.mode == "ungated":
            _write_edges(con, run_row_id, snapshot, inserted)
        _write_decisions(con, run_row_id, snapshot.change_order_id, decisions)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def _check_chain_shape(snapshot: ChainSnapshot) -> None:
    """The change order is the last member and the only one with its role."""
    members = snapshot.members
    if len(members) < 2 or members[-1].role != "change_order":
        raise SnapshotChanged("chain_shape")
    if any(m.role == "change_order" for m in members[:-1]):
        raise SnapshotChanged("chain_shape")


def _check_snapshot(con: sqlite3.Connection, snapshot: ChainSnapshot) -> None:
    """Re-read the chain vector from the DB; a stale diff must not be written."""
    for m in snapshot.members:
        rows = con.execute(
            "SELECT e.run_id, e.textdoc_sha256 FROM agreement a"
            " JOIN extraction_run e ON e.source_id = a.source_id WHERE a.id = ?",
            (m.agreement_id,),
        ).fetchall()
        if (m.extraction_run_id, m.textdoc_sha256) not in rows:
            raise SnapshotChanged("snapshot_mismatch")


def _check_docs(snapshot: ChainSnapshot, docs: Mapping[str, TextDoc]) -> dict[str, TextDoc]:
    """Every chain member's TextDoc must hash to its pinned canonical hash."""
    chain_docs: dict[str, TextDoc] = {}
    for m in snapshot.members:
        doc = docs.get(m.agreement_id)
        if doc is None:
            raise SnapshotChanged("doc_missing")
        if textdoc_sha256(doc) != m.textdoc_sha256:
            raise SnapshotChanged("doc_hash_mismatch")
        chain_docs[m.agreement_id] = doc
    return chain_docs


def _check_span(span: CitedSpan, chain_docs: dict[str, TextDoc]) -> None:
    """The span's document must be a chain member and its text an exact slice."""
    doc = chain_docs.get(span.agreement_id)
    if doc is None:
        raise SnapshotChanged("doc_not_in_chain")
    ev = span.evidence
    if doc.text[ev.char_start : ev.char_end] != ev.span_text:
        raise SnapshotChanged("span_mismatch")


def _check_finding(
    f: Finding,
    snapshot: ChainSnapshot,
    chain_docs: dict[str, TextDoc],
    positions: Mapping[str, int],
) -> None:
    co_id = snapshot.change_order_id
    _check_span(f.new, chain_docs)
    if f.new.agreement_id != co_id:
        raise SnapshotChanged("new_side_agreement")
    if f.context is not None:
        _check_span(f.context, chain_docs)
        if f.context.agreement_id != co_id:
            raise SnapshotChanged("context_side_agreement")
    if f.old is not None:
        _check_span(f.old, chain_docs)
        if f.old_origin == "self" and f.old.agreement_id != co_id:
            raise SnapshotChanged("old_side_agreement")
        if f.old_origin == "chain" and positions[f.old.agreement_id] >= positions[co_id]:
            raise SnapshotChanged("old_side_agreement")


def _check_baseline(con: sqlite3.Connection, info: ChangeRunInfo, snapshot: ChainSnapshot) -> None:
    """A gated run's baseline must be the current ungated run of this chain."""
    row = con.execute(
        "SELECT id FROM change_run WHERE run_id = ? AND change_order_id = ? AND mode = 'ungated'",
        (info.baseline_run_id, snapshot.change_order_id),
    ).fetchone()
    if row is None:
        raise SnapshotChanged("baseline_missing")
    vector = con.execute(
        "SELECT agreement_id, textdoc_sha256, extraction_run_id FROM change_run_chain"
        " WHERE change_run_id = ? ORDER BY position",
        (row[0],),
    ).fetchall()
    if vector != [tuple(v) for v in snapshot.vector()]:
        raise SnapshotChanged("baseline_stale")


def _replace_previous(con: sqlite3.Connection, change_order_id: str, mode: str) -> None:
    """One run per (change order, mode); replacing ungated drops its gated pair."""
    rows = con.execute(
        "SELECT id FROM change_run WHERE change_order_id = ? AND (mode = ? OR mode = 'gated')",
        (change_order_id, mode),
    ).fetchall()
    delete_change_runs(con, (row[0] for row in rows))


def _insert_run(con: sqlite3.Connection, *, info: ChangeRunInfo, snapshot: ChainSnapshot) -> int:
    cur = con.execute(
        "INSERT INTO change_run(run_id, pair_id, change_order_id, mode, prompt_version,"
        " question_set_sha256, model, fingerprints_json, baseline_run_id, chain_size,"
        " cost_usd, incremental_cost_usd, latency_ms, completed_at)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            info.run_id,
            info.pair_id,
            snapshot.change_order_id,
            info.mode,
            info.prompt_version,
            info.question_set_sha256,
            info.model,
            json.dumps(info.fingerprints),
            info.baseline_run_id,
            len(snapshot.members),
            info.cost_usd,
            info.incremental_cost_usd,
            info.latency_ms,
        ),
    )
    run_row_id = cur.lastrowid
    for position, m in enumerate(snapshot.members):
        con.execute(
            "INSERT INTO change_run_chain(change_run_id, position, agreement_id, role,"
            " textdoc_sha256, extraction_run_id) VALUES(?, ?, ?, ?, ?, ?)",
            (run_row_id, position, m.agreement_id, m.role, m.textdoc_sha256, m.extraction_run_id),
        )
    return run_row_id


def _insert_change_ref(con: sqlite3.Connection, span: CitedSpan) -> int:
    """A change-run ref never claims an obligation; only verify-produced spans land here."""
    ev = span.evidence
    cur = con.execute(
        "INSERT INTO clause_ref(obligation_id, agreement_id, section, page, char_start,"
        " char_end, span_text, grounded) VALUES(NULL, ?, ?, ?, ?, ?, ?, 1)",
        (
            span.agreement_id,
            ev.section_number,
            ev.page,
            ev.char_start,
            ev.char_end,
            ev.span_text,
        ),
    )
    return cur.lastrowid


def _insert_findings(
    con: sqlite3.Connection, run_row_id: int, findings: Sequence[Finding]
) -> list[tuple[Finding, int]]:
    """Returns (finding, new clause ref id) for the edge pass."""
    inserted: list[tuple[Finding, int]] = []
    for f in findings:
        new_ref = _insert_change_ref(con, f.new)
        old_ref = _insert_change_ref(con, f.old) if f.old is not None else None
        context_ref = _insert_change_ref(con, f.context) if f.context is not None else None
        con.execute(
            "INSERT INTO change_finding(change_run_id, kind, category, new_clause_ref_id,"
            " old_clause_ref_id, context_clause_ref_id, old_origin, target_label,"
            " target_resolution, old_value, new_value, delta, currency)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_row_id,
                f.kind,
                f.category,
                new_ref,
                old_ref,
                context_ref,
                f.old_origin,
                f.target_label,
                f.target_resolution,
                f.old_value,
                f.new_value,
                f.delta,
                f.currency,
            ),
        )
        inserted.append((f, new_ref))
    return inserted


def _overlapping_obligations(
    con: sqlite3.Connection, agreement_id: str, span: CitedSpan, *, type_: str | None = None
) -> list[tuple[int, str]]:
    """Visible obligations of one agreement whose grounded ref overlaps the span."""
    sql = (
        "SELECT DISTINCT o.id, o.type FROM obligation o"
        " WHERE o.agreement_id = ? AND o.id IN (SELECT id FROM visible_obligation)"
        " AND EXISTS (SELECT 1 FROM clause_ref c WHERE c.obligation_id = o.id"
        "  AND c.agreement_id = o.agreement_id AND c.grounded = 1"
        "  AND c.char_start < ? AND c.char_end > ?)"
    )
    params: list[object] = [agreement_id, span.evidence.char_end, span.evidence.char_start]
    if type_ is not None:
        sql += " AND o.type = ?"
        params.append(type_)
    return con.execute(sql, params).fetchall()


def _write_edges(
    con: sqlite3.Connection,
    run_row_id: int,
    snapshot: ChainSnapshot,
    inserted: Sequence[tuple[Finding, int]],
) -> None:
    """Ungated runs only: one edge per unambiguous, clause-resolved supersession."""
    positions = {m.agreement_id: i for i, m in enumerate(snapshot.members)}
    co_id = snapshot.change_order_id
    for f, new_ref in inserted:
        if f.kind != "supersedes" or f.old_origin != "chain" or f.old is None:
            continue
        if f.target_resolution not in _EDGE_TARGET_RESOLUTIONS:
            continue
        if positions.get(f.old.agreement_id, positions[co_id]) >= positions[co_id]:
            continue
        new_side = _overlapping_obligations(con, co_id, f.new)
        if len(new_side) != 1:
            continue
        new_id, new_type = new_side[0]
        old_side = _overlapping_obligations(con, f.old.agreement_id, f.old, type_=new_type)
        if len(old_side) != 1 or old_side[0][0] == new_id:
            continue
        con.execute(
            "INSERT INTO supersedes(obligation_id, superseded_obligation_id, change_order_id,"
            " clause_ref_id, change_run_id) VALUES(?, ?, ?, ?, ?)",
            (new_id, old_side[0][0], co_id, new_ref, run_row_id),
        )


def _write_decisions(
    con: sqlite3.Connection,
    run_row_id: int,
    change_order_id: str,
    decisions: Sequence[GateDecision],
) -> None:
    for d in decisions:
        con.execute(
            "INSERT INTO gate_decision(change_run_id, change_order_id, question, backend,"
            " tier, answer, confidence, samples_json, evidence_json, run_check, latency_ms,"
            " input_tokens, output_tokens, cost_usd, error)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_row_id,
                change_order_id,
                d.question,
                d.backend,
                d.tier,
                None if d.answer is None else int(d.answer),
                d.confidence,
                json.dumps(list(d.samples)),
                json.dumps([asdict(e) for e in d.evidence]),
                int(d.run_check),
                d.latency_ms,
                d.input_tokens,
                d.output_tokens,
                d.cost_usd,
                d.error,
            ),
        )
