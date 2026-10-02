"""Schema v3 (wave 3): change runs, freshness, edge eligibility, visible change findings.

Plan: docs/superpowers/plans/2026-10-02-wave3-change-gates.md, rev 2 R2/R4 and the
schema-v3 additions. Every view is checked by flipping one input at a time.
"""

import sqlite3

import pytest

from og.store.db import connect

SPAN = "Tenant shall"


@pytest.fixture
def db(tmp_path):
    con = connect(tmp_path / "g.db")
    for src in ("src_a", "src_x", "src_b"):
        con.execute("INSERT INTO source(id,url,local_path,sha256) VALUES(?,'u','p','h')", (src,))
        con.execute(
            "INSERT INTO extraction_run(run_id,source_id,prompt_version,model,textdoc_sha256)"
            " VALUES(?,?,'v1','m',?)",
            (f"er_{src}", src, f"t_{src}"),
        )
    agreement = "INSERT INTO agreement(id,title,type,source_id) VALUES(?,?,'lease',?)"
    con.execute(agreement, ("a1", "Lease", "src_a"))
    con.execute(
        "INSERT INTO agreement(id,title,type,source_id,base_agreement_id)"
        " VALUES('a1x','Amendment','amendment','src_x','a1')"
    )
    con.execute(agreement, ("b1", "Other", "src_b"))
    return con


SOURCE = {"a1": "src_a", "a1x": "src_x", "b1": "src_b"}


def add_obligation(con, agreement, type_="payment"):
    return con.execute(
        "INSERT INTO obligation(agreement_id,type,description,status) VALUES(?,?,'d','active')",
        (agreement, type_),
    ).lastrowid


def add_ref(con, agreement, oid=None, grounded=1):
    return con.execute(
        "INSERT INTO clause_ref(obligation_id,agreement_id,section,page,char_start,char_end,"
        "span_text,grounded) VALUES(?,?,'1',1,0,?,?,?)",
        (oid, agreement, len(SPAN), SPAN, grounded),
    ).lastrowid


def add_run(
    con,
    mode="ungated",
    chain=(("a1", "base"), ("a1x", "change_order")),
    chain_size=None,
    completed=True,
    run_id=None,
    baseline=None,
):
    run_id = run_id or f"cr_{mode}"
    if mode == "gated" and baseline is None:
        baseline = "cr_ungated"
    rid = con.execute(
        "INSERT INTO change_run(run_id,pair_id,change_order_id,mode,prompt_version,"
        "question_set_sha256,model,baseline_run_id,chain_size,completed_at)"
        " VALUES(?,'p','a1x',?,'change_v1@x','q','m',?,?,"
        " CASE WHEN ? THEN datetime('now') END)",
        (run_id, mode, baseline, chain_size or len(chain), completed),
    ).lastrowid
    for pos, (agr, role) in enumerate(chain):
        src = SOURCE[agr]
        con.execute(
            "INSERT INTO change_run_chain(change_run_id,position,agreement_id,role,"
            "textdoc_sha256,extraction_run_id) VALUES(?,?,?,?,?,?)",
            (rid, pos, agr, role, f"t_{src}", f"er_{src}"),
        )
    return rid


def fresh_ids(con):
    return [r[0] for r in con.execute("SELECT id FROM fresh_change_run ORDER BY id")]


# --- freshness (rev 2 R4: complete membership, current snapshot) ---------------------


def test_complete_current_run_is_fresh(db):
    rid = add_run(db)
    assert fresh_ids(db) == [rid]


def test_incomplete_run_is_not_fresh(db):
    add_run(db, completed=False)
    assert fresh_ids(db) == []


def test_chain_row_count_must_equal_chain_size(db):
    add_run(db, chain_size=3)
    assert fresh_ids(db) == []


def test_chain_must_end_with_the_change_order(db):
    add_run(db, chain=(("a1", "base"), ("b1", "prior_amendment")))
    assert fresh_ids(db) == []


def test_stale_extraction_run_id_is_not_fresh(db):
    add_run(db)
    db.execute("UPDATE extraction_run SET run_id='er_new' WHERE source_id='src_a'")
    assert fresh_ids(db) == []


def test_stale_textdoc_hash_is_not_fresh(db):
    add_run(db)
    db.execute("UPDATE extraction_run SET textdoc_sha256='changed' WHERE source_id='src_x'")
    assert fresh_ids(db) == []


def test_missing_extraction_run_is_not_fresh(db):
    add_run(db)
    db.execute("DELETE FROM extraction_run WHERE source_id='src_a'")
    assert fresh_ids(db) == []


def test_gated_requires_baseline_and_ungated_forbids_it(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO change_run(run_id,pair_id,change_order_id,mode,prompt_version,"
            "question_set_sha256,model,chain_size) VALUES('g1','p','a1x','gated','v','q','m',2)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        add_run(db, mode="ungated", baseline="something")


def test_one_run_per_change_order_and_mode(db):
    add_run(db)
    with pytest.raises(sqlite3.IntegrityError):
        add_run(db, run_id="cr_other")


@pytest.mark.parametrize("mode", ["both", "skip", ""])
def test_mode_check(db, mode):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO change_run(run_id,pair_id,change_order_id,mode,prompt_version,"
            "question_set_sha256,model,chain_size) VALUES('x','p','a1x',?,'v','q','m',2)",
            (mode,),
        )


# --- supersedes eligibility (rev 2 R2) -----------------------------------------------


def edge(con, new_agr="a1x", old_agr="a1", run=None, cite_agr="a1x", grounded=1):
    run = run if run is not None else add_run(con)
    n = add_obligation(con, new_agr)
    add_ref(con, new_agr, n)
    o = add_obligation(con, old_agr)
    add_ref(con, old_agr, o)
    con.execute(
        "INSERT INTO supersedes(obligation_id,superseded_obligation_id,change_order_id,"
        "clause_ref_id,change_run_id) VALUES(?,?,'a1x',?,?)",
        (n, o, add_ref(con, cite_agr, grounded=grounded), run),
    )
    return n, o


def lifecycle(con, oid):
    row = con.execute("SELECT lifecycle FROM visible_obligation WHERE id=?", (oid,)).fetchone()
    return row[0] if row else None


def n_visible_edges(con):
    return con.execute("SELECT count(*) FROM visible_supersedes").fetchone()[0]


def test_ungated_fresh_edge_marks_old_obligation_superseded(db):
    n, o = edge(db)
    assert n_visible_edges(db) == 1
    assert lifecycle(db, o) == "superseded"
    assert lifecycle(db, n) == "pending"


def test_stale_run_edge_is_invisible_and_lifecycle_reverts(db):
    _n, o = edge(db)
    db.execute("UPDATE extraction_run SET run_id='er_new' WHERE source_id='src_a'")
    assert n_visible_edges(db) == 0
    assert lifecycle(db, o) == "pending"


def test_gated_run_edge_is_invisible(db):
    add_run(db)
    gated = add_run(db, mode="gated")
    _n, o = edge(db, run=gated)
    assert n_visible_edges(db) == 0
    assert lifecycle(db, o) == "pending"


def test_equal_endpoints_rejected_by_check(db):
    run = add_run(db)
    n = add_obligation(db, "a1x")
    add_ref(db, "a1x", n)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO supersedes(obligation_id,superseded_obligation_id,change_order_id,"
            "clause_ref_id,change_run_id) VALUES(?,?,'a1x',?,?)",
            (n, n, add_ref(db, "a1x"), run),
        )


def test_superseded_obligation_in_the_change_order_is_invisible(db):
    """W3-2: the old endpoint must be strictly earlier in the chain."""
    _n, o = edge(db, old_agr="a1x")
    assert n_visible_edges(db) == 0
    assert lifecycle(db, o) == "pending"


def test_superseded_obligation_outside_the_chain_is_invisible(db):
    _n, o = edge(db, old_agr="b1")
    assert n_visible_edges(db) == 0
    assert lifecycle(db, o) == "pending"


def test_superseding_obligation_must_belong_to_the_change_order(db):
    _n, o = edge(db, new_agr="a1")
    assert n_visible_edges(db) == 0
    assert lifecycle(db, o) == "pending"


def test_edge_citation_must_be_grounded_in_the_change_order(db):
    _n, o = edge(db, cite_agr="a1")
    assert n_visible_edges(db) == 0
    assert lifecycle(db, o) == "pending"
    _n2, o2 = edge(db, run=db.execute("SELECT id FROM change_run").fetchone()[0], grounded=0)
    assert n_visible_edges(db) == 0
    assert lifecycle(db, o2) == "pending"


def test_ungrounded_superseding_endpoint_does_not_supersede(db):
    n, o = edge(db)
    db.execute("UPDATE clause_ref SET grounded=0 WHERE obligation_id=?", (n,))
    assert n_visible_edges(db) == 0
    assert lifecycle(db, o) == "pending"


# --- visible_change_finding ------------------------------------------------------------


def finding(
    con, run, new_agr="a1x", new_grounded=1, old_agr=None, old_grounded=1, origin=None, ctx_agr=None
):
    new_ref = add_ref(con, new_agr, grounded=new_grounded)
    old_ref = add_ref(con, old_agr, grounded=old_grounded) if old_agr else None
    ctx_ref = add_ref(con, ctx_agr) if ctx_agr else None
    if origin is None:
        origin = "unresolved" if old_agr is None else ("self" if old_agr == "a1x" else "chain")
    return con.execute(
        "INSERT INTO change_finding(change_run_id,kind,category,new_clause_ref_id,"
        "old_clause_ref_id,context_clause_ref_id,old_origin,target_label)"
        " VALUES(?,'supersedes','dates',?,?,?,?,NULL)",
        (run, new_ref, old_ref, ctx_ref, origin),
    ).lastrowid


def visible_findings(con):
    return [r[0] for r in con.execute("SELECT id FROM visible_change_finding ORDER BY id")]


def test_finding_with_grounded_refs_is_visible(db):
    run = add_run(db)
    fid = finding(db, run, old_agr="a1")
    row = db.execute(
        "SELECT change_order_id, mode, run_id, pair_id FROM visible_change_finding WHERE id=?",
        (fid,),
    ).fetchone()
    assert row == ("a1x", "ungated", "cr_ungated", "p")


def test_unresolved_finding_without_old_ref_is_visible(db):
    fid = finding(db, add_run(db))
    assert visible_findings(db) == [fid]


def test_new_ref_must_be_grounded(db):
    finding(db, add_run(db), new_grounded=0)
    assert visible_findings(db) == []


def test_new_ref_must_be_in_the_change_order(db):
    finding(db, add_run(db), new_agr="a1", old_agr="a1")
    assert visible_findings(db) == []


def test_old_ref_must_be_grounded(db):
    finding(db, add_run(db), old_agr="a1", old_grounded=0)
    assert visible_findings(db) == []


def test_old_ref_must_be_in_the_chain(db):
    finding(db, add_run(db), old_agr="b1", origin="chain")
    assert visible_findings(db) == []


def test_self_origin_iff_old_ref_in_change_order(db):
    run = add_run(db)
    ok_self = finding(db, run, old_agr="a1x", origin="self")
    finding(db, run, old_agr="a1x", origin="chain")
    finding(db, run, old_agr="a1", origin="self")
    assert visible_findings(db) == [ok_self]


def test_context_ref_must_be_in_the_change_order(db):
    run = add_run(db)
    ok = finding(db, run, ctx_agr="a1x")
    finding(db, run, ctx_agr="a1")
    assert visible_findings(db) == [ok]


def test_stale_run_findings_are_invisible(db):
    finding(db, add_run(db), old_agr="a1")
    db.execute("UPDATE extraction_run SET textdoc_sha256='changed' WHERE source_id='src_a'")
    assert visible_findings(db) == []


def test_incomplete_run_findings_are_invisible(db):
    finding(db, add_run(db, completed=False), old_agr="a1")
    assert visible_findings(db) == []


def test_unresolved_iff_no_old_ref(db):
    run = add_run(db)
    with pytest.raises(sqlite3.IntegrityError):
        finding(db, run, old_agr="a1", origin="unresolved")
    with pytest.raises(sqlite3.IntegrityError):
        finding(db, run, old_agr=None, origin="chain")


@pytest.mark.parametrize(
    "col,val",
    [
        ("kind", "conflict"),
        ("category", "rent"),
        ("old_origin", "base"),
        ("target_resolution", "clause"),
    ],
)
def test_finding_enum_checks(db, col, val):
    run = add_run(db)
    fid = finding(db, run, old_agr="a1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f"UPDATE change_finding SET {col}=? WHERE id=?", (val, fid))


def test_gate_decision_v3_columns(db):
    run = add_run(db)
    db.execute(
        "INSERT INTO gate_decision(change_run_id,change_order_id,question,backend,tier,answer,"
        "confidence,samples_json,evidence_json,run_check) VALUES(?,'a1x','touches_sla','haiku',"
        "'classifier',0,1.0,'[false,false,false]','[]',0)",
        (run,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO gate_decision(change_order_id,question,backend,tier) "
            "VALUES('a1x','q','b','model')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO gate_decision(change_order_id,question,backend,run_check) "
            "VALUES('a1x','q','b',2)"
        )
