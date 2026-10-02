"""Task 18: re-extraction invalidates dependent change runs (plan Review Focus 5, rev 2 R4).

og.store.writer._delete_snapshot (reached through write_snapshot) must first delete
every change run whose chain includes the re-extracted agreement, with its edges,
gate decisions, findings, and the ClauseRefs those findings own, and never delete
extraction-owned refs of any other agreement.
"""

import pytest
from change_db import (
    BASE_ID,
    BASE_RENT,
    CO_ID,
    OTHER_ID,
    build_graph,
    counts,
    extract,
    info,
    lifecycle,
    obligation_id,
    snapshot,
)
from change_db import DOCS as _DOCS
from change_db import FINDINGS as _FINDINGS
from change_db import decisions as _decisions

from og.change.writer import write_change_run
from og.store.db import connect

EMPTY = {
    "change_run": 0,
    "change_run_chain": 0,
    "change_finding": 0,
    "supersedes": 0,
    "gate_decision": 0,
}


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "g.db")
    build_graph(c, with_party=True)
    for mode in ("ungated", "gated"):
        write_change_run(
            c,
            info=info(mode),
            snapshot=snapshot(c),
            docs=_DOCS,
            findings=_FINDINGS,
            decisions=_decisions(),
        )
    return c


def orphan_refs(con):
    """Refs with no obligation that nothing (extraction or change run) cites any more."""
    return con.execute(
        "SELECT count(*) FROM clause_ref WHERE obligation_id IS NULL AND id NOT IN ("
        " SELECT clause_ref_id FROM agreement_party UNION"
        " SELECT clause_ref_id FROM defined_term UNION"
        " SELECT clause_ref_id FROM event WHERE clause_ref_id IS NOT NULL UNION"
        " SELECT clause_ref_id FROM supersedes UNION"
        " SELECT new_clause_ref_id FROM change_finding UNION"
        " SELECT old_clause_ref_id FROM change_finding WHERE old_clause_ref_id IS NOT NULL UNION"
        " SELECT context_clause_ref_id FROM change_finding"
        " WHERE context_clause_ref_id IS NOT NULL UNION"
        " SELECT trigger_clause_ref_id FROM obligation_timing"
        " WHERE trigger_clause_ref_id IS NOT NULL UNION"
        " SELECT clause_ref_id FROM agreement_site)"
    ).fetchone()[0]


def extraction_refs(con, agreement):
    return con.execute(
        "SELECT count(*) FROM clause_ref WHERE agreement_id = ? AND (obligation_id IS NOT NULL"
        " OR id IN (SELECT clause_ref_id FROM agreement_party)"
        " OR id IN (SELECT clause_ref_id FROM defined_term))",
        (agreement,),
    ).fetchone()[0]


def test_fixture_has_runs_edges_and_decisions(con):
    c = counts(con)
    assert c["change_run"] == 2 and c["change_finding"] == 6
    assert c["supersedes"] == 1 and c["gate_decision"] == 12
    assert lifecycle(con, obligation_id(con, BASE_ID, BASE_RENT)) == "superseded"


def test_reextracting_the_base_deletes_dependent_change_runs(con):
    assert orphan_refs(con) == 0
    co_refs = extraction_refs(con, CO_ID)
    other_refs = extraction_refs(con, OTHER_ID)
    extract(con, BASE_ID, "er-b0-2")  # Review Focus 5: no FK error
    assert counts(con) == EMPTY
    assert orphan_refs(con) == 0  # the change-owned refs went with their findings
    assert extraction_refs(con, CO_ID) == co_refs
    assert extraction_refs(con, OTHER_ID) == other_refs
    assert con.execute("SELECT count(*) FROM visible_agreement_party").fetchone()[0] == 1
    assert (
        con.execute(
            "SELECT count(*) FROM visible_obligation WHERE agreement_id = ?", (BASE_ID,)
        ).fetchone()[0]
        == 5
    )
    assert lifecycle(con, obligation_id(con, BASE_ID, BASE_RENT)) != "superseded"


def test_reextracting_the_change_order_deletes_its_change_runs(con):
    extract(con, CO_ID, "er-x1-2", base=BASE_ID, with_party=True)
    assert counts(con) == EMPTY
    assert orphan_refs(con) == 0
    assert (
        con.execute(
            "SELECT count(*) FROM visible_obligation WHERE agreement_id = ?", (CO_ID,)
        ).fetchone()[0]
        == 3
    )


def test_reextracting_an_unrelated_agreement_keeps_change_runs(con):
    before = counts(con)
    visible = con.execute("SELECT count(*) FROM visible_change_finding").fetchone()[0]
    extract(con, OTHER_ID, "er-z9-2")
    assert counts(con) == before
    assert con.execute("SELECT count(*) FROM visible_change_finding").fetchone()[0] == visible
    assert lifecycle(con, obligation_id(con, BASE_ID, BASE_RENT)) == "superseded"


def test_a_stale_run_left_behind_would_be_invisible(con):
    """Belt and braces: even without deletion, a changed extraction run hides the diff."""
    con.execute("UPDATE extraction_run SET run_id = 'er-b0-X' WHERE source_id = ?", (BASE_ID,))
    assert con.execute("SELECT count(*) FROM visible_change_finding").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM visible_supersedes").fetchone()[0] == 0
    assert lifecycle(con, obligation_id(con, BASE_ID, BASE_RENT)) != "superseded"


def test_change_runs_can_be_rewritten_after_reextraction(con):
    extract(con, BASE_ID, "er-b0-2")
    write_change_run(
        con,
        info=info("ungated", run_id="run-ungated-2", pair_id="pair-2"),
        snapshot=snapshot(con),
        docs=_DOCS,
        findings=_FINDINGS,
        decisions=_decisions(),
    )
    assert con.execute("SELECT count(*) FROM visible_change_finding").fetchone()[0] == 3
    assert lifecycle(con, obligation_id(con, BASE_ID, BASE_RENT)) == "superseded"
