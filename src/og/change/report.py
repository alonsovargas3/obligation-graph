"""The ChangeReport reader: citation-bearing projections in, cited findings out.

``load_change_report`` reads only the allowlisted views and tables
(``og.query.READ_ALLOWLIST``): findings and their refs from ``visible_change_finding``
joined with ``visible_change_finding_ref``, new obligations from
``visible_obligation`` plus ``visible_obligation_clause``, the chain from
``change_run_chain``, gates from ``gate_decision``, and run identity from
``fresh_change_run`` (wave 4 rev 2.1 R2-1). Anything the DB considers invisible (a
revoked grounding, a stale chain snapshot) is absent from the report rather than
filtered by the caller, and a run that is not fresh is an error, never an empty
check (rev 2 W4-3): ``stale_change_run`` for a stored-but-stale run, ``ValueError``
for no run at all, ``missing_textdoc`` when the change order's canonical TextDoc is
absent (resolved through ``og.paths``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from og.change.chain import load_unresolved_aliases
from og.paths import text_dir
from og.textdoc import TextDoc

TEXT_DIR = Path("data/text")

_REF_COLUMNS = ("agreement_id", "section", "page", "char_start", "char_end", "span_text")
KINDS = ("supersedes", "shifted_date", "price_change", "potential_conflict")


def _ref(row: tuple) -> dict[str, Any] | None:
    """A ClauseRef row (agreement_id..span_text) as a dict, or None for a NULL side."""
    if row is None or row[0] is None:
        return None
    return dict(zip(_REF_COLUMNS, row, strict=True))


def _finding_rows(con: sqlite3.Connection, change_order_id: str, mode: str) -> list[tuple]:
    """Visible findings with their new/old/context refs from the projection view."""
    new_cols = ", ".join(f"n.{c}" for c in _REF_COLUMNS)
    old_cols = ", ".join(f"o.{c}" for c in _REF_COLUMNS)
    ctx_cols = ", ".join(f"x.{c}" for c in _REF_COLUMNS)
    return con.execute(
        "SELECT f.kind, f.category, f.old_origin, f.target_label, f.target_resolution,"
        " f.old_value, f.new_value, f.delta, f.currency,"
        f" {new_cols}, n.clause_ref_id, {old_cols}, o.clause_ref_id, {ctx_cols},"
        " x.clause_ref_id"
        " FROM visible_change_finding f"
        " JOIN visible_change_finding_ref n ON n.finding_id = f.id AND n.side = 'new'"
        " LEFT JOIN visible_change_finding_ref o ON o.finding_id = f.id AND o.side = 'old'"
        " LEFT JOIN visible_change_finding_ref x ON x.finding_id = f.id"
        " AND x.side = 'context'"
        " WHERE f.change_order_id = ? AND f.mode = ? ORDER BY f.id",
        (change_order_id, mode),
    ).fetchall()


def _grouped_findings(rows: list[tuple]) -> dict[str, list[dict[str, Any]]]:
    """Grouped by kind; the same finding in several categories keeps a categories set."""
    order: list[tuple] = []
    grouped: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        head = row[:9]
        new_ref, old_ref, context_ref = row[9:15], row[15:21], row[21:27]
        new_id, old_id, context_id = row[27], row[28], row[29]
        kind, category, old_origin, target_label, target_resolution = head[:5]
        old_value, new_value, delta, currency = head[5:9]
        key = (kind, new_id, old_id, context_id)
        finding = grouped.get(key)
        if finding is None:
            finding = {
                "kind": kind,
                "categories": [category],
                "new": _ref(new_ref),
                "old": _ref(old_ref),
                "old_origin": old_origin,
                "target_label": target_label,
                "target_resolution": target_resolution,
                "old_value": old_value,
                "new_value": new_value,
                "delta": delta,
                "currency": currency,
                "context": _ref(context_ref),
            }
            grouped[key] = finding
            order.append(key)
        elif category not in finding["categories"]:
            finding["categories"].append(category)
    for finding in grouped.values():
        finding["categories"] = sorted(finding["categories"])
    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for key in order:
        finding = grouped[key]
        by_kind.setdefault(finding["kind"], []).append(finding)
    return by_kind


def _new_obligations(con: sqlite3.Connection, change_order_id: str) -> list[dict[str, Any]]:
    """Visible change-order obligations without a resolved supersession edge (R11)."""
    rows = con.execute(
        "SELECT o.id, o.type, o.description, c.agreement_id, c.section, c.page,"
        " c.char_start, c.char_end, c.span_text"
        " FROM visible_obligation o"
        " JOIN visible_obligation_clause c ON c.obligation_id = o.id"
        " WHERE o.agreement_id = ? AND o.id NOT IN (SELECT obligation_id FROM visible_supersedes)"
        " ORDER BY o.id, c.char_start, c.clause_ref_id",
        (change_order_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        obligation_id, type_, description = row[:3]
        if obligation_id in seen:
            continue  # one clause per obligation: its first grounded citation
        seen.add(obligation_id)
        out.append(
            {
                "obligation_id": obligation_id,
                "type": type_,
                "description": description,
                "clause": _ref(row[3:9]),
            }
        )
    return out


def _gates(con: sqlite3.Connection, run_row_id: int) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT question, backend, tier, answer, confidence, run_check, error"
        " FROM gate_decision WHERE change_run_id = ? ORDER BY id",
        (run_row_id,),
    ).fetchall()
    return [
        {
            "question": question,
            "backend": backend,
            "tier": tier,
            "answer": None if answer is None else bool(answer),
            "confidence": confidence,
            "run_check": bool(run_check),
            "error": error,
        }
        for question, backend, tier, answer, confidence, run_check, error in rows
    ]


def _unresolved_documents(con: sqlite3.Connection, run_row_id: int, change_order_id: str) -> list:
    """Unresolved aliases named by the change order: the chain is incomplete (R2-1)."""
    base = con.execute(
        "SELECT agreement_id FROM change_run_chain WHERE change_run_id = ? AND role = 'base'",
        (run_row_id,),
    ).fetchone()
    if base is None:
        return []
    text = TextDoc.load(text_dir() / f"{change_order_id}.json").text
    return [alias for alias in load_unresolved_aliases(base[0]) if alias and alias in text]


def _run_row(con: sqlite3.Connection, change_order_id: str, mode: str) -> tuple | None:
    return con.execute(
        "SELECT id, run_id, pair_id, cost_usd, incremental_cost_usd FROM fresh_change_run"
        " WHERE change_order_id = ? AND mode = ?",
        (change_order_id, mode),
    ).fetchone()


def _has_stored_run(con: sqlite3.Connection, change_order_id: str) -> bool:
    """Any stored run whose change-order chain member is this agreement."""
    return (
        con.execute(
            "SELECT 1 FROM change_run_chain WHERE agreement_id = ? AND role = 'change_order'"
            " LIMIT 1",
            (change_order_id,),
        ).fetchone()
        is not None
    )


def load_change_report(con: sqlite3.Connection, change_order_id: str, mode: str) -> dict[str, Any]:
    """The ChangeReport for one (change order, mode), read from the visible views.

    Raises ``ValueError`` when no run is stored for the pair. Returns
    ``{"error": "stale_change_run"}`` when the stored run is not fresh, and
    ``{"error": "missing_textdoc"}`` when the change order's canonical TextDoc is
    absent: both are errors to surface, never empty reports (rev 2 W4-3).
    """
    run = _run_row(con, change_order_id, mode)
    if run is None:
        if not _has_stored_run(con, change_order_id):
            raise ValueError(f"no change run for {change_order_id!r} mode {mode!r}")
        return {
            "error": "stale_change_run",
            "message": f"The stored {mode} change run for {change_order_id!r} is stale:"
            " its chain no longer matches the current extraction snapshots."
            " Run make change to refresh it.",
        }
    doc_path = text_dir() / f"{change_order_id}.json"
    if not doc_path.is_file():
        return {
            "error": "missing_textdoc",
            "message": f"The canonical TextDoc for {change_order_id!r} is missing"
            f" under {text_dir()}: run make ingest to rebuild it.",
        }
    run_row_id, run_id, pair_id, cost_usd, incremental_cost_usd = run
    chain = [
        {"agreement_id": agreement_id, "role": role, "extraction_run_id": extraction_run_id}
        for agreement_id, role, extraction_run_id in con.execute(
            "SELECT agreement_id, role, extraction_run_id FROM change_run_chain"
            " WHERE change_run_id = ? ORDER BY position",
            (run_row_id,),
        )
    ]
    by_kind = _grouped_findings(_finding_rows(con, change_order_id, mode))
    return {
        "change_order_id": change_order_id,
        "mode": mode,
        "run_id": run_id,
        "pair_id": pair_id,
        "chain": chain,
        "unresolved_documents": _unresolved_documents(con, run_row_id, change_order_id),
        "supersessions": by_kind.get("supersedes", []),
        "shifted_dates": by_kind.get("shifted_date", []),
        "price_changes": by_kind.get("price_change", []),
        "potential_conflicts": by_kind.get("potential_conflict", []),
        "new_obligations": _new_obligations(con, change_order_id),
        "gates": _gates(con, run_row_id),
        "cost_usd": cost_usd,
        "incremental_cost_usd": incremental_cost_usd,
    }
