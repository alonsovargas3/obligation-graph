"""Task 30: og.query on the real graph (wave 4 Rev 2 W4-1, W4-6, W4-7, W4-8, W4-10, W4-11).

Every check runs on a copy of tests/fixtures/graph/real_v5.db inside a workspace
layout (OG_WORKSPACE), so the committed fixture is never written.
"""

import hashlib

import pytest
import yaml
from graph_fixture import (
    A1,
    A3,
    APPLIED,
    BASE,
    CARBONITE,
    CC_CHAIN,
    LANDLORD_PAYEE,
    OBL_34,
    OBL_34_REF,
    PAYMENTS,
    PER_AGREEMENT,
    REDACTED,
    REDACTED_ROWS,
    REF_LANDLORD,
    REF_SITE_CARBONITE,
    TENANT_PAYEE,
    UNRESOLVED_PARTY,
    VISIBLE,
    make_workspace,
    open_db,
    textdoc,
)

from og import query
from og.query import (
    CHANGE_STATUSES,
    MARKERS,
    MAX_LIMIT,
    PENDING_NOTE,
    change_order,
    get_obligations,
    list_agreements,
    upcoming_deadlines,
)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    return make_workspace(tmp_path, monkeypatch)


@pytest.fixture
def con(ws):
    c = open_db(ws / "data" / "graph.db")
    yield c
    c.close()


def all_obligations(con, **filters):
    out, offset = [], 0
    while True:
        page = get_obligations(con, limit=MAX_LIMIT, offset=offset, **filters)
        out.extend(page["obligations"])
        if not page["truncated"]:
            return out
        offset += page["returned"]


def assert_clause_is_slice(clause):
    doc = textdoc(clause["agreement_id"])
    assert doc.text[clause["char_start"] : clause["char_end"]] == clause["span_text"]


# ---------------------------------------------------------------- agreements


def test_list_agreements(con):
    agreements = list_agreements(con)
    assert sorted(a["id"] for a in agreements) == sorted(PER_AGREEMENT)
    by_id = {a["id"]: a for a in agreements}
    for a in agreements:
        assert a["obligation_count"] == PER_AGREEMENT[a["id"]]
        assert isinstance(a["metadata"], dict) and a["metadata"]["source_url"].startswith(
            "https://"
        )
        for binding in a["parties"] + a["sites"]:
            assert_clause_is_slice(binding["clause"])
    for doc_id in (*CC_CHAIN, CARBONITE):
        [site] = by_id[doc_id]["sites"]
        assert site["label"] == "agreement site"
        assert site["name"] in site["clause"]["span_text"]
        assert site["location"] in site["clause"]["span_text"]
    assert {s["name"] for s in by_id[CARBONITE]["sites"]} == {"2121 South Price Road"}
    for doc_id in ("mawson-2025-ex101", "terawulf-2025-ex10-1", APPLIED):
        assert by_id[doc_id]["sites"] == []
    assert {(p["name"], p["role"]) for p in by_id[BASE]["parties"]} == {
        ("Digital 55 Middlesex, LLC", "landlord"),
        ("Constant Contact, Inc.", "tenant"),
    }
    assert by_id[A3]["base_agreement_id"] == BASE


# ---------------------------------------------------------------- obligations


def test_default_page(con):
    page = get_obligations(con)
    assert (page["total"], page["returned"], page["offset"], page["truncated"]) == (
        VISIBLE,
        50,
        0,
        True,
    )
    assert page["unresolved_party_count"] == UNRESOLVED_PARTY


def test_every_obligation_has_grounded_clauses_and_cited_bindings(con):
    rows = all_obligations(con)
    assert len(rows) == VISIBLE
    for o in rows:
        assert o["clauses"], o["id"]
        for c in o["clauses"]:
            assert_clause_is_slice(c)
        for side in ("owed_by", "owed_to"):
            if o[side] is not None:
                assert_clause_is_slice(o[side]["clause"])
        for s in o["agreement_sites"]:
            assert_clause_is_slice(s["clause"])


def test_pages_are_deterministic_and_complete(con):
    rows = all_obligations(con)
    keys = [(o["agreement_id"], o["id"]) for o in rows]  # no effective_due in this corpus
    assert keys == sorted(keys)
    assert len({o["id"] for o in rows}) == VISIBLE
    again = all_obligations(con)
    assert [o["id"] for o in again] == [o["id"] for o in rows]


def test_agreement_filter_carbonite(con):
    page = get_obligations(con, agreement=CARBONITE, limit=MAX_LIMIT)
    assert (page["total"], page["returned"], page["truncated"]) == (202, 202, False)
    assert {o["agreement_id"] for o in page["obligations"]} == {CARBONITE}


def test_offset_page(con):
    page = get_obligations(con, agreement=CARBONITE, limit=50, offset=200)
    assert (page["total"], page["returned"], page["offset"], page["truncated"]) == (
        202,
        2,
        200,
        False,
    )


@pytest.mark.parametrize("limit,offset", [(0, 0), (MAX_LIMIT + 1, 0), (10, -1)])
def test_bad_paging_raises(con, limit, offset):
    with pytest.raises(ValueError):
        get_obligations(con, limit=limit, offset=offset)


def test_filters_apply_before_limit(con):
    expected = con.execute(
        "SELECT count(*) FROM visible_obligation WHERE type='payment' AND status='redacted'"
    ).fetchone()[0]
    page = get_obligations(con, type="payment", status="redacted", limit=5)
    assert page["total"] == expected and expected > 5
    assert page["returned"] == 5
    assert all(o["type"] == "payment" and o["status"] == "redacted" for o in page["obligations"])
    assert get_obligations(con, type="payment")["total"] == PAYMENTS
    assert get_obligations(con, status="redacted")["total"] == REDACTED


def test_lifecycle_filter(con):
    assert get_obligations(con, lifecycle="pending")["total"] == VISIBLE
    assert get_obligations(con, lifecycle="scheduled")["total"] == 0
    assert get_obligations(con, lifecycle="superseded", include_superseded=True)["total"] == 0


def test_party_role_word_means_payee_role(con):
    rows = all_obligations(con, party="landlord")
    assert len(rows) == LANDLORD_PAYEE
    assert all(o["owed_to"] is not None and o["owed_to"]["role"] == "landlord" for o in rows)
    assert len(all_obligations(con, party="tenant")) == TENANT_PAYEE


def test_party_name_matches_case_insensitively(con):
    expected = con.execute(
        "SELECT count(*) FROM visible_obligation o JOIN visible_party_binding b"
        " ON b.agreement_id = o.agreement_id AND b.party_id = o.owed_to"
        " WHERE lower(b.name) LIKE '%digital 55 middlesex%'"
    ).fetchone()[0]
    assert expected > 0
    rows = all_obligations(con, party="DIGITAL 55 middlesex")
    assert len(rows) == expected
    assert all("digital 55 middlesex" in o["owed_to"]["name"].lower() for o in rows)


def test_unresolved_party_count_uses_non_party_filters(con):
    assert get_obligations(con, party="landlord")["unresolved_party_count"] == UNRESOLVED_PARTY
    carb = get_obligations(con, agreement=CARBONITE, party="landlord")
    assert carb["total"] == 0
    assert carb["unresolved_party_count"] == 202


def test_site_filter(con):
    rows = all_obligations(con, site="middlesex")
    assert {o["agreement_id"] for o in rows} == set(CC_CHAIN)
    assert len(rows) == sum(PER_AGREEMENT[d] for d in CC_CHAIN)
    for o in rows:
        assert [s["label"] for s in o["agreement_sites"]] == ["agreement site"]
    assert len(all_obligations(con, site="Chandler")) == PER_AGREEMENT[CARBONITE]
    assert all_obligations(con, site="Phoenix") == []


def test_redacted_rows_keep_verified_fields_and_quotes(con):
    by_id = {o["id"]: o for o in all_obligations(con, status="redacted")}
    for oid in REDACTED_ROWS:
        o = by_id[oid]
        assert o["marker"] == MARKERS["redacted"] == "[REDACTED]"
        assert (o["amount"], o["due_date"], o["anchor_event"], o["offset_days"]) == (
            None,
            None,
            None,
            None,
        )
        [quote] = con.execute(
            "SELECT span_text FROM visible_obligation_clause WHERE obligation_id=?", (oid,)
        ).fetchall()
        assert o["clauses"][0]["span_text"] == quote[0]
    assert "[***]" in by_id[204]["clauses"][0]["span_text"]
    for oid in (490, 504):
        o = by_id[oid]
        assert (o["owed_by"]["name"], o["owed_by"]["role"]) == ("COREWEAVE, INC.", "guarantor")
        assert (o["owed_to"]["name"], o["owed_to"]["role"]) == ("APLD ELN-02 LLC", "landlord")
    for oid in (204, 381):
        assert by_id[oid]["owed_by"] is None and by_id[oid]["owed_to"] is None


def test_unredacted_rows_have_no_marker(con):
    page = get_obligations(con, status="active", limit=20)
    assert all(o["marker"] is None for o in page["obligations"])


# ---------------------------------------------------------------- deadlines


def test_upcoming_deadlines_is_honest_about_pending(con):
    d = upcoming_deadlines(con, as_of="2018-04-01", days=90)
    assert (d["as_of"], d["days"], d["window_end"]) == ("2018-04-01", 90, "2018-06-30")
    assert d["scheduled"] == []
    assert d["pending_total"] == VISIBLE
    assert len(d["pending"]) == 50 and d["truncated"] is True and d["offset"] == 0
    assert d["note"] == PENDING_NOTE
    assert d["unresolved_party_count"] == UNRESOLVED_PARTY


def test_upcoming_deadlines_party_and_paging(con):
    d = upcoming_deadlines(con, as_of="2018-04-01", party="landlord", limit=MAX_LIMIT)
    assert d["pending_total"] == LANDLORD_PAYEE and len(d["pending"]) == LANDLORD_PAYEE
    assert d["truncated"] is False


def test_upcoming_deadlines_default_as_of(con):
    d = upcoming_deadlines(con)
    assert len(d["as_of"]) == 10 and d["as_of"][4] == "-"


# ---------------------------------------------------------------- revocation


def test_revoked_party_ref_unbinds_payee_only(con):
    con.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (REF_LANDLORD,))
    [o] = [x for x in all_obligations(con, agreement=BASE) if x["id"] == OBL_34]
    assert o["owed_to"] is None
    assert o["owed_by"]["role"] == "tenant"
    assert [c["span_text"] for c in o["clauses"]] == [
        con.execute("SELECT span_text FROM clause_ref WHERE id=?", (OBL_34_REF,)).fetchone()[0]
    ]
    assert len(all_obligations(con, party="landlord")) == LANDLORD_PAYEE - 92


def test_mixed_citations_return_only_grounded(con):
    con.execute(
        "INSERT INTO clause_ref(obligation_id,agreement_id,section,page,char_start,char_end,"
        "span_text,grounded) VALUES(?,?,'1',1,0,5,'Xyzzy',0)",
        (OBL_34, BASE),
    )
    [o] = [x for x in all_obligations(con, agreement=BASE) if x["id"] == OBL_34]
    assert [c["span_text"] for c in o["clauses"]] == [
        con.execute("SELECT span_text FROM clause_ref WHERE id=?", (OBL_34_REF,)).fetchone()[0]
    ]


def test_revoked_site_ref_removes_site(con):
    con.execute("UPDATE clause_ref SET grounded=0 WHERE id=?", (REF_SITE_CARBONITE,))
    by_id = {a["id"]: a for a in list_agreements(con)}
    assert by_id[CARBONITE]["sites"] == []
    assert all_obligations(con, site="Chandler") == []


def test_ungrounded_obligation_is_invisible(con):
    con.execute("UPDATE clause_ref SET grounded=0 WHERE obligation_id=?", (OBL_34,))
    assert OBL_34 not in {o["id"] for o in all_obligations(con)}
    assert get_obligations(con)["total"] == VISIBLE - 1


# ---------------------------------------------------------------- read transaction


def test_functions_leave_no_open_transaction(con):
    list_agreements(con)
    assert not con.in_transaction
    get_obligations(con, party="landlord")
    assert not con.in_transaction
    upcoming_deadlines(con, as_of="2018-04-01")
    assert not con.in_transaction
    change_order(con, A3)
    assert not con.in_transaction


def test_query_writes_nothing(ws, con):
    before = con.execute("SELECT total_changes()").fetchone()[0]
    list_agreements(con)
    get_obligations(con)
    upcoming_deadlines(con, as_of="2018-04-01")
    change_order(con, A3)
    assert con.execute("SELECT total_changes()").fetchone()[0] == before


# ---------------------------------------------------------------- change orders


def _pinned(ws, doc_id):
    docs = yaml.safe_load((ws / "data" / "sources.yaml").read_text(encoding="utf-8"))["documents"]
    return next(d for d in docs if d["id"] == doc_id)


def assert_ok(result, doc_id):
    assert result["status"] == "ok", result
    assert result["stored_report"] is True and result["analysis_performed"] is False
    assert result["change_order_id"] == doc_id
    assert result["ungated"]["change_order_id"] == doc_id


def test_change_order_by_id(con):
    r = change_order(con, A3)
    assert_ok(r, A3)
    assert r["status"] in CHANGE_STATUSES
    [shift] = r["ungated"]["shifted_dates"]
    assert (shift["old_value"], shift["new_value"], shift["delta"]) == (
        "2018-06-30",
        "2020-06-30",
        "731",
    )
    assert len(r["ungated"]["price_changes"]) == 3
    assert r["gated"] is not None and r["gated"]["mode"] == "gated"
    assert r["pair_id"] == r["ungated"]["pair_id"]
    assert (
        r["source_sha256"]
        == con.execute("SELECT sha256 FROM source WHERE id=?", (A3,)).fetchone()[0]
    )
    assert [m["agreement_id"] for m in r["chain"]] == [BASE, A1, A3]
    assert r["gate_summary"]


def test_change_order_1a(con):
    r = change_order(con, A1)
    assert_ok(r, A1)
    assert len(r["ungated"]["price_changes"]) == 5


def test_change_order_by_local_path_and_filename(ws, con):
    local = _pinned(ws, A3)["local_path"]
    assert_ok(change_order(con, local), A3)
    assert_ok(change_order(con, local.rsplit("/", 1)[-1]), A3)


def test_change_order_arbitrary_file_with_pinned_bytes(ws, con, tmp_path):
    other = tmp_path / "elsewhere" / "renamed.htm"
    other.parent.mkdir()
    other.write_bytes(b"SYNTHETIC stand-in bytes for the pinned 3A filing")
    sha = hashlib.sha256(other.read_bytes()).hexdigest()
    # Re-pin 3A to these bytes in both the workspace sources.yaml and the DB copy.
    sources = ws / "data" / "sources.yaml"
    sources.write_text(
        sources.read_text(encoding="utf-8").replace(_pinned(ws, A3)["sha256"], sha),
        encoding="utf-8",
    )
    con.execute("UPDATE source SET sha256=? WHERE id=?", (sha, A3))
    assert_ok(change_order(con, str(other)), A3)


def test_change_order_rejects_lookalike_paths(con, tmp_path):
    fake = tmp_path / "endurance-2017-ex106.htm"
    fake.write_bytes(b"SYNTHETIC: not the pinned filing")
    for value in (str(fake), str(tmp_path / "missing" / "endurance-2017-ex106.htm"), "nope"):
        r = change_order(con, value)
        assert r["status"] == "unknown_change_order", value
        assert r["ungated"] is None and r["gated"] is None
        assert "make" in r["message"]


def test_non_amendment_is_not_a_change_order(con):
    assert change_order(con, CARBONITE)["status"] == "unknown_change_order"


def test_stale_change_run(con):
    con.execute("UPDATE extraction_run SET textdoc_sha256=? WHERE source_id=?", ("0" * 64, BASE))
    r = change_order(con, A3)
    assert r["status"] == "stale_change_run"
    assert r["ungated"] is None and r["gated"] is None
    assert "make change" in r["message"]


def test_missing_change_run(con):
    runs = [r[0] for r in con.execute("SELECT id FROM change_run WHERE change_order_id=?", (A3,))]
    q = ",".join("?" * len(runs))
    for table in ("supersedes", "gate_decision", "change_finding", "change_run_chain"):
        con.execute(f"DELETE FROM {table} WHERE change_run_id IN ({q})", runs)
    con.execute(f"DELETE FROM change_run WHERE id IN ({q})", runs)
    r = change_order(con, A3)
    assert r["status"] == "missing_change_run"
    assert r["ungated"] is None
    assert "make change" in r["message"]


def test_gated_stale_ungated_fresh(con):
    gated = con.execute(
        "SELECT id FROM change_run WHERE change_order_id=? AND mode='gated'", (A3,)
    ).fetchone()[0]
    con.execute(
        "UPDATE change_run_chain SET extraction_run_id='stale'"
        " WHERE change_run_id=? AND agreement_id=?",
        (gated, BASE),
    )
    r = change_order(con, A3)
    assert_ok(r, A3)
    assert r["gated"] is None


def test_missing_textdoc(tmp_path, monkeypatch):
    ws = make_workspace(tmp_path, monkeypatch, drop_text=(A3,))
    con = open_db(ws / "data" / "graph.db")
    r = change_order(con, A3)
    assert r["status"] == "missing_textdoc"
    assert r["ungated"] is None
    assert "make ingest" in r["message"]


def test_module_exposes_contract():
    assert set(CHANGE_STATUSES) >= {
        "ok",
        "unknown_change_order",
        "missing_change_run",
        "stale_change_run",
        "missing_textdoc",
    }
    assert callable(query.get_obligations)
