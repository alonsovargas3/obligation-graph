"""Rev 2.4 end-to-end regressions: verify -> write_snapshot -> visible_obligation.

Executed counterexamples from the Astra wave-2 round-4 review
(docs/reviews/2026-10-02-astra-wave2-review.md, Round 4, section B/C).
"""

import pytest
from test_pipeline_regressions_r3 import make_doc, raw, write

from og.store.db import connect


@pytest.fixture
def con(tmp_path):
    return connect(tmp_path / "g.db")


@pytest.mark.parametrize(
    "definition,proposed",
    [
        ("“Commencement Date” means the date that is 30 days after March 1, 2011.", "2011-03-01"),
        ("“Commencement Date” is not March 1, 2011; it is April 1, 2011.", "2011-03-01"),
        ("“Commencement Date” means the later of January 1, 2011 and March 1, 2011.", "2011-01-01"),
    ],
)
def test_non_literal_event_date_never_schedules_a_deadline(con, definition, proposed):
    lines = [
        definition,
        "Tenant shall pay Additional Rent within thirty (30) days after the Commencement Date.",
    ]
    items = [
        raw(lines, 1, kind="event", type=None, name="Commencement Date", date=proposed),
        raw(lines, 2, offset_days=30, anchor_event="Commencement Date"),
    ]
    write(con, make_doc(lines), items)
    assert con.execute("SELECT effective_due, lifecycle FROM visible_obligation").fetchall() == [
        (None, "pending")
    ]


def _payer(con):
    rows = con.execute(
        "SELECT p.name FROM visible_obligation o LEFT JOIN party p ON p.id = o.owed_by"
    ).fetchall()
    assert len(rows) == 1
    return rows[0][0]


def test_truncated_company_name_never_becomes_the_payer(con):
    lines = [
        "Landlord Holdings LLC, as Tenant, leases space from Alpha LLC, as Landlord.",
        "Landlord shall pay the Tenant Improvement Allowance of $10,000.",
    ]
    items = [
        raw(lines, 1, kind="party", type=None, name="Holdings LLC", role="landlord", status=None),
        raw(lines, 2, owed_by="Landlord", owed_to="Tenant", amount=10000.0),
    ]
    write(con, make_doc(lines), items)
    assert _payer(con) != "Holdings LLC"


def test_role_across_another_entity_never_becomes_the_payer(con):
    lines = [
        "Alpha LLC leases space to Beta Inc., as Tenant.",
        "Tenant shall pay Base Rent of $1,000 per month.",
    ]
    items = [
        raw(lines, 1, kind="party", type=None, name="Alpha LLC", role="tenant", status=None),
        raw(lines, 2, owed_by="Tenant", owed_to="Landlord", amount=1000.0),
    ]
    write(con, make_doc(lines), items)
    assert _payer(con) != "Alpha LLC"
