"""Wave 5 Task 42: og.query timing surfaces (plan rev 2 W5-1/W5-3/W5-6/W5-11, rev 2.1).

On a copy of the real v5 graph with the timing set from tests/timing_fixture.py:
- every ObligationOut carries `timing` (TimingOut) and `deadline` (DeadlineOut | None);
- a scheduled row's deadline keeps its relation: strict `lt` bounds (62, 65, 236) never
  become due-on dates and leave `effective_due` null; inclusive `lte` bounds (514, 519)
  also set `effective_due`;
- upcoming_deadlines selects scheduled rows by deadline date in the window whatever the
  relation, lists contingent rows as a paged subset of pending, and reports totals for
  each pending kind; nothing is counted twice;
- revoking a citation removes the timing everywhere.
"""

import sqlite3

import pytest
from timing_fixture import (
    A3,
    BASE,
    CONTINGENT,
    SCHEDULED,
    UNRESOLVED,
    VISIBLE,
    obligation_quote,
    timed_v5,
)

from og import query


@pytest.fixture
def db(tmp_path):
    path, ids = timed_v5(tmp_path / "graph.db")
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    yield con, ids
    con.close()


def all_rows(con, **kw):
    """Every matching obligation, across pages (525 visible rows exceed one page)."""
    rows, offset = [], 0
    while True:
        page = query.get_obligations(con, limit=500, offset=offset, **kw)
        rows += page["obligations"]
        offset += page["returned"]
        if not page["truncated"]:
            return {o["id"]: o for o in rows}


def by_id(con, ids, **kw):
    found = all_rows(con, **kw)
    return {i: found[i] for i in ids if i in found}


def all_pending_ids(con, **kw):
    ids, offset = set(), 0
    while True:
        out = query.upcoming_deadlines(con, limit=500, offset=offset, **kw)
        ids |= {o["id"] for o in out["pending"]}
        offset += len(out["pending"])
        if not out["truncated"]:
            return ids


def inside_own_quote(con, ob):
    trig = ob["timing"]["trigger"]
    return any(
        c["agreement_id"] == trig["agreement_id"]
        and c["char_start"] <= trig["char_start"]
        and trig["char_end"] <= c["char_end"]
        for c in ob["clauses"]
    )


TIMING_KEYS = {
    "kind",
    "trigger_kind",
    "trigger",
    "relation",
    "offset_days",
    "offset_unit",
    "anchor",
    "reason",
}


def test_every_obligation_carries_timing_and_deadline(db):
    con, _ = db
    rows = all_rows(con)
    assert len(rows) == VISIBLE
    for ob in rows.values():
        assert set(ob["timing"]) == TIMING_KEYS
        assert "deadline" in ob
        assert (ob["deadline"] is not None) == (ob["timing"]["kind"] == "scheduled")
        assert (ob["timing"]["reason"] is not None) == (ob["timing"]["kind"] == "unresolved")


def test_scheduled_rows_keep_their_relation(db):
    con, _ = db
    rows = by_id(con, SCHEDULED)
    assert set(rows) == set(SCHEDULED)
    for oid, (relation, bound) in SCHEDULED.items():
        ob = rows[oid]
        assert ob["lifecycle"] == "scheduled"
        t = ob["timing"]
        assert t["kind"] == "scheduled" and t["relation"] == relation
        assert t["anchor"]["date"] == bound
        assert ob["deadline"]["relation"] == relation
        assert ob["deadline"]["date"] == bound
        assert ob["deadline"]["clause"]["span_text"] == t["anchor"]["clause"]["span_text"]
        assert inside_own_quote(con, ob)
        if relation == "lt":
            assert ob["effective_due"] is None, oid
        else:
            assert ob["effective_due"] == bound, oid


def test_anchor_carries_its_own_declaration_clause(db):
    con, _ = db
    ob = by_id(con, [519])[519]
    anchor = ob["timing"]["anchor"]
    assert anchor["name"] == "3A Suite 409 Amended Surrender Date"
    assert anchor["clause"]["agreement_id"] == A3
    assert "expiring June 30, 2020" in anchor["clause"]["span_text"]
    base = by_id(con, [62])[62]["timing"]["anchor"]
    assert base["clause"]["agreement_id"] == BASE
    assert "Commencement Date" in base["clause"]["span_text"]
    assert "January" in base["clause"]["span_text"]


def test_contingent_rows_quote_their_trigger(db):
    con, _ = db
    rows = by_id(con, CONTINGENT)
    for oid in CONTINGENT:
        ob = rows[oid]
        t = ob["timing"]
        assert ob["lifecycle"] == "pending"
        assert t["kind"] == "contingent" and t["trigger_kind"] == "invoice"
        assert t["relation"] == "lte" and t["offset_unit"] == "calendar"
        assert t["anchor"] is None and t["reason"] is None and ob["deadline"] is None
        assert "invoice" in t["trigger"]["span_text"]
        assert inside_own_quote(con, ob)
    assert rows[14]["timing"]["offset_days"] == 15
    assert rows[57]["timing"]["offset_days"] == 30


def test_unresolved_rows_give_a_reason_and_no_date(db):
    con, _ = db
    rows = by_id(con, UNRESOLVED)
    for oid, reason in UNRESOLVED.items():
        ob = rows[oid]
        assert ob["lifecycle"] == "pending"
        assert ob["timing"]["kind"] == "unresolved"
        assert ob["timing"]["reason"] == reason
        assert ob["deadline"] is None and ob["effective_due"] is None
        assert inside_own_quote(con, ob)
    assert rows[159]["timing"]["offset_unit"] == "business"
    assert rows[490]["timing"]["offset_days"] is None


def test_untimed_rows_have_null_timing(db):
    con, _ = db
    ob = by_id(con, [34])[34]
    assert ob["timing"] == {k: (None if k != "kind" else "untimed") for k in TIMING_KEYS}
    assert ob["deadline"] is None


def test_lifecycle_filter_scheduled_returns_exactly_the_five(db):
    con, _ = db
    page = query.get_obligations(con, lifecycle="scheduled", limit=50)
    assert page["total"] == 5
    assert {o["id"] for o in page["obligations"]} == set(SCHEDULED)


def test_window_selects_strict_bounds_by_deadline_date(db):
    con, _ = db
    out = query.upcoming_deadlines(con, as_of="2010-12-15", days=90, limit=500)
    assert [o["id"] for o in out["scheduled"]] == [62, 65]
    assert all(o["deadline"]["relation"] == "lt" for o in out["scheduled"])
    assert out["note"] == query.PENDING_NOTE


def test_window_with_inclusive_bound(db):
    con, _ = db
    out = query.upcoming_deadlines(con, as_of="2020-06-01", days=60, limit=500)
    assert [o["id"] for o in out["scheduled"]] == [519]


def test_pending_kinds_are_consistent_and_never_double_counted(db):
    con, _ = db
    out = query.upcoming_deadlines(con, as_of="2010-12-15", days=90, limit=500)
    pending_ids = all_pending_ids(con, as_of="2010-12-15", days=90)
    scheduled_ids = {o["id"] for o in out["scheduled"]}
    assert not pending_ids & scheduled_ids
    assert not pending_ids & set(SCHEDULED)
    assert out["pending_total"] == VISIBLE - len(SCHEDULED)
    assert out["contingent_total"] == len(CONTINGENT)
    assert out["unresolved_total"] == len(UNRESOLVED)
    assert out["untimed_total"] == (
        out["pending_total"] - out["contingent_total"] - out["unresolved_total"]
    )
    contingent_ids = {o["id"] for o in out["contingent"]}
    assert contingent_ids == CONTINGENT
    assert contingent_ids <= pending_ids
    assert all(o["timing"]["kind"] == "contingent" for o in out["contingent"])


def test_contingent_list_is_paged(db):
    con, _ = db
    first = query.upcoming_deadlines(con, as_of="2010-12-15", days=90, limit=1)
    assert len(first["contingent"]) == 1
    assert first["contingent_total"] == len(CONTINGENT)


def _revoke(con, ref_id):
    con.execute("UPDATE clause_ref SET grounded = 0 WHERE id = ?", (ref_id,))


def test_revoked_trigger_removes_timing_everywhere(db):
    con, ids = db
    _revoke(con, ids["trigger_refs"][14])
    ob = by_id(con, [14])[14]
    assert ob["timing"]["kind"] == "untimed" and ob["timing"]["trigger"] is None
    assert ob["deadline"] is None
    out = query.upcoming_deadlines(con, as_of="2010-12-15", days=90, limit=500)
    assert out["contingent_total"] == len(CONTINGENT) - 1
    assert 14 not in {o["id"] for o in out["contingent"]}


def test_revoked_declaration_unschedules_both_dependents(db):
    con, ids = db
    _revoke(con, ids["decl_refs"]["base_cd"])
    rows = by_id(con, [62, 65])
    for oid in (62, 65):
        assert rows[oid]["lifecycle"] == "pending"
        assert rows[oid]["timing"]["kind"] == "untimed"
        assert rows[oid]["deadline"] is None
    out = query.upcoming_deadlines(con, as_of="2010-12-15", days=90, limit=500)
    assert out["scheduled"] == []
    page = query.get_obligations(con, lifecycle="scheduled", limit=50)
    assert page["total"] == 3


def test_trigger_from_another_obligation_is_rejected(db):
    """Rev 2 W5-3: 62 given 65's quote span (same agreement, grounded) is not contained
    in 62's own citation, so 62's timing is invisible."""
    con, ids = db
    agreement_id, start, end, text = obligation_quote(con, 65)
    ref = con.execute(
        "INSERT INTO clause_ref(obligation_id, agreement_id, section, page, char_start,"
        " char_end, span_text, grounded) VALUES(NULL, ?, NULL, NULL, ?, ?, ?, 1)",
        (agreement_id, start, end, text),
    ).lastrowid
    con.execute(
        "UPDATE obligation_timing SET trigger_clause_ref_id = ? WHERE obligation_id = 62",
        (ref,),
    )
    ob = by_id(con, [62])[62]
    assert ob["timing"]["kind"] == "untimed" and ob["deadline"] is None
    assert by_id(con, [65])[65]["timing"]["kind"] == "scheduled"


def test_query_reads_timing_only_through_the_projection():
    assert "visible_obligation_timing" in query.READ_ALLOWLIST
    assert "obligation_timing" not in query.READ_ALLOWLIST
    assert "grounded_obligation" not in query.READ_ALLOWLIST


def test_pending_note_explains_the_pending_kinds():
    note = query.PENDING_NOTE.lower()
    for word in ("contingent", "unresolved", "no deadline"):
        assert word in note, word
