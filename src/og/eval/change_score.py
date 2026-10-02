"""Score change-order runs against the reference set (Task 20; rev 2 R8, R9).

Everything is read from the visible views: an invisible (stale or ungrounded)
finding cannot be scored, exactly as it cannot be shown. Both runs of the pair
must be present and matched (rev 2 R7); otherwise scoring refuses with
``ValueError("unmatched_pair")``.

The finding unit is rev 2 R9: one finding per (kind, new segment, old side),
where the old side is the same old document and segment (chain), the same
change-order segment (self), or a normalized target label (unresolved).
Matching is therefore exact identity, and the maximum-cardinality matching on
identity edges is computed by grouping: within a key group every gold pairs
with every prediction, so pairing the i-th gold with the i-th prediction of a
group is a maximum-cardinality matching (the wave 2 matcher core with identity
candidate edges and no type/IoU adapter).

Gate metrics follow rev 2 R8: recall against the reference labels and against
the ungated baseline (a category is baseline-positive when its ungated check
kept at least one finding), with a one-sided Clopper-Pearson 95% upper bound
on the miss rate. The cascade's operative decision is ``run_check`` (a skip is
the only way to miss); the classifier backends are scored on their own
answers, and Haiku is reported on its observed subset with coverage.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from og.change.types import CATEGORIES, FINDING_KINDS
from og.eval.change_gold import ChangeGold, ChangeGoldFinding

_QUOTE_MAP = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}
_VALUE_FIELDS = ("old_value", "new_value", "delta", "currency", "target_label")


# --- Clopper-Pearson one-sided upper bound -----------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (Lentz)."""
    max_iter, eps, fpmin = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def clopper_pearson_upper(k: int, n: int) -> float | None:
    """One-sided 95% upper bound on a miss rate: k misses in n positive cases.

    Solves I_p(k+1, n-k) = 0.95 exactly by bisection. Returns None when there
    are no cases to bound.
    """
    if n <= 0:
        return None
    if not 0 <= k <= n:
        raise ValueError("bad_counts")
    if k == n:
        return 1.0
    a, b = k + 1, n - k
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _betainc(a, b, mid) < 0.95:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return hi


# --- finding unit (rev 2 R9) --------------------------------------------------------------------


def _norm_label(v: str | None) -> str | None:
    """Casefolded, whitespace-collapsed, quote-normalized target label."""
    if v is None:
        return None
    for curly, straight in _QUOTE_MAP.items():
        v = v.replace(curly, straight)
    return " ".join(v.split()).casefold()


Key = tuple[str, str, str, str | None, str | None, str | None]


def _gold_key(f: ChangeGoldFinding) -> Key:
    if f.old_origin == "chain":
        return (f.kind, f.new_segment_id, "chain", f.old_doc, f.old_segment_id, None)
    if f.old_origin == "self":
        return (f.kind, f.new_segment_id, "self", None, f.old_segment_id, None)
    return (f.kind, f.new_segment_id, "unresolved", None, None, _norm_label(f.target_label))


@dataclass(frozen=True)
class PredFinding:
    key: Key
    kind: str
    categories: tuple[str, ...]
    target_label: str | None
    old_value: str | None
    new_value: str | None
    delta: str | None
    currency: str | None


def _segment_of(
    sorted_segments: list[tuple[str, tuple[int, int]]], char_start: int | None
) -> str | None:
    if char_start is None:
        return None
    for sid, (start, end) in sorted_segments:
        if start <= char_start < end:
            return sid
        if start > char_start:
            break
    return None


def _load_predictions(
    con: sqlite3.Connection, gold: ChangeGold, mode: str
) -> tuple[list[PredFinding], dict[str, int]]:
    """Visible findings of one mode, deduplicated across categories (R9)."""
    sorted_segments = {
        a: sorted(t.items(), key=lambda kv: kv[1][0]) for a, t in gold.segments.items()
    }
    co_id = gold.change_order_id
    rows = con.execute(
        "SELECT f.kind, f.category, f.old_origin, f.target_label, f.old_value, f.new_value,"
        " f.delta, f.currency, n.char_start, o.agreement_id, o.char_start"
        " FROM visible_change_finding f"
        " JOIN clause_ref n ON n.id = f.new_clause_ref_id"
        " LEFT JOIN clause_ref o ON o.id = f.old_clause_ref_id"
        " WHERE f.change_order_id = ? AND f.mode = ? ORDER BY f.id",
        (co_id, mode),
    ).fetchall()

    by_key: dict[Key, PredFinding] = {}
    categories: dict[Key, set[str]] = {}
    per_category: dict[str, int] = {}
    for (
        kind,
        category,
        origin,
        label,
        old_value,
        new_value,
        delta,
        currency,
        new_start,
        old_agr,
        old_start,
    ) in rows:
        per_category[category] = per_category.get(category, 0) + 1
        new_seg = _segment_of(sorted_segments[co_id], new_start)
        old_seg = None
        old_doc = None
        if origin == "chain" and old_agr is not None:
            old_doc = old_agr
            old_seg = _segment_of(sorted_segments.get(old_agr, []), old_start)
        elif origin == "self":
            old_seg = _segment_of(sorted_segments[co_id], old_start)
        label_part = _norm_label(label) if origin == "unresolved" else None
        key: Key = (kind, new_seg, origin, old_doc, old_seg, label_part)
        categories.setdefault(key, set()).add(category)
        if key not in by_key:
            by_key[key] = PredFinding(
                key=key,
                kind=kind,
                categories=(),
                target_label=label,
                old_value=old_value,
                new_value=new_value,
                delta=delta,
                currency=currency,
            )

    preds: list[PredFinding] = []
    for key, pred in by_key.items():
        preds.append(
            PredFinding(
                key=key,
                kind=pred.kind,
                categories=tuple(sorted(categories[key])),
                target_label=pred.target_label,
                old_value=pred.old_value,
                new_value=pred.new_value,
                delta=pred.delta,
                currency=pred.currency,
            )
        )
    return preds, per_category


def _match(
    gold_findings: list[ChangeGoldFinding], preds: list[PredFinding]
) -> list[tuple[int, int]]:
    """Maximum-cardinality matching on identity keys, deterministic."""
    gold_groups: dict[Key, list[int]] = {}
    for i, f in enumerate(gold_findings):
        gold_groups.setdefault(_gold_key(f), []).append(i)
    pred_groups: dict[Key, list[int]] = {}
    for j, p in enumerate(preds):
        pred_groups.setdefault(p.key, []).append(j)
    matches: list[tuple[int, int]] = []
    for key, golds in sorted(gold_groups.items()):
        candidates = pred_groups.get(key, [])
        for gi, pj in zip(golds, candidates, strict=False):
            matches.append((gi, pj))
    return sorted(matches)


def _block(tp: int, fp: int, fn: int) -> dict[str, Any]:
    n_pred, n_gold = tp + fp, tp + fn
    precision = (1.0 if n_gold == 0 else 0.0) if n_pred == 0 else tp / n_pred
    recall = 1.0 if n_gold == 0 else tp / n_gold
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}


def _findings_block(
    gold_findings: list[ChangeGoldFinding], preds: list[PredFinding]
) -> dict[str, Any]:
    matches = _match(gold_findings, preds)
    tp = len(matches)
    overall = _block(tp, len(preds) - tp, len(gold_findings) - tp)
    overall["predicted"] = len(preds)
    overall["gold"] = len(gold_findings)
    per_kind: dict[str, dict[str, Any]] = {}
    for kind in FINDING_KINDS:
        n_gold = sum(1 for g in gold_findings if g.kind == kind)
        n_pred = sum(1 for p in preds if p.kind == kind)
        tp_k = sum(1 for i, _ in matches if gold_findings[i].kind == kind)
        per_kind[kind] = _block(tp_k, n_pred - tp_k, n_gold - tp_k)
    return {"overall": overall, "per_kind": per_kind, "matches": matches}


def _values_block(
    gold_findings: list[ChangeGoldFinding],
    preds: list[PredFinding],
    matches: list[tuple[int, int]],
) -> dict[str, dict[str, Any]]:
    """Value accuracy on matched pairs, reported separately from matching (R9)."""
    out: dict[str, dict[str, Any]] = {}
    for field in _VALUE_FIELDS:
        gold_known = both_known = equal = 0
        for gi, pj in matches:
            gv = getattr(gold_findings[gi], field)
            pv = getattr(preds[pj], field)
            if gv is not None:
                gold_known += 1
            if gv is not None and pv is not None:
                both_known += 1
                if field == "target_label":
                    equal += _norm_label(gv) == _norm_label(pv)
                else:
                    equal += gv == pv
        out[field] = {
            "gold": gold_known,
            "coverage": both_known / gold_known if gold_known else None,
            "accuracy": equal / both_known if both_known else None,
        }
    return out


# --- gates (rev 2 R8) ---------------------------------------------------------------------------


def _category_of(question: str) -> str | None:
    for cat in CATEGORIES:
        if question in (cat, f"touches_{cat}"):
            return cat
    return None


def _gate_metrics(predicted_yes: frozenset[str], positives: frozenset[str]) -> dict[str, Any]:
    misses = positives - predicted_yes
    recall = None if not positives else 1.0 - len(misses) / len(positives)
    precision = None if not predicted_yes else len(predicted_yes & positives) / len(predicted_yes)
    return {
        "positives": len(positives),
        "misses": len(misses),
        "missed": sorted(misses),
        "recall": recall,
        "precision": precision,
        "miss_upper_95": clopper_pearson_upper(len(misses), len(positives)),
    }


def _decisions(
    con: sqlite3.Connection, run_rowid: int, backend: str | None = None
) -> dict[str, dict[str, Any]]:
    sql = (
        "SELECT question, backend, answer, run_check, cost_usd FROM gate_decision"
        " WHERE change_run_id = ?"
    )
    params: tuple[Any, ...] = (run_rowid,)
    if backend is not None:
        sql += " AND backend = ?"
        params += (backend,)
    out: dict[str, dict[str, Any]] = {}
    for question, b, answer, run_check, cost_usd in con.execute(sql, params):
        cat = _category_of(question)
        if cat is None or cat in out:
            continue
        out[cat] = {"backend": b, "answer": answer, "run_check": run_check, "cost_usd": cost_usd}
    return out


def _cost(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_usd": run["cost_usd"],
        "incremental_cost_usd": run["incremental_cost_usd"],
        "latency_ms": run["latency_ms"],
    }


def score_change(con: sqlite3.Connection, gold: ChangeGold) -> dict[str, Any]:
    """Score one change order's paired ungated/gated runs against the gold."""
    runs: dict[str, dict[str, Any]] = {}
    for row in con.execute(
        "SELECT id, run_id, pair_id, mode, baseline_run_id, cost_usd, incremental_cost_usd,"
        " latency_ms FROM change_run WHERE change_order_id = ?",
        (gold.change_order_id,),
    ):
        runs[row[3]] = {
            "id": row[0],
            "run_id": row[1],
            "pair_id": row[2],
            "baseline_run_id": row[4],
            "cost_usd": row[5],
            "incremental_cost_usd": row[6],
            "latency_ms": row[7],
        }
    ungated, gated = runs.get("ungated"), runs.get("gated")
    if ungated is None or gated is None:
        raise ValueError("unmatched_pair")
    if gated["baseline_run_id"] != ungated["run_id"] or gated["pair_id"] != ungated["pair_id"]:
        raise ValueError("unmatched_pair")

    co_id = gold.change_order_id
    ungated_preds, ungated_by_cat = _load_predictions(con, gold, "ungated")
    gated_preds, _ = _load_predictions(con, gold, "gated")

    findings_ungated = _findings_block(gold.findings, ungated_preds)
    findings_gated = _findings_block(gold.findings, gated_preds)

    # Retention: the gated run keeps findings relative to the ungated run (same
    # cached responses), measured on the deduplicated finding unit.
    gated_counts: dict[Key, int] = {}
    for p in gated_preds:
        gated_counts[p.key] = gated_counts.get(p.key, 0) + 1
    kept = total = 0
    for p in ungated_preds:
        total += 1
        if gated_counts.get(p.key, 0) > 0:
            kept += 1
            gated_counts[p.key] -= 1
    retention_recall = kept / total if total else None

    values = _values_block(gold.findings, ungated_preds, findings_ungated["matches"])

    # --- gates ---
    ref_positive = frozenset(c for c in CATEGORIES if gold.gates[c])
    baseline_positive = frozenset(ungated_by_cat)

    rules_decisions = _decisions(con, ungated["id"], backend="rules")
    gated_decisions = _decisions(con, gated["id"])
    haiku_decisions = {cat: d for cat, d in gated_decisions.items() if d["backend"] == "haiku"}

    rules_yes = frozenset(c for c, d in rules_decisions.items() if d["answer"] == 1)
    haiku_yes = frozenset(c for c, d in haiku_decisions.items() if d["answer"] == 1)
    observed = frozenset(haiku_decisions)

    # The cascade's operative decision is run_check: a check runs unless the
    # rules tier hit and the classifier unanimously said no. A missing decision
    # fails open (the check runs).
    cascade_yes: set[str] = set()
    cascade_skipped: set[str] = set()
    for cat in CATEGORIES:
        decision = gated_decisions.get(cat)
        runs_check = True if decision is None else decision["run_check"] == 1
        if runs_check:
            cascade_yes.add(cat)
        else:
            cascade_skipped.add(cat)
    cascade_yes_f = frozenset(cascade_yes)

    skipped = len(cascade_skipped)
    gates_out: dict[str, Any] = {
        "cascade": {
            "vs_reference": {
                **_gate_metrics(cascade_yes_f, ref_positive),
                "skipped": skipped,
                "skip_rate": skipped / len(CATEGORIES),
            },
            "vs_baseline": _gate_metrics(cascade_yes_f, baseline_positive),
        },
        "rules": {
            "vs_reference": _gate_metrics(rules_yes, ref_positive),
            "vs_baseline": _gate_metrics(rules_yes, baseline_positive),
        },
        "haiku": {
            "observed": sorted(observed),
            "coverage": len(observed) / len(CATEGORIES),
            "vs_reference": _gate_metrics(haiku_yes, ref_positive & observed),
            "vs_baseline": _gate_metrics(haiku_yes, baseline_positive & observed),
        },
    }

    skips: list[dict[str, Any]] = []
    for cat in sorted(cascade_skipped):
        if cat in baseline_positive:
            kind = "baseline_miss"
        elif cat in ref_positive:
            kind = "zero_baseline_skip"
        else:
            kind = "confirmed_safe_skip"
        skips.append(
            {
                "category": cat,
                "kind": kind,
                "reference": gold.gates[cat],
                "baseline_findings": ungated_by_cat.get(cat, 0),
            }
        )

    disagreements: list[dict[str, Any]] = []
    for backend, domain, yes in (
        ("rules", frozenset(rules_decisions), rules_yes),
        ("haiku", observed, haiku_yes),
        ("cascade", frozenset(CATEGORIES), cascade_yes_f),
    ):
        for cat in sorted(domain):
            answer = cat in yes
            if answer != gold.gates[cat]:
                disagreements.append(
                    {
                        "backend": backend,
                        "category": cat,
                        "answer": answer,
                        "reference": gold.gates[cat],
                    }
                )

    gate_cost = sum(d["cost_usd"] for d in gated_decisions.values() if d["cost_usd"] is not None)
    cost = {
        "ungated": _cost(ungated),
        "gated": _cost(gated),
        "gate_cost_usd": gate_cost,
        "note": (
            "gated check responses replay the ungated run's cache; the gated latency is a"
            " replay comparison, not two independently timed live pipelines"
        ),
    }

    return {
        "change_order_id": co_id,
        "chain": list(gold.chain),
        "pair_id": ungated["pair_id"],
        "findings": {
            "ungated": findings_ungated,
            "gated": findings_gated,
            "retention_recall": retention_recall,
        },
        "values": values,
        "gates": gates_out,
        "skips": skips,
        "disagreements": disagreements,
        "cost": cost,
    }
