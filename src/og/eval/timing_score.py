"""Timing scorer (wave 5 Task 43, plan rev 2 W5-9 and rev 2.2).

``score_timing(con, gold)`` matches each labeled item to at most one visible
obligation of the same agreement whose grounded extraction citation has
IoU >= 0.3 with the labeled quote, by maximum-cardinality matching with the
same exact solver as the extraction scorer (type is not part of a timing
label). Predictions come only from the read projections: an obligation with
no visible timing row predicts ``untimed`` with null fields, a scheduled row
predicts its bound, and the bound metric never reads the legacy ``due_date``.
Scoring happens within matched obligations only; the missing list names
labels that matched nothing. An invented bound is a predicted date on a
matched obligation whose label states none.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from og.eval.score import IOU_THRESHOLD, _iou, _opt_weights
from og.eval.timing_gold import TimingGold, TimingLabel

TRIGGER_IOU_THRESHOLD = Fraction(1, 2)


@dataclass(frozen=True)
class _Pred:
    """A predicted obligation's timing: its citations and visible timing row."""

    obligation_id: int
    citations: tuple[tuple[int, int], ...]
    kind: str
    relation: str | None
    bound_date: str | None
    reason: str | None
    trigger: tuple[int, int] | None


_CITATIONS_SQL = (
    "SELECT obligation_id, char_start, char_end FROM visible_obligation_clause"
    " WHERE agreement_id = ?"
)
_TIMING_SQL = (
    "SELECT obligation_id, kind, relation, bound_date, offset_days, offset_unit,"
    " reason, trigger_char_start, trigger_char_end FROM visible_obligation_timing"
    " WHERE agreement_id = ?"
)


def _predictions(con: sqlite3.Connection, agreement_id: str) -> list[_Pred]:
    citations: dict[int, list[tuple[int, int]]] = {}
    for oid, start, end in con.execute(_CITATIONS_SQL, (agreement_id,)):
        citations.setdefault(oid, []).append((start, end))

    timing: dict[int, tuple[Any, ...]] = {}
    for row in con.execute(_TIMING_SQL, (agreement_id,)):
        timing[row[0]] = tuple(row[1:])

    preds: list[_Pred] = []
    for oid in sorted(citations):
        kind, relation, bound, _off_days, _off_unit, reason, t0, t1 = timing.get(
            oid, (None, None, None, None, None, None, None, None)
        )
        preds.append(
            _Pred(
                obligation_id=oid,
                citations=tuple(citations[oid]),
                kind=kind if kind is not None else "untimed",
                relation=relation,
                bound_date=bound,
                reason=reason,
                trigger=(t0, t1) if t0 is not None and t1 is not None else None,
            )
        )
    return preds


def _match(labels: list[TimingLabel], preds: list[_Pred]) -> list[tuple[int, int]]:
    """Lexicographically smallest optimal (max cardinality, then max IoU) matching.

    The same construction as the extraction scorer, minus the type constraint:
    an edge exists when any grounded extraction citation of the obligation
    overlaps the labeled quote with IoU >= 0.3, weighted by the best such IoU.
    """
    edges: dict[tuple[int, int], Fraction] = {}
    for i, label in enumerate(labels):
        for j, pred in enumerate(preds):
            best = max(
                (_iou(label.char_start, label.char_end, c0, c1) for c0, c1 in pred.citations),
                default=Fraction(0),
            )
            if best >= IOU_THRESHOLD:
                edges[(i, j)] = best

    big_m = Fraction(len(labels) + len(preds) + 2)
    avail_l = set(range(len(labels)))
    avail_p = set(range(len(preds)))
    table = _opt_weights(edges, avail_l, avail_p, big_m)
    remaining_k = max(table)
    remaining_w = table[remaining_k]
    matches: list[tuple[int, int]] = []

    for i in range(len(labels)):
        for j in sorted(j for (ii, j) in edges if ii == i and j in avail_p):
            rem_l = avail_l - {i}
            rem_p = avail_p - {j}
            sub = _opt_weights(edges, rem_l, rem_p, big_m)
            k = max(sub)
            if k == remaining_k - 1 and sub[k] == remaining_w - edges[(i, j)]:
                matches.append((i, j))
                avail_l, avail_p = rem_l, rem_p
                remaining_k, remaining_w = k, sub[k]
                break
        else:
            # No optimal completion matches this label; leave it unmatched.
            avail_l.discard(i)
    return matches


def _accuracy(correct: int, denominator: int) -> dict[str, Any]:
    return {
        "correct": correct,
        "denominator": denominator,
        "accuracy": correct / denominator if denominator else None,
    }


def score_timing(con: sqlite3.Connection, gold: TimingGold) -> dict[str, Any]:
    """Score the graph's visible timing against a timing reference set."""
    label_indices: dict[str, list[int]] = {}
    for idx, item in enumerate(gold.items):
        label_indices.setdefault(item.agreement_id, []).append(idx)

    matched: dict[int, _Pred] = {}
    for agreement_id in sorted(label_indices):
        indices = label_indices[agreement_id]
        labels = [gold.items[i] for i in indices]
        preds = _predictions(con, agreement_id)
        for li, pj in _match(labels, preds):
            matched[indices[li]] = preds[pj]

    kind_correct = 0
    relation_correct = relation_den = 0
    bound_correct = bound_den = invented = 0
    trigger_matched = trigger_den = 0
    reason_correct = reason_den = 0
    confusion: dict[str, dict[str, int]] = {}

    for idx in sorted(matched):
        label = gold.items[idx]
        pred = matched[idx]
        cell = confusion.setdefault(label.timing_kind, {})
        cell[pred.kind] = cell.get(pred.kind, 0) + 1

        if label.timing_kind == pred.kind:
            kind_correct += 1
        if label.relation is not None:
            relation_den += 1
            if label.relation == pred.relation:
                relation_correct += 1
        if label.bound_date is not None:
            bound_den += 1
            if label.bound_date == pred.bound_date:
                bound_correct += 1
        elif pred.bound_date is not None:
            invented += 1
        if label.trigger_span_text is not None:
            trigger_den += 1
            if pred.trigger is not None:
                t0 = label.char_start + label.span_text.index(label.trigger_span_text)
                t1 = t0 + len(label.trigger_span_text)
                if _iou(t0, t1, pred.trigger[0], pred.trigger[1]) >= TRIGGER_IOU_THRESHOLD:
                    trigger_matched += 1
        if label.timing_kind == "unresolved":
            reason_den += 1
            if label.reason == pred.reason:
                reason_correct += 1

    return {
        "name": gold.name,
        "labeled": len(gold.items),
        "matched": len(matched),
        "missing": [
            {"agreement_id": item.agreement_id, "segment_id": item.segment_id}
            for idx, item in enumerate(gold.items)
            if idx not in matched
        ],
        "timing_kind": _accuracy(kind_correct, len(matched)),
        "relation": _accuracy(relation_correct, relation_den),
        "bound_date": {
            **_accuracy(bound_correct, bound_den),
            "invented": invented,
        },
        "trigger": {
            "matched": trigger_matched,
            "denominator": trigger_den,
            "rate": trigger_matched / trigger_den if trigger_den else None,
        },
        "reason": _accuracy(reason_correct, reason_den),
        "confusion": confusion,
    }
