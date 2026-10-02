"""Task 18: og.change.writer.write_change_run (plan rev 2 R2, R4, R7; rev 2.1 R2-1).

The writer is the only code that sets grounded = 1 on change-run ClauseRefs. It writes
one change run per (change order, mode) in one transaction, re-checks the chain
snapshot and every span first, and writes supersedes edges only from ungated runs.
"""

import dataclasses
import json

import pytest
from change_db import (
    BASE,
    BASE_COOLING,
    BASE_FEE_1,
    BASE_FEE_2,
    BASE_ID,
    BASE_RENT,
    CO,
    CO_ID,
    CO_RENT,
    CO_SURRENDER,
    DOCS,
    FINDINGS,
    SHIFT,
    SUP_RENT,
    UNRESOLVED,
    build_graph,
    cited,
    counts,
    decisions,
    find,
    info,
    lifecycle,
    obligation_id,
    snapshot,
)

from og.change.types import SnapshotChanged
from og.change.writer import write_change_run
from og.store.db import connect


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "g.db")
    build_graph(c)
    return c


def write(con, mode="ungated", findings=FINDINGS, decs=None, snap=None, docs=DOCS, **kw):
    write_change_run(
        con,
        info=info(mode, **kw),
        snapshot=snap or snapshot(con),
        docs=docs,
        findings=findings,
        decisions=decisions() if decs is None else decs,
    )


def visible_findings(con):
    return con.execute(
        "SELECT f.kind, f.category, f.old_origin, f.target_label, f.target_resolution,"
        " f.old_value, f.new_value, f.delta, n.span_text, o.span_text, o.agreement_id"
        " FROM visible_change_finding f JOIN clause_ref n ON n.id = f.new_clause_ref_id"
        " LEFT JOIN clause_ref o ON o.id = f.old_clause_ref_id ORDER BY f.id"
    ).fetchall()


def edges(con):
    return con.execute(
        "SELECT obligation_id, superseded_obligation_id FROM visible_supersedes"
    ).fetchall()


# --- what gets written -------------------------------------------------------------------


def test_run_row_and_chain_vector(con):
    write(con)
    run = con.execute(
        "SELECT run_id, pair_id, change_order_id, mode, prompt_version, question_set_sha256,"
        " model, fingerprints_json, baseline_run_id, chain_size, cost_usd,"
        " incremental_cost_usd, latency_ms, completed_at IS NOT NULL FROM change_run"
    ).fetchone()
    assert run[:7] == (
        "run-ungated",
        "pair-1",
        CO_ID,
        "ungated",
        "change_v1@abcd1234",
        "q" * 64,
        "claude-sonnet-5-5",
    )
    assert json.loads(run[7]) == {"price": "f1", "dates": "f2"}
    assert run[8:] == (None, 2, 0.25, 0.2, 1234, 1)
    chain = con.execute(
        "SELECT position, agreement_id, role, textdoc_sha256, extraction_run_id"
        " FROM change_run_chain ORDER BY position"
    ).fetchall()
    snap = snapshot(con)
    assert chain == [
        (i, m.agreement_id, m.role, m.textdoc_sha256, m.extraction_run_id)
        for i, m in enumerate(snap.members)
    ]
    assert con.execute("SELECT count(*) FROM fresh_change_run").fetchone()[0] == 1


def test_findings_are_visible_with_their_fields(con):
    write(con)
    rows = visible_findings(con)
    assert rows == [
        (
            "supersedes",
            "price",
            "chain",
            "Section 7.2 of the Lease",
            "section",
            None,
            None,
            None,
            SUP_RENT.new.evidence.span_text,
            BASE_RENT,
            BASE_ID,
        ),
        (
            "shifted_date",
            "dates",
            "self",
            None,
            None,
            "2018-06-30",
            "2020-06-30",
            "731",
            CO_SURRENDER,
            "Currently Tenant is scheduled to surrender on June 30, 2018.",
            CO_ID,
        ),
        (
            "supersedes",
            "termination",
            "unresolved",
            "Section 2.C of 2A",
            "unresolved",
            None,
            None,
            None,
            "Section 2.C of 2A is hereby deleted in its entirety.",
            None,
            None,
        ),
    ]


def test_change_refs_are_exact_grounded_slices(con):
    write(con)
    refs = con.execute(
        "SELECT c.agreement_id, c.char_start, c.char_end, c.span_text, c.grounded, c.section,"
        " c.obligation_id FROM clause_ref c WHERE c.id IN ("
        " SELECT new_clause_ref_id FROM change_finding UNION"
        " SELECT old_clause_ref_id FROM change_finding UNION"
        " SELECT context_clause_ref_id FROM change_finding)"
    ).fetchall()
    assert len(refs) == 5
    for agr, start, end, text, grounded, _section, oid in refs:
        assert DOCS[agr].text[start:end] == text
        assert grounded == 1
        assert oid is None  # change-owned refs never claim an obligation
    sections = {r[3]: r[5] for r in refs}
    assert sections[BASE_RENT] == "7.2"


def test_context_ref_is_written(con):
    price = find(
        "price_change",
        "price",
        "$12,000",
        new_value="12000.00",
        currency="USD",
        context=cited(CO, "Tenant shall pay Base Rent of"),
    )
    write(con, findings=[price])
    row = con.execute(
        "SELECT x.span_text, x.agreement_id, x.grounded, f.new_value, f.currency"
        " FROM visible_change_finding f JOIN clause_ref x ON x.id = f.context_clause_ref_id"
    ).fetchone()
    assert row == ("Tenant shall pay Base Rent of", CO_ID, 1, "12000.00", "USD")


def test_gate_decisions_are_written(con):
    write(con)
    rows = con.execute(
        "SELECT g.question, g.backend, g.tier, g.answer, g.confidence, g.samples_json,"
        " g.evidence_json, g.run_check, g.change_order_id, r.run_id, g.cost_usd, g.error"
        " FROM gate_decision g JOIN change_run r ON r.id = g.change_run_id ORDER BY g.id"
    ).fetchall()
    assert [r[0] for r in rows] == [
        "touches_price",
        "touches_dates",
        "touches_termination",
        "touches_guarantee",
        "touches_sla",
        "touches_parties_or_sites",
    ]
    guarantee = rows[3]
    assert guarantee[1:5] == ("haiku", "classifier", 0, 1.0)
    assert json.loads(guarantee[5]) == [False, False, False]
    assert guarantee[7] == 0
    price = rows[0]
    assert price[1:4] == ("rules", "rules", 1)
    assert json.loads(price[5]) == []
    [evidence] = json.loads(price[6])
    assert evidence["rule"] == "lexicon:rent"
    assert evidence["segment_id"] == "p0002"
    assert CO.text[evidence["char_start"] : evidence["char_end"]] == evidence["text"] == "Rent"
    assert price[7] == 1
    assert all(r[8] == CO_ID and r[9] == "run-ungated" for r in rows)


# --- supersedes edges (rev 2 R2, rev 2.1 R2-1) ---------------------------------------------


def test_ungated_resolved_supersession_writes_one_edge(con):
    write(con)
    new = obligation_id(con, CO_ID, CO_RENT)
    old = obligation_id(con, BASE_ID, BASE_RENT)
    assert edges(con) == [(new, old)]
    assert lifecycle(con, old) == "superseded"
    assert lifecycle(con, new) != "superseded"
    cite = con.execute(
        "SELECT c.span_text, c.agreement_id FROM supersedes s"
        " JOIN clause_ref c ON c.id = s.clause_ref_id"
    ).fetchone()
    assert cite == (SUP_RENT.new.evidence.span_text, CO_ID)


def test_range_resolved_target_also_writes_an_edge(con):
    f = dataclasses.replace(SUP_RENT, target_label="Item 7.2", target_resolution="range")
    write(con, findings=[f])
    assert len(edges(con)) == 1


def test_gated_run_writes_findings_but_no_edges(con):
    write(con)
    before = edges(con)
    write(con, mode="gated")
    gated_id = con.execute("SELECT id FROM change_run WHERE mode='gated'").fetchone()[0]
    n_gated = "SELECT count(*) FROM supersedes WHERE change_run_id=?"
    assert con.execute(n_gated, (gated_id,)).fetchone()[0] == 0
    assert edges(con) == before
    assert (
        con.execute("SELECT count(*) FROM visible_change_finding WHERE mode='gated'").fetchone()[0]
        == 3
    )


def test_gated_only_never_marks_superseded(con):
    write(con, mode="ungated", findings=[])
    write(con, mode="gated", findings=[SUP_RENT])
    assert lifecycle(con, obligation_id(con, BASE_ID, BASE_RENT)) != "superseded"


@pytest.mark.parametrize(
    "finding",
    [
        # W3-2: self-origin supersession over the very same obligation.
        find(
            "supersedes",
            "dates",
            CO_SURRENDER,
            old=cited(CO, CO_SURRENDER),
            origin="self",
        ),
        # Unresolved target: no old side, no edge.
        UNRESOLVED,
        # Document-only resolution is not clause resolution (rev 2.1 R2-1).
        dataclasses.replace(SUP_RENT, target_resolution="document"),
        # No explicit target at all.
        dataclasses.replace(SUP_RENT, target_label=None, target_resolution=None),
        # Type mismatch: payment cannot supersede an sla obligation.
        dataclasses.replace(SUP_RENT, old=cited(BASE, BASE_COOLING)),
        # Ambiguous: the old span overlaps two base obligations.
        dataclasses.replace(SUP_RENT, old=cited(BASE, f"{BASE_FEE_1} {BASE_FEE_2}")),
        # The new span overlaps no change-order obligation.
        dataclasses.replace(
            SUP_RENT,
            new=cited(CO, "Section 7.2 of the Lease is hereby deleted"),
        ),
        # Other kinds never write edges.
        dataclasses.replace(SUP_RENT, kind="potential_conflict"),
    ],
    ids=[
        "self_same_obligation",
        "unresolved",
        "document_only",
        "no_target",
        "type_mismatch",
        "ambiguous_old",
        "no_new_obligation",
        "potential_conflict",
    ],
)
def test_no_edge_cases(con, finding):
    write(con, findings=[finding])
    assert edges(con) == []
    assert con.execute("SELECT count(*) FROM supersedes").fetchone()[0] == 0
    assert all(
        lifecycle(con, oid) != "superseded"
        for (oid,) in con.execute("SELECT id FROM obligation").fetchall()
    )


def test_ambiguous_new_side_writes_no_edge(con):
    """The new span overlaps two change-order obligations (rent and surrender lines)."""
    two = (
        "Tenant shall pay Base Rent of $12,000 per month.\n2. Currently Tenant is scheduled"
        " to surrender on June 30, 2018. Tenant shall surrender no later than June 30, 2020."
    )
    f = dataclasses.replace(SUP_RENT, new=cited(CO, two))
    write(con, findings=[f])
    assert edges(con) == []


# --- replacement and pairing (rev 2 R7) --------------------------------------------------


def test_rewriting_same_mode_replaces_the_run(con):
    write(con)
    first = counts(con)
    refs_before = con.execute("SELECT count(*) FROM clause_ref").fetchone()[0]
    write(con, run_id="run-ungated-2")
    assert counts(con) == first
    assert con.execute("SELECT count(*) FROM clause_ref").fetchone()[0] == refs_before
    assert con.execute("SELECT run_id FROM change_run").fetchall() == [("run-ungated-2",)]


def test_replacing_the_ungated_run_deletes_its_paired_gated_run(con):
    write(con)
    write(con, mode="gated")
    assert con.execute("SELECT count(*) FROM change_run").fetchone()[0] == 2
    write(con, run_id="run-ungated-2", pair_id="pair-2")
    assert con.execute("SELECT run_id, mode FROM change_run").fetchall() == [
        ("run-ungated-2", "ungated")
    ]
    assert (
        con.execute("SELECT count(*) FROM gate_decision WHERE change_run_id IS NULL").fetchone()[0]
        == 0
    )
    assert con.execute("SELECT count(*) FROM gate_decision").fetchone()[0] == 6


def test_gated_run_requires_its_current_ungated_baseline(con):
    write(con)
    with pytest.raises(SnapshotChanged):
        write(con, mode="gated", baseline="run-does-not-exist")
    assert con.execute("SELECT count(*) FROM change_run WHERE mode='gated'").fetchone()[0] == 0


def test_gated_run_without_any_baseline_is_refused(con):
    with pytest.raises(SnapshotChanged):
        write(con, mode="gated")
    assert counts(con)["change_run"] == 0


# --- snapshot and span rechecks (rev 2 R4) -------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {BASE_ID: {"extraction_run_id": "er-b0-OLD"}},
        {CO_ID: {"textdoc_sha256": "0" * 64}},
    ],
    ids=["stale_extraction_run", "stale_textdoc_hash"],
)
def test_snapshot_mismatch_writes_nothing_and_keeps_previous_run(con, override):
    write(con)
    before = counts(con)
    findings_before = visible_findings(con)
    with pytest.raises(SnapshotChanged):
        write(con, run_id="run-ungated-2", snap=snapshot(con, override=override))
    assert counts(con) == before
    assert visible_findings(con) == findings_before
    assert con.execute("SELECT run_id FROM change_run").fetchall() == [("run-ungated",)]


def test_doc_text_not_matching_snapshot_hash_is_refused(con):
    other_text = dict(DOCS)
    other_text[BASE_ID] = DOCS["z9"]  # same text, different source sha: canonical hash differs
    with pytest.raises(SnapshotChanged):
        write(con, docs=other_text)
    assert counts(con)["change_run"] == 0


def test_span_mismatch_is_refused(con):
    bad_ev = dataclasses.replace(SHIFT.new.evidence, span_text="Tenant shall surrender LATER")
    bad = dataclasses.replace(SHIFT, new=dataclasses.replace(SHIFT.new, evidence=bad_ev))
    with pytest.raises(SnapshotChanged) as exc:
        write(con, findings=[SUP_RENT, bad])
    assert exc.value.args[0] == "span_mismatch"
    assert counts(con) == {
        "change_run": 0,
        "change_run_chain": 0,
        "change_finding": 0,
        "supersedes": 0,
        "gate_decision": 0,
    }


def test_old_span_from_a_document_outside_the_snapshot_is_refused(con):
    from change_db import OTHER

    bad = dataclasses.replace(SUP_RENT, old=cited(OTHER, BASE_RENT))
    with pytest.raises(SnapshotChanged):
        write(con, findings=[bad])
    assert counts(con)["change_run"] == 0


def test_failure_mid_write_rolls_back_everything(con):
    """One transaction: a decision violating a CHECK leaves no partial run behind."""
    write(con)
    before = counts(con)
    bad = [dataclasses.replace(d, tier="model") for d in decisions()]
    with pytest.raises(Exception):  # noqa: B017 - sqlite3.IntegrityError or a wrapper
        write(con, run_id="run-ungated-2", decs=bad)
    assert counts(con) == before
    assert con.execute("SELECT run_id FROM change_run").fetchall() == [("run-ungated",)]
    assert len(visible_findings(con)) == 3
