"""Schema v4 (wave 4): agreement sites and the citation-bearing projections.

Plan: docs/superpowers/plans/2026-10-02-wave4-mcp-ui-eval-readme.md, Rev 2 W4-8/W4-9
and Rev 2.1 R2-1. Synthetic checks build tiny graphs; real checks run on a copy of
tests/fixtures/graph/real_v5.db. Cross-agreement corruptions drop the citation
triggers inside the copy only, to isolate the view predicates (as in Astra round 3).
"""

import sqlite3

import pytest
from graph_fixture import (
    BASE,
    CARBONITE,
    OBL_34,
    OBL_34_REF,
    REF_LANDLORD,
    REF_SITE_CARBONITE,
    VISIBLE,
    copy_db,
    open_db,
)

from og.store.db import connect

PROJECTIONS = {
    "visible_obligation_clause": ("obligation_id",),
    "visible_party_binding": ("agreement_id", "party_id", "role"),
    "visible_event_binding": ("event_id",),
    "visible_site_binding": ("agreement_id", "site_id"),
    "visible_change_finding_ref": ("finding_id", "side"),
}
REF_COLS = ("clause_ref_id", "section", "page", "char_start", "char_end", "span_text")


@pytest.fixture
def real(tmp_path):
    return open_db(copy_db(tmp_path))


@pytest.fixture
def syn(tmp_path):
    """SYNTHETIC: two agreements, one obligation, one party, one event, one site."""
    con = connect(tmp_path / "syn.db")
    con.execute("INSERT INTO source(id,url,local_path,sha256) VALUES('s','u','p','h')")
    for a in ("a1", "b1"):
        con.execute(
            "INSERT INTO agreement(id,title,type,source_id) VALUES(?,'T','lease','s')", (a,)
        )
    return con


def ref(con, agreement="a1", oid=None, grounded=1, span="Tenant shall"):
    return con.execute(
        "INSERT INTO clause_ref(obligation_id,agreement_id,section,page,char_start,char_end,"
        "span_text,grounded) VALUES(?,?,'1',1,0,?,?,?)",
        (oid, agreement, len(span), span, grounded),
    ).lastrowid


def obligation(con, agreement="a1"):
    return con.execute(
        "INSERT INTO obligation(agreement_id,type,description,status)"
        " VALUES(?,'payment','d','active')",
        (agreement,),
    ).lastrowid


def count(con, view, where="1=1", args=()):
    return con.execute(f"SELECT count(*) FROM {view} WHERE {where}", args).fetchone()[0]


# ---------------------------------------------------------------- tables


def test_projections_exist_with_ref_columns(syn):
    for view, keys in PROJECTIONS.items():
        cols = [r[1] for r in syn.execute(f"PRAGMA table_info({view})")]
        assert cols, view
        for c in (*keys, *REF_COLS):
            assert c in cols, (view, c)


def test_site_identity_is_unique(syn):
    syn.execute("INSERT INTO site(name,location) VALUES('55 Middlesex Turnpike','Bedford')")
    with pytest.raises(sqlite3.IntegrityError):
        syn.execute("INSERT INTO site(name,location) VALUES('55 Middlesex Turnpike','Bedford')")


def test_agreement_site_requires_ref_and_is_unique(syn):
    sid = syn.execute("INSERT INTO site(name,location) VALUES('S','L')").lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        syn.execute("INSERT INTO agreement_site(agreement_id,site_id) VALUES('a1',?)", (sid,))
    r = ref(syn)
    syn.execute(
        "INSERT INTO agreement_site(agreement_id,site_id,clause_ref_id) VALUES('a1',?,?)",
        (sid, r),
    )
    with pytest.raises(sqlite3.IntegrityError):
        syn.execute(
            "INSERT INTO agreement_site(agreement_id,site_id,clause_ref_id) VALUES('a1',?,?)",
            (sid, ref(syn)),
        )


# ---------------------------------------------------------------- synthetic projections


def test_obligation_clause_only_grounded_same_agreement(syn):
    oid = obligation(syn)
    good = ref(syn, oid=oid)
    ref(syn, oid=oid, grounded=0, span="ungrounded")
    rows = syn.execute(
        "SELECT clause_ref_id FROM visible_obligation_clause WHERE obligation_id=?", (oid,)
    ).fetchall()
    assert rows == [(good,)]
    syn.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (good,))
    assert count(syn, "visible_obligation_clause") == 0


def test_site_binding_grounded_same_agreement(syn):
    sid = syn.execute("INSERT INTO site(name,location) VALUES('S','L')").lastrowid
    r = ref(syn, agreement="b1")  # cited from another agreement
    syn.execute(
        "INSERT INTO agreement_site(agreement_id,site_id,clause_ref_id) VALUES('a1',?,?)",
        (sid, r),
    )
    assert count(syn, "visible_site_binding") == 0
    syn.execute("UPDATE clause_ref SET agreement_id='a1' WHERE id=?", (r,))
    assert count(syn, "visible_site_binding") == 1
    syn.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (r,))
    assert count(syn, "visible_site_binding") == 0


def test_event_binding_grounded_same_agreement(syn):
    r = ref(syn)
    syn.execute(
        "INSERT INTO event(agreement_id,name,date,clause_ref_id) VALUES('a1','D','2020-01-01',?)",
        (r,),
    )
    assert count(syn, "visible_event_binding") == 1
    syn.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (r,))
    assert count(syn, "visible_event_binding") == 0


def test_party_binding_carries_name_and_ref(syn):
    syn.execute("INSERT INTO party(id,name) VALUES(1,'Landlord Co')")
    r = ref(syn)
    syn.execute(
        "INSERT INTO agreement_party(agreement_id,party_id,role,clause_ref_id)"
        " VALUES('a1',1,'landlord',?)",
        (r,),
    )
    row = syn.execute(
        "SELECT agreement_id, name, role, clause_ref_id, span_text FROM visible_party_binding"
    ).fetchall()
    assert row == [("a1", "Landlord Co", "landlord", r, "Tenant shall")]
    syn.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (r,))
    assert count(syn, "visible_party_binding") == 0


# ---------------------------------------------------------------- real graph


def test_real_visible_obligation_query_succeeds(real):
    assert count(real, "visible_obligation") == VISIBLE
    assert real.execute("SELECT id FROM visible_obligation LIMIT 1").fetchone() is not None


def test_real_projection_counts(real):
    assert count(real, "visible_obligation_clause") == VISIBLE
    assert count(real, "visible_party_binding") == 4
    assert count(real, "visible_event_binding") == 16
    assert count(real, "visible_site_binding") == 4
    assert count(real, "visible_change_finding_ref") == 56


@pytest.mark.parametrize("view,keys", sorted(PROJECTIONS.items()))
def test_real_one_row_per_owner_and_ref(real, view, keys):
    group = ", ".join((*keys, "clause_ref_id"))
    dup = real.execute(
        f"SELECT {group}, count(*) FROM {view} GROUP BY {group} HAVING count(*) > 1"
    ).fetchall()
    assert dup == []


@pytest.mark.parametrize("view", sorted(PROJECTIONS))
def test_real_projection_refs_are_grounded_slices(real, view):
    bad = real.execute(
        f"SELECT count(*) FROM {view} v JOIN clause_ref c ON c.id = v.clause_ref_id"
        " WHERE c.grounded <> 1 OR c.span_text <> v.span_text"
        " OR length(v.span_text) <> v.char_end - v.char_start"
    ).fetchone()[0]
    assert bad == 0


def test_real_ref_65_revocation_removes_exactly_the_landlord_binding(real):
    before = set(real.execute("SELECT agreement_id, name, role FROM visible_party_binding"))
    real.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (REF_LANDLORD,))
    after = set(real.execute("SELECT agreement_id, name, role FROM visible_party_binding"))
    assert before - after == {(BASE, "Digital 55 Middlesex, LLC", "landlord")}
    assert after - before == set()
    assert count(real, "visible_obligation", "id=?", (OBL_34,)) == 1
    assert real.execute(
        "SELECT clause_ref_id FROM visible_obligation_clause WHERE obligation_id=?", (OBL_34,)
    ).fetchall() == [(OBL_34_REF,)]


def test_real_extra_ungrounded_citation_is_not_projected(real):
    real.execute(
        "INSERT INTO clause_ref(obligation_id,agreement_id,section,page,char_start,char_end,"
        "span_text,grounded) VALUES(?,?,'1',1,0,5,'Xyzzy',0)",
        (OBL_34, BASE),
    )
    rows = real.execute(
        "SELECT clause_ref_id FROM visible_obligation_clause WHERE obligation_id=?", (OBL_34,)
    ).fetchall()
    assert rows == [(OBL_34_REF,)]


def test_real_site_revocation_removes_only_that_site(real):
    real.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (REF_SITE_CARBONITE,))
    rows = [r[0] for r in real.execute("SELECT agreement_id FROM visible_site_binding")]
    assert CARBONITE not in rows and len(rows) == 3


def _first_ref(con, view):
    return con.execute(
        f"SELECT clause_ref_id FROM {view} ORDER BY clause_ref_id LIMIT 1"
    ).fetchone()[0]


@pytest.mark.parametrize("view", sorted(PROJECTIONS))
def test_real_ungrounded_ref_is_absent(real, view):
    rid = _first_ref(real, view)
    real.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (rid,))
    assert count(real, view, "clause_ref_id=?", (rid,)) == 0


@pytest.mark.parametrize("view", sorted(PROJECTIONS))
def test_real_cross_agreement_ref_is_absent(real, view):
    for (name,) in real.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        real.execute(f"DROP TRIGGER {name}")
    rid = _first_ref(real, view)
    agreement = real.execute("SELECT agreement_id FROM clause_ref WHERE id=?", (rid,)).fetchone()[0]
    other = CARBONITE if agreement != CARBONITE else BASE
    real.execute("UPDATE clause_ref SET agreement_id=? WHERE id=?", (other, rid))
    assert count(real, view, "clause_ref_id=?", (rid,)) == 0


def test_real_change_finding_ref_sides(real):
    sides = dict(
        real.execute("SELECT side, count(*) FROM visible_change_finding_ref GROUP BY side")
    )
    assert sides == {"new": 28, "old": 12, "context": 16}
