import sqlite3

import pytest

from og.store.db import connect

SPAN = "Tenant shall"
SPAN_END = len(SPAN)


@pytest.fixture
def db(tmp_path):
    con = connect(tmp_path / "g.db")
    con.execute("INSERT INTO source(id,url,local_path,sha256) VALUES('src','u','p','h')")
    con.execute("INSERT INTO agreement(id,title,type,source_id) VALUES('a1','Lease','lease','src')")
    con.execute(
        "INSERT INTO agreement(id,title,type,source_id,base_agreement_id)"
        " VALUES('a1x','Amendment 1','amendment','src','a1')"
    )
    con.execute("INSERT INTO agreement(id,title,type,source_id) VALUES('b1','Other','lease','src')")
    con.execute("INSERT INTO party(id,name) VALUES(1,'Landlord Co'),(2,'Tenant Co')")
    return con


def add_obligation(con, agreement="a1", status="active", due=None, anchor=None, offset=None):
    cur = con.execute(
        "INSERT INTO obligation(agreement_id,type,owed_by,owed_to,description,status,due_date,"
        "anchor_event_id,offset_days) VALUES(?,'payment',2,1,'pay rent',?,?,?,?)",
        (agreement, status, due, anchor, offset),
    )
    return cur.lastrowid


def add_ref(con, oid=None, grounded=1, agreement="a1", start=0, end=SPAN_END, text=SPAN):
    cur = con.execute(
        "INSERT INTO clause_ref(obligation_id,agreement_id,section,page,char_start,char_end,"
        "span_text,grounded) VALUES(?,?,'1.1',1,?,?,?,?)",
        (oid, agreement, start, end, text, grounded),
    )
    return cur.lastrowid


def add_event(con, agreement="a1", date=None, ref=None):
    cur = con.execute(
        "INSERT INTO event(agreement_id,name,date,clause_ref_id) VALUES(?,'Commencement Date',?,?)",
        (agreement, date, ref),
    )
    return cur.lastrowid


def visible(con):
    return con.execute(
        "SELECT id, status, effective_due, lifecycle FROM visible_obligation"
    ).fetchall()


def test_connect_is_idempotent(tmp_path):
    connect(tmp_path / "g.db").close()
    connect(tmp_path / "g.db").close()


def test_foreign_keys_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        add_obligation(db, agreement="nope")


def test_ungrounded_obligation_is_invisible(db):
    oid = add_obligation(db)
    add_ref(db, oid, grounded=0)
    assert visible(db) == []
    add_ref(db, oid, grounded=1)
    assert len(visible(db)) == 1


def test_obligation_without_any_ref_is_invisible(db):
    add_obligation(db)
    assert visible(db) == []


def test_ref_from_other_agreement_is_rejected(db):
    oid = add_obligation(db)
    with pytest.raises(sqlite3.IntegrityError):
        add_ref(db, oid, agreement="b1")
    assert visible(db) == []


@pytest.mark.parametrize(
    "start,end,text",
    [(-5, 7, SPAN), (5, 5, SPAN), (0, 12, ""), (10, 3, SPAN), (0, 5, SPAN)],
)
def test_clause_ref_range_checks(db, start, end, text):
    oid = add_obligation(db)
    with pytest.raises(sqlite3.IntegrityError):
        add_ref(db, oid, start=start, end=end, text=text)


def test_status_check_constraint(db):
    with pytest.raises(sqlite3.IntegrityError):
        add_obligation(db, status="maybe")


def test_blank_status_allowed(db):
    oid = add_obligation(db, status="blank")
    add_ref(db, oid)
    assert visible(db)[0][1] == "blank"


def test_direct_due_date(db):
    oid = add_obligation(db, due="2026-03-01")
    add_ref(db, oid)
    assert visible(db)[0][2:] == ("2026-03-01", "scheduled")


@pytest.mark.parametrize("bad", ["garbage", "2026-02-30", "2026-1-5", "03/01/2026"])
def test_invalid_due_date_rejected(db, bad):
    with pytest.raises(sqlite3.IntegrityError):
        add_obligation(db, due=bad)


def test_leap_day_due_date_ok(db):
    add_obligation(db, due="2028-02-29")


def test_relative_deadline_needs_grounded_event(db):
    ref = add_ref(db)
    ev = add_event(db, date="2026-01-01", ref=None)
    oid = add_obligation(db, anchor=ev, offset=30)
    add_ref(db, oid)
    assert visible(db)[0][2:] == (None, "pending")
    db.execute("UPDATE event SET clause_ref_id=? WHERE id=?", (ref, ev))
    assert visible(db)[0][2:] == ("2026-01-31", "scheduled")
    db.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (ref,))
    assert visible(db)[0][2:] == (None, "pending")


def test_relative_deadline_unknown_event_date_is_pending(db):
    ev = add_event(db, date=None, ref=add_ref(db))
    oid = add_obligation(db, anchor=ev, offset=30)
    add_ref(db, oid)
    assert visible(db)[0][2:] == (None, "pending")


def test_negative_offset(db):
    ev = add_event(db, date="2026-03-01", ref=add_ref(db))
    oid = add_obligation(db, anchor=ev, offset=-1)
    add_ref(db, oid)
    assert visible(db)[0][2] == "2026-02-28"


def test_amendment_may_anchor_on_base_agreement_event(db):
    ev = add_event(db, agreement="a1", date="2026-01-01", ref=add_ref(db))
    oid = add_obligation(db, agreement="a1x", anchor=ev, offset=10)
    add_ref(db, oid, agreement="a1x")
    assert visible(db)[0][2] == "2026-01-11"


def test_unrelated_agreement_event_is_not_used(db):
    ev = add_event(db, agreement="b1", date="2026-01-01", ref=add_ref(db, agreement="b1"))
    oid = add_obligation(db, anchor=ev, offset=10)
    add_ref(db, oid)
    assert visible(db)[0][2:] == (None, "pending")


def test_fractional_offset_rejected(db):
    ev = add_event(db, date="2026-01-01", ref=add_ref(db))
    with pytest.raises(sqlite3.IntegrityError):
        add_obligation(db, anchor=ev, offset=1.9)


def test_anchor_and_offset_come_together(db):
    ev = add_event(db, date="2026-01-01", ref=add_ref(db))
    with pytest.raises(sqlite3.IntegrityError):
        add_obligation(db, anchor=ev, offset=None)
    with pytest.raises(sqlite3.IntegrityError):
        add_obligation(db, anchor=None, offset=10)


def test_direct_and_relative_due_are_exclusive(db):
    ev = add_event(db, date="2026-01-01", ref=add_ref(db))
    with pytest.raises(sqlite3.IntegrityError):
        add_obligation(db, due="2026-02-01", anchor=ev, offset=10)


def test_superseded_lifecycle(db):
    oid = add_obligation(db, status="superseded", due="2026-03-01")
    add_ref(db, oid)
    assert visible(db)[0][3] == "superseded"


def test_edges_require_clause_ref(db):
    a = add_obligation(db)
    b = add_obligation(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO triggers(obligation_id,triggered_by_obligation_id,kind,clause_ref_id)"
            " VALUES(?,?,'default',NULL)",
            (a, b),
        )


EDGE_SQL = {
    "supersedes": "INSERT INTO supersedes(obligation_id,superseded_obligation_id,"
    "change_order_id,clause_ref_id) VALUES(?,?,'a1x',?)",
    "guarantees": "INSERT INTO guarantees(guarantee_obligation_id,guaranteed_obligation_id,"
    "clause_ref_id) VALUES(?,?,?)",
    "triggers": "INSERT INTO triggers(obligation_id,triggered_by_obligation_id,kind,"
    "clause_ref_id) VALUES(?,?,'default',?)",
}
# The agreement an edge's citation must come from, per edge type.
EDGE_REF_AGREEMENT = {"supersedes": "a1x", "guarantees": "a1", "triggers": "a1"}


@pytest.mark.parametrize("table", ["supersedes", "guarantees", "triggers"])
def test_edge_views_require_grounded_ref_and_visible_endpoints(db, table):
    a, b = add_obligation(db), add_obligation(db)
    add_ref(db, a)
    add_ref(db, b)
    edge_ref = add_ref(db, grounded=0, agreement=EDGE_REF_AGREEMENT[table])
    db.execute(EDGE_SQL[table], (a, b, edge_ref))
    count = f"SELECT count(*) FROM visible_{table}"
    assert db.execute(count).fetchone()[0] == 0
    db.execute("UPDATE clause_ref SET grounded=1 WHERE id=?", (edge_ref,))
    assert db.execute(count).fetchone()[0] == 1
    db.execute("UPDATE clause_ref SET grounded=0 WHERE obligation_id=?", (b,))
    assert db.execute(count).fetchone()[0] == 0


@pytest.mark.parametrize("table", ["supersedes", "guarantees", "triggers"])
def test_edge_citation_from_unrelated_agreement_is_invisible(db, table):
    a, b = add_obligation(db), add_obligation(db)
    add_ref(db, a)
    add_ref(db, b)
    db.execute(EDGE_SQL[table], (a, b, add_ref(db, agreement="b1")))
    assert db.execute(f"SELECT count(*) FROM visible_{table}").fetchone()[0] == 0


def test_event_citation_must_match_event_agreement(db):
    with pytest.raises(sqlite3.IntegrityError):
        add_event(db, agreement="a1", date="2026-01-01", ref=add_ref(db, agreement="b1"))


def test_event_citation_update_path_checked(db):
    ev = add_event(db, agreement="a1", date="2026-01-01", ref=add_ref(db))
    other = add_ref(db, agreement="b1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE event SET clause_ref_id=? WHERE id=?", (other, ev))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE event SET agreement_id='b1' WHERE id=?", (ev,))


def test_view_ignores_event_whose_citation_moved_agreement(db):
    ref = add_ref(db)
    ev = add_event(db, date="2026-01-01", ref=ref)
    oid = add_obligation(db, anchor=ev, offset=30)
    add_ref(db, oid)
    assert visible(db)[0][2] == "2026-01-31"
    db.execute("UPDATE clause_ref SET agreement_id='b1' WHERE id=?", (ref,))
    assert visible(db)[0][2:] == (None, "pending")


def test_defined_term_citation_must_match(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO defined_term(agreement_id,term,clause_ref_id) VALUES('a1','Rent',?)",
            (add_ref(db, agreement="b1"),),
        )


def test_defined_term_view_ignores_moved_citation(db):
    ref = add_ref(db)
    db.execute(
        "INSERT INTO defined_term(agreement_id,term,clause_ref_id) VALUES('a1','Rent',?)", (ref,)
    )
    db.execute("UPDATE clause_ref SET agreement_id='b1' WHERE id=?", (ref,))
    assert db.execute("SELECT count(*) FROM visible_defined_term").fetchone()[0] == 0


def test_defined_term_view_requires_grounding(db):
    ref = add_ref(db, grounded=0)
    db.execute(
        "INSERT INTO defined_term(agreement_id,term,clause_ref_id) VALUES('a1','Rent',?)", (ref,)
    )
    assert db.execute("SELECT count(*) FROM visible_defined_term").fetchone()[0] == 0
    db.execute("UPDATE clause_ref SET grounded=1 WHERE id=?", (ref,))
    assert db.execute("SELECT count(*) FROM visible_defined_term").fetchone()[0] == 1


RUN_SQL = (
    "INSERT INTO extraction_run(run_id,source_id,prompt_version,model,textdoc_sha256)"
    " VALUES(?,'src','v1','m','t')"
)


def test_extraction_run_unique_per_source_and_prompt(db):
    db.execute(RUN_SQL, ("r1",))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(RUN_SQL, ("r2",))
