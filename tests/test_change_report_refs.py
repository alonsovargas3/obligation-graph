"""Wave 4 rev 2.3: every ClauseRef in a ChangeReport is an exact slice of its source.

Regression found by the Task 32 worker: the report sliced its finding rows one column
off, so every `old` and `context` citation was garbage (an integer where the agreement
id belongs, a null quote). The frozen wave 4 tests checked that an old side existed,
not its content. This test pins content on the real graph fixture for both change
orders and both modes.
"""

import pytest
from graph_fixture import make_workspace, open_db

from og.change.report import load_change_report
from og.paths import text_dir
from og.textdoc import TextDoc

CHANGE_ORDERS = ("constantcontact-2012-ex101", "endurance-2017-ex106")
KINDS = ("supersessions", "shifted_dates", "price_changes", "potential_conflicts")


@pytest.fixture
def con(tmp_path, monkeypatch):
    ws = make_workspace(tmp_path, monkeypatch)
    return open_db(ws / "data" / "graph.db")


def _doc(agreement_id):
    return TextDoc.load(text_dir() / f"{agreement_id}.json")


def _assert_exact(ref):
    assert isinstance(ref["agreement_id"], str)
    assert isinstance(ref["char_start"], int) and isinstance(ref["char_end"], int)
    doc = _doc(ref["agreement_id"])
    assert doc.text[ref["char_start"] : ref["char_end"]] == ref["span_text"]


@pytest.mark.parametrize("mode", ["ungated", "gated"])
@pytest.mark.parametrize("co", CHANGE_ORDERS)
def test_every_report_citation_is_an_exact_source_slice(con, co, mode):
    report = load_change_report(con, co, mode)
    assert "error" not in report
    seen = 0
    for kind in KINDS:
        for f in report[kind]:
            _assert_exact(f["new"])
            assert f["new"]["agreement_id"] == co
            for side in ("old", "context"):
                if f[side] is not None:
                    _assert_exact(f[side])
                    seen += 1
    assert seen > 0, "both change orders carry at least one old or context citation"


def test_3a_shifted_date_old_side_is_the_cited_recital(con):
    report = load_change_report(con, "endurance-2017-ex106", "ungated")
    [f] = report["shifted_dates"]
    assert f["old_origin"] == "self"
    assert f["old"]["agreement_id"] == "endurance-2017-ex106"
    assert "scheduled to be surrendered to Landlord on June 30, 2018" in f["old"]["span_text"]
    assert f["new"]["span_text"] == "expiring June 30, 2020"


def test_3a_price_rows_carry_their_period_context(con):
    report = load_change_report(con, "endurance-2017-ex106", "ungated")
    doc = _doc("endurance-2017-ex106")
    periods = {doc.segment_text(s).strip() for s in ("p0017", "p0019", "p0021")}
    contexts = [f["context"] for f in report["price_changes"]]
    assert len(contexts) == 3 and all(c is not None for c in contexts)
    assert {c["span_text"].strip() for c in contexts} == periods


def test_1a_supersession_old_sides_are_in_the_base_lease(con):
    report = load_change_report(con, "constantcontact-2012-ex101", "ungated")
    olds = [f["old"] for f in report["supersessions"] if f["old"] is not None]
    assert olds and all(o["agreement_id"] == "constantcontact-2011-ex1041" for o in olds)
