import pytest

from og.eval.gold import GoldItem
from og.eval.score import PredItem, pred_from_db, score
from og.store.db import connect

FIELDS = dict(
    segment_id="p0001",
    span_text="x",
    owed_by=None,
    owed_to=None,
    description="d",
    amount=None,
    currency=None,
    due_date=None,
    anchor_event=None,
    offset_days=None,
    trigger=None,
    status="active",
)


def g(start, end, type_="payment", **kw):
    return GoldItem(**{**FIELDS, "char_start": start, "char_end": end, "type": type_, **kw})


def p(start, end, type_="payment", obligation_id=0, **kw):
    return PredItem(
        **{
            **FIELDS,
            "char_start": start,
            "char_end": end,
            "type": type_,
            "obligation_id": obligation_id,
            **kw,
        }
    )


def pairs(result):
    return sorted((m[0], m[1]) for m in result["matches"])


def test_maximum_cardinality_beats_greedy():
    # Greedy-by-IoU takes (g0, p0) at 0.909 and leaves g1 unmatched; two matches exist.
    gold = [g(0, 100), g(60, 160)]
    pred = [p(0, 110), p(0, 50)]
    result = score(gold, pred).as_dict()
    assert pairs(result) == [(0, 1), (1, 0)]
    assert result["micro"]["tp"] == 2


def test_among_maximum_matchings_total_iou_wins():
    gold = [g(0, 100), g(200, 300)]
    pred = [p(0, 100), p(10, 100), p(200, 300)]
    assert pairs(score(gold, pred).as_dict()) == [(0, 0), (1, 2)]


def test_iou_threshold_is_inclusive():
    assert score([g(0, 100)], [p(0, 30)]).as_dict()["micro"]["tp"] == 1
    assert score([g(0, 100)], [p(0, 29)]).as_dict()["micro"]["tp"] == 0


def test_type_must_match():
    result = score([g(0, 10, "payment")], [p(0, 10, "notice")]).as_dict()
    assert result["micro"] == {
        "tp": 0,
        "fp": 1,
        "fn": 1,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
    }


def test_deterministic_ties():
    assert pairs(score([g(0, 10)], [p(0, 10), p(0, 10)]).as_dict()) == [(0, 0)]
    assert pairs(score([g(0, 10), g(0, 10)], [p(0, 10)]).as_dict()) == [(0, 0)]


def test_metadata():
    result = score([g(0, 10)], [p(0, 10)]).as_dict()
    assert result["metric"] == "m1"
    assert result["iou_threshold"] == 0.3
    assert result["n_gold"] == 1 and result["n_pred"] == 1


@pytest.mark.parametrize(
    "gold,pred,precision,recall",
    [
        ([], [], 1.0, 1.0),
        ([g(0, 10)], [], 0.0, 0.0),
        ([], [p(0, 10)], 0.0, 1.0),
    ],
)
def test_empty_set_conventions(gold, pred, precision, recall):
    micro = score(gold, pred).as_dict()["micro"]
    assert (micro["precision"], micro["recall"]) == (precision, recall)


def test_per_type_micro_macro():
    gold = [g(0, 10, "payment"), g(20, 30, "payment"), g(40, 50, "notice")]
    pred = [p(0, 10, "payment"), p(40, 50, "notice"), p(60, 70, "insurance")]
    result = score(gold, pred).as_dict()
    micro = result["micro"]
    assert (micro["tp"], micro["fp"], micro["fn"]) == (2, 1, 1)
    assert micro["precision"] == pytest.approx(2 / 3)
    assert micro["recall"] == pytest.approx(2 / 3)
    assert micro["f1"] == pytest.approx(2 / 3)
    pay = result["per_type"]["payment"]
    assert (pay["tp"], pay["fp"], pay["fn"]) == (1, 0, 1)
    assert pay["precision"] == 1.0 and pay["recall"] == 0.5
    assert pay["f1"] == pytest.approx(2 / 3)
    ins = result["per_type"]["insurance"]
    # No gold of this type: recall is 1.0 by convention (nothing missed), precision 0.0.
    assert (ins["tp"], ins["fp"], ins["fn"], ins["precision"], ins["recall"]) == (0, 1, 0, 0.0, 1.0)
    assert ins["f1"] == 0.0
    macro = result["macro"]  # over types present in gold: payment, notice
    assert macro["precision"] == pytest.approx(1.0)
    assert macro["recall"] == pytest.approx(0.75)
    assert macro["f1"] == pytest.approx((2 / 3 + 1.0) / 2)


def test_field_metrics_on_matched_pairs():
    gold = [
        g(0, 10, amount=100),
        g(20, 30, amount=50),
        g(40, 50, amount=None),
        g(60, 70, amount=20),
        g(80, 90, amount=7),  # unmatched: never counted
    ]
    pred = [
        p(0, 10, amount=100.0),
        p(20, 30, amount=None),
        p(40, 50, amount=70),
        p(60, 70, amount=25),
    ]
    amount = score(gold, pred).as_dict()["fields"]["amount"]
    assert amount == {
        "gold_known": 3,
        "pred_known": 3,
        "both_known": 2,
        "both_known_equal": 1,
        "accuracy_on_known": 0.5,
        "coverage": pytest.approx(2 / 3),
    }


def test_field_metric_strings_compare_casefolded_and_unknown_is_none():
    gold = [g(0, 10, owed_by="Tenant")]
    pred = [p(0, 10, owed_by="tenant")]
    fields = score(gold, pred).as_dict()["fields"]
    assert fields["owed_by"]["both_known_equal"] == 1
    assert fields["due_date"] == {
        "gold_known": 0,
        "pred_known": 0,
        "both_known": 0,
        "both_known_equal": 0,
        "accuracy_on_known": None,
        "coverage": None,
    }
    assert set(fields) == {
        "amount",
        "currency",
        "due_date",
        "offset_days",
        "anchor_event",
        "owed_by",
        "owed_to",
        "status",
    }


SPAN = "Tenant shall pay rent."


@pytest.fixture
def db(tmp_path):
    con = connect(tmp_path / "g.db")
    con.execute("INSERT INTO source(id,url,local_path,sha256) VALUES('d1','u','p','h')")
    con.execute("INSERT INTO agreement(id,title,type,source_id) VALUES('d1','Lease','lease','d1')")
    con.execute("INSERT INTO party(id,name) VALUES(1,'Landlord Co'),(2,'Tenant Co')")
    for pid, role, start in ((1, "landlord", 100), (2, "tenant", 200)):
        ref = add_ref(con, None, start)
        con.execute(
            "INSERT INTO agreement_party(agreement_id,party_id,role,clause_ref_id)"
            " VALUES('d1',?,?,?)",
            (pid, role, ref),
        )
    return con


def add_ref(con, oid, start, grounded=1):
    cur = con.execute(
        "INSERT INTO clause_ref(obligation_id,agreement_id,section,page,char_start,char_end,"
        "span_text,grounded) VALUES(?,'d1','2',3,?,?,?,?)",
        (oid, start, start + len(SPAN), SPAN, grounded),
    )
    return cur.lastrowid


def add_obligation(con, type_="payment", amount=54000.0):
    cur = con.execute(
        "INSERT INTO obligation(agreement_id,type,owed_by,owed_to,description,amount,currency,"
        "status) VALUES('d1',?,2,1,'pay rent',?,'USD','active')",
        (type_, amount),
    )
    return cur.lastrowid


def test_pred_from_db_dedups_refs_and_returns_role_words(db):
    oid = add_obligation(db)
    add_ref(db, oid, 500)
    add_ref(db, oid, 300)
    hidden = add_obligation(db, "notice")
    add_ref(db, hidden, 700, grounded=0)
    preds = pred_from_db(db, "d1")
    assert len(preds) == 1
    item = preds[0]
    assert item.obligation_id == oid
    assert (item.char_start, item.char_end) == (300, 300 + len(SPAN))
    assert item.span_text == SPAN
    assert (item.owed_by, item.owed_to) == ("tenant", "landlord")
    assert (item.type, item.amount, item.currency, item.status) == (
        "payment",
        54000.0,
        "USD",
        "active",
    )
    assert item.segment_id is None
