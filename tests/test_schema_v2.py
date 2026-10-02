import sqlite3

import pytest

from og.store.db import SCHEMA_VERSION, SchemaOutdated, connect

SPAN = "Tenant shall"


@pytest.fixture
def db(tmp_path):
    con = connect(tmp_path / "g.db")
    con.execute("INSERT INTO source(id,url,local_path,sha256) VALUES('src','u','p','h')")
    con.execute("INSERT INTO agreement(id,title,type,source_id) VALUES('a1','Lease','lease','src')")
    con.execute("INSERT INTO agreement(id,title,type,source_id) VALUES('b1','Other','lease','src')")
    con.execute("INSERT INTO party(id,name) VALUES(1,'Landlord Co')")
    return con


def add_ref(con, agreement="a1", grounded=1):
    cur = con.execute(
        "INSERT INTO clause_ref(agreement_id,section,page,char_start,char_end,span_text,grounded)"
        " VALUES(?,'1',1,0,?,?,?)",
        (agreement, len(SPAN), SPAN, grounded),
    )
    return cur.lastrowid


def test_fresh_connect_sets_user_version(tmp_path):
    con = connect(tmp_path / "g.db")
    assert SCHEMA_VERSION == 5
    assert con.execute("PRAGMA user_version").fetchone()[0] == 5


def test_reconnect_is_fine(tmp_path):
    connect(tmp_path / "g.db").close()
    con = connect(tmp_path / "g.db")
    assert con.execute("PRAGMA user_version").fetchone()[0] == 5


def test_outdated_file_is_refused(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE source (id TEXT PRIMARY KEY)")
    old.execute("PRAGMA user_version = 0")
    old.commit()
    old.close()
    with pytest.raises(SchemaOutdated, match="delete"):
        connect(path)


def test_v2_file_is_refused(tmp_path):
    """Wave 3: a schema-v2 graph.db is rebuilt, not migrated (cached re-extraction is free)."""
    path = tmp_path / "v2.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE source (id TEXT PRIMARY KEY)")
    old.execute("PRAGMA user_version = 2")
    old.commit()
    old.close()
    with pytest.raises(SchemaOutdated, match="make extract"):
        connect(path)


def test_v3_file_is_refused(tmp_path):
    """Wave 4: a schema-v3 graph.db is rebuilt, not migrated (recorded responses replay at $0)."""
    path = tmp_path / "v3.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE source (id TEXT PRIMARY KEY)")
    old.execute("PRAGMA user_version = 3")
    old.commit()
    old.close()
    with pytest.raises(SchemaOutdated, match="make extract"):
        connect(path)


def test_v4_file_is_refused(tmp_path):
    """Wave 5: a schema-v4 graph.db is rebuilt, not migrated (recorded responses replay at $0)."""
    path = tmp_path / "v4.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE source (id TEXT PRIMARY KEY)")
    old.execute("PRAGMA user_version = 4")
    old.commit()
    old.close()
    with pytest.raises(SchemaOutdated, match="make extract"):
        connect(path)


def test_agreement_party_requires_clause_ref(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO agreement_party(agreement_id,party_id,role) VALUES('a1',1,'landlord')"
        )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO extraction_run(source_id,prompt_version,model,textdoc_sha256)"
        " VALUES('src','v1','m','t')",
        "INSERT INTO extraction_run(run_id,source_id,prompt_version,model)"
        " VALUES('r1','src','v1','m')",
    ],
)
def test_extraction_run_requires_run_id_and_textdoc_sha(db, sql):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql)


def test_extraction_run_columns(db):
    db.execute(
        "INSERT INTO extraction_run(run_id,source_id,prompt_version,model,textdoc_sha256)"
        " VALUES('r1','src','v1','m','t')"
    )
    row = db.execute(
        "SELECT model_attempts_json, completed_at FROM extraction_run WHERE run_id='r1'"
    ).fetchone()
    assert row == ("[]", None)


def visible_parties(con):
    return con.execute("SELECT count(*) FROM visible_agreement_party").fetchone()[0]


def test_visible_agreement_party_requires_grounded_ref(db):
    ref = add_ref(db, grounded=0)
    db.execute(
        "INSERT INTO agreement_party(agreement_id,party_id,role,clause_ref_id)"
        " VALUES('a1',1,'landlord',?)",
        (ref,),
    )
    assert visible_parties(db) == 0
    db.execute("UPDATE clause_ref SET grounded=1 WHERE id=?", (ref,))
    assert visible_parties(db) == 1


def test_visible_agreement_party_ignores_foreign_agreement_ref(db):
    ref = add_ref(db, agreement="b1")
    db.execute(
        "INSERT INTO agreement_party(agreement_id,party_id,role,clause_ref_id)"
        " VALUES('a1',1,'landlord',?)",
        (ref,),
    )
    assert visible_parties(db) == 0
