"""Rev 2.5 end-to-end regressions: verify -> write_snapshot -> visible_* views.

Executed counterexamples from the Astra wave-2 round-5 review
(docs/reviews/2026-10-02-astra-wave2-review.md, Round 5, section B/C).
"""

import pytest
from test_pipeline_regressions_r3 import make_doc, raw, write

from og.store.db import connect


@pytest.fixture
def con(tmp_path):
    return connect(tmp_path / "g.db")


DUE = "Tenant shall pay Additional Rent within thirty (30) days after the Commencement Date."


@pytest.mark.parametrize(
    "definition,span",
    [
        ("It is false that “Commencement Date” is March 1, 2011.", None),
        (
            "It is false that “Commencement Date” is March 1, 2011.",
            "“Commencement Date” is March 1, 2011.",
        ),
        (
            "“Commencement Date” means March 1, 2011; provided that Landlord first"
            " delivers possession.",
            None,
        ),
    ],
)
def test_governed_event_date_never_schedules_a_deadline(con, definition, span):
    lines = [definition, DUE]
    ev = raw(lines, 1, kind="event", type=None, name="Commencement Date", date="2011-03-01")
    if span is not None:
        ev = raw(
            lines,
            1,
            span_text=span,
            kind="event",
            type=None,
            name="Commencement Date",
            date="2011-03-01",
        )
    write(
        con, make_doc(lines), [ev, raw(lines, 2, offset_days=30, anchor_event="Commencement Date")]
    )
    assert con.execute("SELECT effective_due, lifecycle FROM visible_obligation").fetchall() == [
        (None, "pending")
    ]


PAY = "Tenant shall pay Base Rent of $1,000 per month."


@pytest.mark.parametrize(
    "declaration,name",
    [
        ("Silver Cloud Holdings LLC, as Tenant.", "Holdings LLC"),
        ("Alpha LLC, a non-tenant company appointing Beta Inc. as Tenant.", "Alpha LLC"),
        ("The agreement does not designate Alpha LLC as Tenant.", "Alpha LLC"),
    ],
)
def test_unsupported_declaration_never_creates_a_visible_tenant(con, declaration, name):
    lines = [declaration, PAY]
    items = [
        raw(lines, 1, kind="party", type=None, name=name, role="tenant", status=None),
        raw(lines, 2, owed_by="Tenant", owed_to="Landlord", amount=1000.0),
    ]
    write(con, make_doc(lines), items)
    assert con.execute("SELECT count(*) FROM visible_agreement_party").fetchone()[0] == 0
    payer = con.execute("SELECT owed_by FROM visible_obligation").fetchall()
    assert payer == [(None,)]
