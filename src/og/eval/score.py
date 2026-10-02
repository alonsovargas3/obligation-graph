"""Score predicted obligations against the reference set.

Matching is a true maximum-cardinality bipartite matching over candidate pairs
(same type, span IoU >= 0.3, inclusive), refined to maximum total IoU among
maximum matchings, with deterministic lexicographic (gold index, pred index)
tie-breaking. It is solved exactly with min-cost flow in rational arithmetic:
each arc costs -(M + IoU) with M larger than any possible cardinality, so
cardinality dominates first and total IoU breaks ties among maximum matchings.
No greedy shortcut is taken anywhere (review finding R2-15).

Localization (per-type and micro P/R/F1, macro over types present in gold) is
reported separately from field correctness on matched pairs.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from og.eval.gold import GoldItem

IOU_THRESHOLD = Fraction(3, 10)
MATCH_FIELDS = (
    "amount",
    "currency",
    "due_date",
    "offset_days",
    "anchor_event",
    "owed_by",
    "owed_to",
    "status",
)
_NUMERIC_FIELDS = ("amount", "offset_days")


@dataclass(frozen=True)
class PredItem:
    """A predicted obligation as scored: GoldItem fields plus its DB id."""

    segment_id: str | None
    char_start: int
    char_end: int
    span_text: str
    type: str
    owed_by: str | None
    owed_to: str | None
    description: str
    amount: float | None
    currency: str | None
    due_date: str | None
    anchor_event: str | None
    offset_days: int | None
    trigger: str | None
    status: str
    obligation_id: int


@dataclass(frozen=True)
class Score:
    metric: str
    iou_threshold: float
    n_gold: int
    n_pred: int
    matches: list[tuple[int, int]]
    micro: dict[str, Any]
    per_type: dict[str, dict[str, Any]]
    macro: dict[str, Any]
    fields: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "iou_threshold": self.iou_threshold,
            "n_gold": self.n_gold,
            "n_pred": self.n_pred,
            "matches": list(self.matches),
            "micro": self.micro,
            "per_type": self.per_type,
            "macro": self.macro,
            "fields": self.fields,
        }


def _iou(a0: int, a1: int, b0: int, b1: int) -> Fraction:
    inter = min(a1, b1) - max(a0, b0)
    if inter <= 0:
        return Fraction(0)
    union = (a1 - a0) + (b1 - b0) - inter
    return Fraction(inter, union)


def _opt_weights(
    edges: dict[tuple[int, int], Fraction],
    golds: set[int],
    preds: set[int],
    big_m: Fraction,
) -> dict[int, Fraction]:
    """Best total IoU achievable at each matching cardinality, exactly.

    Min-cost flow by successive shortest paths (SPFA) on
    source -> gold -> pred -> sink, arc cost -(big_m + iou), capacities 1.
    After t augmentations the flow is optimal for value t, so the recorded
    weights are the maxima for every cardinality, not just the final one.
    """
    n_g, n_p = len(golds), len(preds)
    n = n_g + n_p + 2
    src, snk = 0, n - 1
    gi = {g: 1 + k for k, g in enumerate(sorted(golds))}
    pi = {p: 1 + n_g + k for k, p in enumerate(sorted(preds))}

    to: list[int] = []
    cap: list[int] = []
    cost: list[Fraction] = []
    adj: list[list[int]] = [[] for _ in range(n)]

    def add(u: int, v: int, c: int, w: Fraction) -> None:
        adj[u].append(len(to))
        to.append(v)
        cap.append(c)
        cost.append(w)
        adj[v].append(len(to))
        to.append(u)
        cap.append(0)
        cost.append(-w)

    for g in golds:
        add(src, gi[g], 1, Fraction(0))
    for p in preds:
        add(pi[p], snk, 1, Fraction(0))
    for (i, j), iou in edges.items():
        if i in gi and j in pi:
            add(gi[i], pi[j], 1, -(big_m + iou))

    best: dict[int, Fraction] = {0: Fraction(0)}
    while True:
        dist: list[Fraction | None] = [None] * n
        prev = [0] * n
        dist[src] = Fraction(0)
        in_queue = [False] * n
        queue = deque([src])
        in_queue[src] = True
        while queue:
            u = queue.popleft()
            in_queue[u] = False
            du = dist[u]
            assert du is not None
            for e in adj[u]:
                if cap[e] <= 0:
                    continue
                v = to[e]
                nd = du + cost[e]
                if dist[v] is None or nd < dist[v]:
                    dist[v] = nd
                    prev[v] = e
                    if not in_queue[v]:
                        queue.append(v)
                        in_queue[v] = True
        if dist[snk] is None or dist[snk] >= 0:
            return best
        v = snk
        while v != src:
            e = prev[v]
            cap[e] -= 1
            cap[e ^ 1] += 1
            v = to[e ^ 1]
        best[len(best)] = best[len(best) - 1] - dist[snk] - big_m


def _candidate_edges(
    gold: Sequence[GoldItem], pred: Sequence[PredItem]
) -> dict[tuple[int, int], Fraction]:
    edges: dict[tuple[int, int], Fraction] = {}
    for i, g in enumerate(gold):
        for j, p in enumerate(pred):
            if g.type != p.type:
                continue
            iou = _iou(g.char_start, g.char_end, p.char_start, p.char_end)
            if iou >= IOU_THRESHOLD:
                edges[(i, j)] = iou
    return edges


def _match_pairs(gold: Sequence[GoldItem], pred: Sequence[PredItem]) -> list[tuple[int, int]]:
    """Lexicographically smallest optimal (max cardinality, then max IoU) matching."""
    edges = _candidate_edges(gold, pred)
    big_m = Fraction(len(gold) + len(pred) + 2)
    avail_g = set(range(len(gold)))
    avail_p = set(range(len(pred)))
    table = _opt_weights(edges, avail_g, avail_p, big_m)
    remaining_k = max(table)
    remaining_w = table[remaining_k]
    matches: list[tuple[int, int]] = []

    for i in range(len(gold)):
        for j in sorted(j for (ii, j) in edges if ii == i and j in avail_p):
            rem_g = avail_g - {i}
            rem_p = avail_p - {j}
            sub = _opt_weights(edges, rem_g, rem_p, big_m)
            k = max(sub)
            if k == remaining_k - 1 and sub[k] == remaining_w - edges[(i, j)]:
                matches.append((i, j))
                avail_g, avail_p = rem_g, rem_p
                remaining_k, remaining_w = k, sub[k]
                break
        else:
            # No optimal completion matches this gold item; leave it unmatched.
            avail_g.discard(i)
    return sorted(matches)


def _block(tp: int, fp: int, fn: int) -> dict[str, Any]:
    n_pred = tp + fp
    n_gold = tp + fn
    precision = (1.0 if n_gold == 0 else 0.0) if n_pred == 0 else tp / n_pred
    recall = 1.0 if n_gold == 0 else tp / n_gold
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _norm_str(v: Any) -> str:
    return " ".join(str(v).split()).casefold()


def _values_equal(field: str, a: Any, b: Any) -> bool:
    if field in _NUMERIC_FIELDS:
        return a == b
    return _norm_str(a) == _norm_str(b)


def _field_metrics(
    gold: Sequence[GoldItem], pred: Sequence[PredItem], matches: list[tuple[int, int]]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in MATCH_FIELDS:
        gold_known = pred_known = both_known = both_known_equal = 0
        for i, j in matches:
            gv = getattr(gold[i], f)
            pv = getattr(pred[j], f)
            if gv is not None:
                gold_known += 1
            if pv is not None:
                pred_known += 1
            if gv is not None and pv is not None:
                both_known += 1
                if _values_equal(f, gv, pv):
                    both_known_equal += 1
        out[f] = {
            "gold_known": gold_known,
            "pred_known": pred_known,
            "both_known": both_known,
            "both_known_equal": both_known_equal,
            "accuracy_on_known": both_known_equal / both_known if both_known else None,
            "coverage": both_known / gold_known if gold_known else None,
        }
    return out


def score(gold: Sequence[GoldItem], predicted: Sequence[PredItem], metric: str = "m1") -> Score:
    matches = _match_pairs(gold, predicted)
    tp = len(matches)
    micro = _block(tp, len(predicted) - tp, len(gold) - tp)

    types = sorted({g.type for g in gold} | {p.type for p in predicted})
    per_type: dict[str, dict[str, Any]] = {}
    for t in types:
        n_gold_t = sum(1 for g in gold if g.type == t)
        n_pred_t = sum(1 for p in predicted if p.type == t)
        tp_t = sum(1 for i, _ in matches if gold[i].type == t)
        per_type[t] = _block(tp_t, n_pred_t - tp_t, n_gold_t - tp_t)

    gold_types = sorted({g.type for g in gold})
    if gold_types:
        macro = {
            k: sum(per_type[t][k] for t in gold_types) / len(gold_types)
            for k in ("precision", "recall", "f1")
        }
    else:
        macro = {"precision": None, "recall": None, "f1": None}

    return Score(
        metric=metric,
        iou_threshold=float(IOU_THRESHOLD),
        n_gold=len(gold),
        n_pred=len(predicted),
        matches=matches,
        micro=micro,
        per_type=per_type,
        macro=macro,
        fields=_field_metrics(gold, predicted, matches),
    )


def pred_from_db(con: sqlite3.Connection, doc_id: str) -> list[PredItem]:
    """One PredItem per visible obligation of the agreement.

    The span comes from the earliest grounded clause_ref of the obligation;
    owed_by/owed_to come back as the resolved party's role word (lowercase).
    """
    roles: dict[int, str] = {}
    for party_id, role in con.execute(
        "SELECT party_id, role FROM agreement_party WHERE agreement_id = ? ORDER BY role",
        (doc_id,),
    ):
        roles.setdefault(party_id, role)

    items: list[PredItem] = []
    rows = con.execute(
        "SELECT id, type, owed_by, owed_to, description, amount, currency, due_date,"
        ' anchor_event_id, offset_days, "trigger", status FROM visible_obligation'
        " WHERE agreement_id = ? ORDER BY id",
        (doc_id,),
    ).fetchall()
    for row in rows:
        (
            oid,
            type_,
            owed_by,
            owed_to,
            description,
            amount,
            currency,
            due_date,
            anchor_event_id,
            offset_days,
            trigger,
            status,
        ) = row
        ref = con.execute(
            "SELECT char_start, char_end, span_text FROM clause_ref"
            " WHERE obligation_id = ? AND agreement_id = ? AND grounded = 1"
            " ORDER BY char_start, char_end, id LIMIT 1",
            (oid, doc_id),
        ).fetchone()
        if ref is None:
            continue  # not visible; the view should already exclude it
        anchor = None
        if anchor_event_id is not None:
            ev = con.execute("SELECT name FROM event WHERE id = ?", (anchor_event_id,)).fetchone()
            anchor = ev[0] if ev else None
        items.append(
            PredItem(
                segment_id=None,
                char_start=ref[0],
                char_end=ref[1],
                span_text=ref[2],
                type=type_,
                owed_by=roles.get(owed_by),
                owed_to=roles.get(owed_to),
                description=description,
                amount=amount,
                currency=currency,
                due_date=due_date,
                anchor_event=anchor,
                offset_days=offset_days,
                trigger=trigger,
                status=status,
                obligation_id=oid,
            )
        )
    return items
