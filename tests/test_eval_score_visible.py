"""Task 34: the scorers read only citation-bearing visible bindings (wave 4 rev 2 W4-2, W4-3).

On a copy of the real wave 3 graph (tests/fixtures/graph/real_v4.db):
- pred_from_db takes payer/payee roles from visible_party_binding and anchor names from
  visible_event_binding, so revoking the landlord's party citation (clause_ref 65, CC
  base) removes every landlord-payee prediction of that agreement and leaves obligation
  34's own quote visible with owed_to None;
- score_change refuses a stale pair (ValueError("stale_change_run")).
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from og.eval.change_gold import load_change_gold
from og.eval.change_score import score_change
from og.eval.score import pred_from_db
from og.textdoc import TextDoc

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "graph"
BASE = "constantcontact-2011-ex1041"
A3 = "endurance-2017-ex106"


@pytest.fixture
def graph(tmp_path):
    path = tmp_path / "graph.db"
    shutil.copy(FIX / "real_v4.db", path)
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    yield con
    con.close()


def landlord_payees_via_projection(con, doc_id):
    return con.execute(
        "SELECT count(*) FROM visible_obligation o WHERE o.agreement_id = ? AND EXISTS"
        " (SELECT 1 FROM visible_party_binding b WHERE b.agreement_id = o.agreement_id"
        "  AND b.party_id = o.owed_to AND b.role = 'landlord')",
        (doc_id,),
    ).fetchone()[0]


def test_fixture_binding_facts(graph):
    row = graph.execute(
        "SELECT agreement_id, name, role FROM visible_party_binding WHERE clause_ref_id = 65"
    ).fetchone()
    assert row == (BASE, "Digital 55 Middlesex, LLC", "landlord")
    assert landlord_payees_via_projection(graph, BASE) == 92


def test_revoked_party_citation_removes_landlord_predictions(graph):
    before = [p for p in pred_from_db(graph, BASE) if p.owed_to == "landlord"]
    assert len(before) == landlord_payees_via_projection(graph, BASE) == 92
    graph.execute("UPDATE clause_ref SET grounded = 0 WHERE id = 65")
    after = pred_from_db(graph, BASE)
    assert [p for p in after if p.owed_to == "landlord"] == []
    assert landlord_payees_via_projection(graph, BASE) == 0
    [ob34] = [p for p in after if p.obligation_id == 34]
    assert ob34.owed_to is None
    assert ob34.span_text  # its own quote stays visible
    assert len(after) == 166  # no obligation is hidden by the revoked binding


def test_revoked_event_citation_removes_the_anchor_name(graph):
    event = graph.execute(
        "SELECT event_id, agreement_id, clause_ref_id FROM visible_event_binding LIMIT 1"
    ).fetchone()
    assert event is not None
    # Attach the anchor to a visible obligation of the same agreement (synthetic edit on
    # the copy: no obligation in the real graph has an anchor today).
    oid = graph.execute(
        "SELECT id FROM visible_obligation WHERE agreement_id = ? ORDER BY id LIMIT 1",
        (event[1],),
    ).fetchone()[0]
    graph.execute(
        "UPDATE obligation SET anchor_event_id = ?, offset_days = 30, due_date = NULL WHERE id = ?",
        (event[0], oid),
    )
    [pred] = [p for p in pred_from_db(graph, event[1]) if p.obligation_id == oid]
    assert pred.anchor_event is not None
    graph.execute("UPDATE clause_ref SET grounded = 0 WHERE id = ?", (event[2],))
    [pred] = [p for p in pred_from_db(graph, event[1]) if p.obligation_id == oid]
    assert pred.anchor_event is None


def gold_3a():
    docs = {p.stem: TextDoc.load(p) for p in (FIX / "text").glob("*.json")}
    return load_change_gold(REPO / "eval" / "gold" / "change" / f"{A3}.yaml", docs)


def test_fresh_pair_scores(graph):
    result = score_change(graph, gold_3a())
    assert result["findings"]["ungated"]["overall"]["tp"] == 4


def test_stale_pair_is_refused(graph):
    graph.execute(
        "UPDATE extraction_run SET textdoc_sha256 = ? WHERE source_id = ?",
        ("0" * 64, BASE),
    )
    with pytest.raises(ValueError) as err:
        score_change(graph, gold_3a())
    assert err.value.args[0] == "stale_change_run"
