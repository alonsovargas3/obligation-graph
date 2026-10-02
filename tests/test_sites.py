"""Task 33: cited site pins (wave 4 rev 2 W4-8, W4-9).

A sources.yaml entry may carry `site: {segment_id, quote, name, location}`. The
extraction writer verifies the pin (the quote grounds exactly in that segment; name and
location are substrings of the quote) and writes one immutable `site` row (unique on
name, location) plus one cited `agreement_site` binding, inside the snapshot
transaction. An invalid pin refuses the whole write (WriteRefused("site_pin_invalid"))
and keeps the previous snapshot. Documents are SYNTHETIC.
"""

import hashlib
import sqlite3

import pytest
from extract_fakes import FakeClient, build_doc, echo_responder

from og.extract.types import Attempt, RunInfo, VerifyResult, WriteRefused
from og.store.db import SchemaOutdated, connect
from og.store.writer import write_snapshot

ADDR = "Premises located at 55 Main Street, Springfield, Ohio."
PIN = {
    "segment_id": "p0001",
    "quote": "55 Main Street, Springfield, Ohio",
    "name": "55 Main Street",
    "location": "Springfield, Ohio",
}


def doc_for(doc_id, sha):
    return build_doc(
        [
            ("1", "Premises", [ADDR]),
            ("2", "Rent", ["Tenant shall pay Base Rent of $1,000 per month."]),
        ],
        doc_id=doc_id,
        sha=sha,
    )


DOCS = {"lease_a": doc_for("lease_a", "a" * 64), "lease_b": doc_for("lease_b", "b" * 64)}


def write(con, doc_id, pin=PIN, run_id="r1"):
    doc = DOCS[doc_id]
    source = {
        "id": doc_id,
        "url": f"https://www.sec.gov/{doc_id}.htm",
        "filer": "Filer",
        "filing_date": "2011-03-09",
        "form": "10-K",
        "exhibit": "10.1",
        "local_path": f"data/raw/{doc_id}.htm",
        "sha256": doc.source_sha256,
    }
    if pin is not None:
        source["site"] = dict(pin)
    agreement = {
        "id": doc_id,
        "title": doc_id,
        "type": "lease",
        "effective_date": None,
        "base_agreement_id": None,
        "is_form": False,
    }
    run = RunInfo(
        run_id=f"{doc_id}-{run_id}",
        prompt_version="extract_v1@abc12345",
        model="claude-sonnet-5-5",
        textdoc_sha256=hashlib.sha256(doc.to_json().encode()).hexdigest(),
        attempts=[Attempt("claude-sonnet-5-5", 10, 5, 0, 0, False)],
    )
    write_snapshot(
        con,
        source=source,
        agreement=agreement,
        doc=doc,
        run=run,
        result=VerifyResult([], [], [], [], []),
    )


@pytest.fixture
def con(tmp_path):
    return connect(tmp_path / "g.db")


def bindings(con):
    return con.execute(
        "SELECT agreement_id, name, location, span_text FROM visible_site_binding"
        " ORDER BY agreement_id"
    ).fetchall()


def test_pin_writes_one_cited_site(con):
    write(con, "lease_a")
    assert bindings(con) == [
        ("lease_a", "55 Main Street", "Springfield, Ohio", "55 Main Street, Springfield, Ohio")
    ]
    ref = con.execute(
        "SELECT c.char_start, c.char_end, c.span_text, c.grounded FROM agreement_site a"
        " JOIN clause_ref c ON c.id = a.clause_ref_id"
    ).fetchone()
    text = DOCS["lease_a"].text
    assert text[ref[0] : ref[1]] == ref[2] == PIN["quote"]
    assert ref[3] == 1


def test_repeat_extraction_is_idempotent(con):
    write(con, "lease_a", run_id="r1")
    write(con, "lease_a", run_id="r2")
    assert con.execute("SELECT count(*) FROM site").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM agreement_site").fetchone()[0] == 1
    assert len(bindings(con)) == 1


def test_changed_pin_replaces_the_binding(con):
    write(con, "lease_a")
    write(
        con,
        "lease_a",
        pin={**PIN, "quote": "55 Main Street", "location": "55 Main"},
        run_id="r2",
    )
    assert bindings(con) == [("lease_a", "55 Main Street", "55 Main", "55 Main Street")]
    assert con.execute("SELECT count(*) FROM agreement_site").fetchone()[0] == 1


def test_removed_pin_removes_the_binding(con):
    write(con, "lease_a")
    write(con, "lease_a", pin=None, run_id="r2")
    assert bindings(con) == []
    assert con.execute("SELECT count(*) FROM agreement_site").fetchone()[0] == 0


def test_shared_site_is_one_row_with_two_bindings(con):
    write(con, "lease_a")
    site_row = con.execute("SELECT id, name, location FROM site").fetchone()
    write(con, "lease_b")
    assert con.execute("SELECT id, name, location FROM site").fetchall() == [site_row]
    assert [b[0] for b in bindings(con)] == ["lease_a", "lease_b"]
    # Re-extracting one agreement never touches the other's binding or the site row.
    write(con, "lease_a", run_id="r2")
    assert con.execute("SELECT id, name, location FROM site").fetchall() == [site_row]
    assert [b[0] for b in bindings(con)] == ["lease_a", "lease_b"]


@pytest.mark.parametrize(
    "bad",
    [
        {**PIN, "quote": "55 Main Street, Springfield, Iowa"},  # not in the segment
        {**PIN, "segment_id": "p0099"},  # unknown segment
        {**PIN, "segment_id": "p0002"},  # quote is in another segment
        {**PIN, "name": "56 Main Street"},  # name not copied from the quote
        {**PIN, "location": "Dayton, Ohio"},  # location not copied from the quote
    ],
)
def test_invalid_pin_refuses_and_keeps_previous_snapshot(con, bad):
    write(con, "lease_a")
    before = (
        bindings(con),
        con.execute("SELECT run_id FROM extraction_run").fetchall(),
    )
    with pytest.raises(WriteRefused) as err:
        write(con, "lease_a", pin=bad, run_id="r2")
    assert err.value.args[0] == "site_pin_invalid"
    after = (
        bindings(con),
        con.execute("SELECT run_id FROM extraction_run").fetchall(),
    )
    assert after == before


def test_invalid_pin_on_first_write_writes_nothing(con):
    with pytest.raises(WriteRefused):
        write(con, "lease_a", pin={**PIN, "name": "nowhere"})
    assert con.execute("SELECT count(*) FROM agreement").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM site").fetchone()[0] == 0


def test_revoked_site_ref_hides_the_binding(con):
    write(con, "lease_a")
    con.execute(
        "UPDATE clause_ref SET grounded = 0 WHERE id = (SELECT clause_ref_id FROM agreement_site)"
    )
    assert bindings(con) == []


def test_v3_file_is_refused(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE x (y)")
    old.execute("PRAGMA user_version = 3")
    old.commit()
    old.close()
    with pytest.raises(SchemaOutdated):
        connect(path)


def test_extract_cli_writes_the_pin_from_sources(tmp_path, monkeypatch):
    """The CLI passes the sources.yaml entry (with its site pin) to the writer."""
    from pathlib import Path

    import yaml

    from og.extract.__main__ import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SENTINEL-0000-do-not-log-0000")
    monkeypatch.setenv("OG_EXTRACT_CHUNK_CHARS", "300")
    doc = DOCS["lease_a"]
    Path("data/text").mkdir(parents=True)
    doc.save(Path("data/text") / "lease_a.json")
    entry = {
        "id": "lease_a",
        "url": "https://www.sec.gov/lease_a.htm",
        "filer": "Filer",
        "form": "10-K",
        "filing_date": "2011-03-09",
        "exhibit": "10.1",
        "title": "Lease A (synthetic)",
        "is_form": False,
        "local_path": "data/raw/lease_a.htm",
        "sha256": doc.source_sha256,
        "agreement_type": "lease",
        "amends": None,
        "effective_date": None,
        "site": dict(PIN),
    }
    Path("data/sources.yaml").write_text(yaml.safe_dump({"documents": [entry]}), encoding="utf-8")
    assert main([], client=FakeClient(responder=echo_responder)) == 0
    con = connect("data/graph.db")
    assert bindings(con) == [
        ("lease_a", "55 Main Street", "Springfield, Ohio", "55 Main Street, Springfield, Ohio")
    ]
