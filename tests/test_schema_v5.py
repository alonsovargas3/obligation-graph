"""Schema v5 (wave 5): obligation timing and the acyclic timing views.

Plan rev 2 W5-1/W5-3/W5-7 and rev 2.1 R2-1, mirroring the executed evidence in
docs/reviews/2026-10-02-astra-wave5-review.md round 3. Every test runs on a copy of
tests/fixtures/graph/real_v5.db (the real graph, no timing rows) and inserts its own
timing rows by SQL: defined-date events cite the real declaration slices, and each
trigger ref is an exact slice of the obligation's own grounded extraction quote.

The five scheduled rows are the real wave-5 deadlines:
  62, 65   "prior to the Commencement Date"         lt  2011-01-01 (CC base BLI pair)
  236      "prior to the Target Commencement Date"  lt  2014-04-01 (Carbonite BLI pair)
  514      "on or before the 1A Expansion Date"      lte 2012-06-01 (1A p0027 declaration)
  519      "no later than the 3A Suite 409 ..."      lte 2020-06-30 (3A p0011 declaration)
"""

import sqlite3

import pytest
from graph_fixture import A1, A3, BASE, CARBONITE, VISIBLE, copy_db, open_db, textdoc

# Real declaration slices (canonical TextDoc offsets; Astra round 2 table).
DECLARATIONS = {
    "cc_commencement": (BASE, "Commencement Date", "2011-01-01", 44806, 44844),
    "carbonite_target": (CARBONITE, "Target Commencement Date", "2014-04-01", 48757, 48801),
    "a1_expansion": (A1, "1A Expansion Date", "2012-06-01", 4057, 4101),
    "a3_surrender": (A3, "3A Suite 409 Amended Surrender Date", "2020-06-30", 2775, 2841),
}
# obligation id -> (extraction ref id, trigger phrase inside its quote, anchor, relation)
SCHEDULED = {
    62: (120, "prior to the Commencement Date", "cc_commencement", "lt"),
    65: (123, "prior to the Commencement Date", "cc_commencement", "lt"),
    236: (331, "prior to the Target Commencement Date", "carbonite_target", "lt"),
    514: (728, "on or before the 1A Expansion Date", "a1_expansion", "lte"),
    519: (745, "no later than the 3A Suite 409 Amended Surrender Date", "a3_surrender", "lte"),
}
CARBONITE_EVENT_5 = 5  # real "Early Access Date", 2014-02-01, grounded
OBL_89, OBL_89_REF = 89, 147  # "... defend upon demand ..."


@pytest.fixture
def con(tmp_path):
    con = open_db(copy_db(tmp_path))
    yield con
    con.close()


def ref(con, agreement, start, end, grounded=1):
    """A ClauseRef owned by no obligation, sliced from the real TextDoc."""
    text = textdoc(agreement).text
    return con.execute(
        "INSERT INTO clause_ref(obligation_id, agreement_id, section, page, char_start,"
        " char_end, span_text, grounded) VALUES(NULL, ?, NULL, NULL, ?, ?, ?, ?)",
        (agreement, start, end, text[start:end], grounded),
    ).lastrowid


def inner_ref(con, owner_ref, phrase):
    """A ref for `phrase` located inside the owner citation's own span."""
    agreement, start, end, span = con.execute(
        "SELECT agreement_id, char_start, char_end, span_text FROM clause_ref WHERE id = ?",
        (owner_ref,),
    ).fetchone()
    i = span.index(phrase)
    assert textdoc(agreement).text[start + i : start + i + len(phrase)] == phrase
    return ref(con, agreement, start + i, start + i + len(phrase))


def seed(con):
    """Defined-date events, trigger refs and the five scheduled timing rows."""
    events, decl_refs = {}, {}
    for key, (agreement, name, date, start, end) in DECLARATIONS.items():
        decl_refs[key] = ref(con, agreement, start, end)
        events[key] = con.execute(
            "INSERT INTO event(agreement_id, name, date, clause_ref_id) VALUES(?, ?, ?, ?)",
            (agreement, name, date, decl_refs[key]),
        ).lastrowid
    triggers = {}
    for oid, (owner, phrase, anchor, relation) in SCHEDULED.items():
        triggers[oid] = inner_ref(con, owner, phrase)
        con.execute(
            "INSERT INTO obligation_timing(obligation_id, kind, trigger_kind,"
            " trigger_clause_ref_id, relation, offset_days, offset_unit, anchor_event_id,"
            " bound_date, reason) VALUES(?, 'scheduled', 'defined_event', ?, ?, 0, NULL, ?, ?,"
            " NULL)",
            (oid, triggers[oid], relation, events[anchor], DECLARATIONS[anchor][2]),
        )
    return {"events": events, "decl_refs": decl_refs, "triggers": triggers}


def timing(con, oid):
    return con.execute(
        "SELECT kind, relation, bound_date, anchor_event_id, trigger_clause_ref_id,"
        " anchor_agreement_id FROM visible_obligation_timing WHERE obligation_id = ?",
        (oid,),
    ).fetchone()


def lifecycle(con, oid):
    return con.execute(
        "SELECT lifecycle, effective_due FROM visible_obligation WHERE id = ?", (oid,)
    ).fetchone()


# --- acyclic views ---------------------------------------------------------------------


def test_views_exist_in_acyclic_order(con):
    views = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'view'")]
    assert {"grounded_obligation", "visible_obligation_timing", "visible_obligation"} <= set(views)
    timing_sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'visible_obligation_timing'"
    ).fetchone()[0]
    assert "visible_obligation " not in timing_sql and "visible_obligation\n" not in timing_sql


def test_both_views_query_on_the_real_graph(con):
    assert con.execute("SELECT count(*) FROM visible_obligation").fetchone()[0] == VISIBLE
    assert con.execute("SELECT count(*) FROM visible_obligation_timing").fetchone()[0] == 0
    seed(con)
    assert con.execute("SELECT count(*) FROM visible_obligation").fetchone()[0] == VISIBLE
    assert con.execute("SELECT count(*) FROM visible_obligation_timing").fetchone()[0] == 5


def test_no_timing_rows_leaves_every_obligation_pending(con):
    rows = con.execute("SELECT DISTINCT lifecycle FROM visible_obligation").fetchall()
    assert rows == [("pending",)]


# --- the five scheduled rows -------------------------------------------------------------


def test_five_scheduled_rows_relations_and_bounds(con):
    seed(con)
    for oid, (_owner, _phrase, anchor, relation) in SCHEDULED.items():
        kind, rel, bound, *_ = timing(con, oid)
        assert (kind, rel, bound) == ("scheduled", relation, DECLARATIONS[anchor][2]), oid
        assert lifecycle(con, oid)[0] == "scheduled", oid


def test_effective_due_only_for_inclusive_bounds(con):
    seed(con)
    assert lifecycle(con, 62) == ("scheduled", None)
    assert lifecycle(con, 65) == ("scheduled", None)
    assert lifecycle(con, 236) == ("scheduled", None)
    assert lifecycle(con, 514) == ("scheduled", "2012-06-01")
    assert lifecycle(con, 519) == ("scheduled", "2020-06-30")


def test_ninety_day_window_selects_strict_bounds_once(con):
    seed(con)
    rows = con.execute(
        "SELECT t.obligation_id, t.relation, t.bound_date FROM visible_obligation_timing t"
        " JOIN visible_obligation o ON o.id = t.obligation_id"
        " WHERE t.kind = 'scheduled' AND t.bound_date BETWEEN ? AND date(?, '+90 days')"
        " ORDER BY t.obligation_id",
        ("2010-12-15", "2010-12-15"),
    ).fetchall()
    assert rows == [(62, "lt", "2011-01-01"), (65, "lt", "2011-01-01")]


def test_trigger_and_anchor_citations_are_exposed(con):
    s = seed(con)
    row = con.execute(
        "SELECT trigger_span_text, anchor_name, anchor_date, anchor_span_text, anchor_agreement_id"
        " FROM visible_obligation_timing WHERE obligation_id = 514"
    ).fetchone()
    assert row[0] == "on or before the 1A Expansion Date"
    assert row[1:3] == ("1A Expansion Date", "2012-06-01")
    assert row[3] == "As of June 1, 2012 (the “1A Expansion Date”)"
    assert row[4] == A1
    assert s["triggers"][514] == timing(con, 514)[4]


def test_contingent_and_untimed_rows_stay_pending(con):
    trig = inner_ref(con, OBL_89_REF, "upon demand")
    con.execute(
        "INSERT INTO obligation_timing(obligation_id, kind, trigger_kind, trigger_clause_ref_id,"
        " relation) VALUES(?, 'contingent', 'demand', ?, 'eq')",
        (OBL_89, trig),
    )
    con.execute("INSERT INTO obligation_timing(obligation_id, kind) VALUES(34, 'untimed')")
    assert timing(con, OBL_89)[0] == "contingent"
    assert timing(con, 34)[0] == "untimed"
    assert lifecycle(con, OBL_89) == ("pending", None)
    assert lifecycle(con, 34) == ("pending", None)


# --- negatives, each in isolation ----------------------------------------------------------


def test_revoked_trigger_ref_removes_62_only(con):
    s = seed(con)
    con.execute("UPDATE clause_ref SET grounded = 0 WHERE id = ?", (s["triggers"][62],))
    assert timing(con, 62) is None
    assert lifecycle(con, 62) == ("pending", None)
    assert timing(con, 65)[0] == "scheduled"
    assert con.execute("SELECT count(*) FROM visible_obligation_timing").fetchone()[0] == 4


def test_revoked_shared_declaration_removes_62_and_65(con):
    s = seed(con)
    con.execute(
        "UPDATE clause_ref SET grounded = 0 WHERE id = ?", (s["decl_refs"]["cc_commencement"],)
    )
    assert timing(con, 62) is None and timing(con, 65) is None
    assert lifecycle(con, 62)[0] == lifecycle(con, 65)[0] == "pending"
    assert con.execute("SELECT count(*) FROM visible_obligation_timing").fetchone()[0] == 3


def test_revoked_extraction_ref_removes_62_from_both_views(con):
    seed(con)
    con.execute("UPDATE clause_ref SET grounded = 0 WHERE id = 120")
    assert timing(con, 62) is None
    assert con.execute("SELECT count(*) FROM visible_obligation WHERE id = 62").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM visible_obligation").fetchone()[0] == VISIBLE - 1


def test_trigger_from_another_obligations_quote_is_rejected(con):
    """Ref 123 is grounded and in the same agreement, but it is 65's quote, not 62's."""
    seed(con)
    con.execute("UPDATE obligation_timing SET trigger_clause_ref_id = 123 WHERE obligation_id = 62")
    assert timing(con, 62) is None
    assert lifecycle(con, 62) == ("pending", None)
    assert timing(con, 65)[0] == "scheduled"


def test_anchor_from_a_foreign_agreement_is_rejected(con):
    """Carbonite event 5 is grounded and dated; its bound is even consistent. Scope fails."""
    seed(con)
    con.execute(
        "UPDATE obligation_timing SET anchor_event_id = ?, bound_date = '2014-02-01'"
        " WHERE obligation_id = 62",
        (CARBONITE_EVENT_5,),
    )
    assert timing(con, 62) is None
    assert lifecycle(con, 62) == ("pending", None)


def test_stored_bound_must_equal_recomputed_bound(con):
    seed(con)
    con.execute("UPDATE obligation_timing SET bound_date = '2011-01-02' WHERE obligation_id = 62")
    assert timing(con, 62) is None
    assert lifecycle(con, 62) == ("pending", None)


def test_offset_is_part_of_the_recomputed_bound(con):
    s = seed(con)
    con.execute(
        "UPDATE obligation_timing SET offset_days = 30, bound_date = '2012-07-01'"
        " WHERE obligation_id = 514"
    )
    assert timing(con, 514)[2] == "2012-07-01"
    assert lifecycle(con, 514) == ("scheduled", "2012-07-01")
    assert s["events"]["a1_expansion"] == timing(con, 514)[3]


def test_base_agreement_anchor_is_visible_for_an_amendment_obligation(con):
    """A 1A obligation may be bound to the base lease's cited Commencement Date."""
    s = seed(con)
    oid, owner = (
        518,
        con.execute(
            "SELECT id FROM clause_ref WHERE obligation_id = 518 AND grounded = 1"
        ).fetchone()[0],
    )
    con.execute(
        "INSERT INTO obligation_timing(obligation_id, kind, trigger_kind, trigger_clause_ref_id,"
        " relation, offset_days, anchor_event_id, bound_date) VALUES(?, 'scheduled',"
        " 'defined_event', NULL, 'lt', 0, ?, '2011-01-01')",
        (oid, s["events"]["cc_commencement"]),
    )
    assert owner
    row = timing(con, oid)
    assert row[0] == "scheduled" and row[5] == BASE
    assert lifecycle(con, oid)[0] == "scheduled"


def test_anchor_from_the_change_order_is_not_visible_to_the_base(con):
    """Scope is own agreement or recorded base, never a later amendment."""
    s = seed(con)
    con.execute(
        "UPDATE obligation_timing SET anchor_event_id = ?, bound_date = '2012-06-01'"
        " WHERE obligation_id = 62",
        (s["events"]["a1_expansion"],),
    )
    assert timing(con, 62) is None


# --- CHECK constraints -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        # scheduled without a bound
        "INSERT INTO obligation_timing(obligation_id, kind, relation, anchor_event_id)"
        " VALUES(62, 'scheduled', 'lt', 5)",
        # scheduled without an anchor
        "INSERT INTO obligation_timing(obligation_id, kind, relation, bound_date)"
        " VALUES(62, 'scheduled', 'lt', '2011-01-01')",
        # scheduled with a business-day unit
        "INSERT INTO obligation_timing(obligation_id, kind, relation, offset_days, offset_unit,"
        " anchor_event_id, bound_date) VALUES(62, 'scheduled', 'lte', 10, 'business', 5,"
        " '2014-02-11')",
        # contingent without a trigger
        "INSERT INTO obligation_timing(obligation_id, kind, trigger_kind)"
        " VALUES(62, 'contingent', 'invoice')",
        # unresolved without a reason
        "INSERT INTO obligation_timing(obligation_id, kind) VALUES(62, 'unresolved')",
        # a reason on a non-unresolved row
        "INSERT INTO obligation_timing(obligation_id, kind, reason)"
        " VALUES(62, 'untimed', 'business_days')",
        # untimed with a trigger
        "INSERT INTO obligation_timing(obligation_id, kind, trigger_clause_ref_id)"
        " VALUES(62, 'untimed', 120)",
        # unknown kind, relation, unit, reason
        "INSERT INTO obligation_timing(obligation_id, kind) VALUES(62, 'overdue')",
        "INSERT INTO obligation_timing(obligation_id, kind, trigger_clause_ref_id, relation)"
        " VALUES(62, 'contingent', 120, 'before')",
        "INSERT INTO obligation_timing(obligation_id, kind, reason)"
        " VALUES(62, 'unresolved', 'too_hard')",
        # malformed bound
        "INSERT INTO obligation_timing(obligation_id, kind, relation, anchor_event_id,"
        " bound_date) VALUES(62, 'scheduled', 'lt', 5, '01/01/2011')",
    ],
)
def test_check_constraints(con, sql):
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(sql)


def test_one_timing_row_per_obligation(con):
    con.execute("INSERT INTO obligation_timing(obligation_id, kind) VALUES(62, 'untimed')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO obligation_timing(obligation_id, kind) VALUES(62, 'untimed')")


def test_valid_unresolved_business_day_row(con):
    con.execute(
        "INSERT INTO obligation_timing(obligation_id, kind, offset_days, offset_unit, reason)"
        " VALUES(62, 'unresolved', 10, 'business', 'business_days')"
    )
    assert timing(con, 62)[0] == "unresolved"
    assert lifecycle(con, 62) == ("pending", None)
