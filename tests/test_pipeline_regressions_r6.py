"""Rev 2.6 end-to-end regressions on real corpus text (Applied Digital guaranty, p0005, p0032).

Executed by Astra wave-2 round 6 (docs/reviews/2026-10-02-astra-wave2-review.md, Round 6, C).
"""

import pytest
from test_pipeline_regressions_r3 import make_doc, raw, write

from og.store.db import connect

GUARANTY = (
    "THIS UNCONDITIONAL SPRINGING GUARANTY OF PAYMENT AND PERFORMANCE (this “Guaranty”)"
    " is made as of March 30, 2026 by COREWEAVE, INC., a Delaware corporation"
    " (“Guarantor”), to APLD ELN-02 LLC, a Delaware limited liability company"
    " (“Landlord”), and is acknowledged and agreed to by Landlord."
)
CONSENTS = (
    "Guarantor hereby consents, prospectively, to Landlord’s taking or entering into any"
    " or all of the foregoing actions or omissions."
)


@pytest.fixture
def con(tmp_path):
    return connect(tmp_path / "g.db")


def parties(con):
    return con.execute(
        "SELECT p.name, ap.role FROM visible_agreement_party ap JOIN party p ON p.id = ap.party_id"
        " ORDER BY p.name"
    ).fetchall()


@pytest.mark.parametrize(
    "line,name",
    [(GUARANTY, "INC."), (GUARANTY, "a Delaware corporation"), (CONSENTS, "hereby consents")],
)
def test_partial_field_or_clause_never_becomes_a_visible_party(con, line, name):
    lines = [line]
    write(
        con,
        make_doc(lines),
        [raw(lines, 1, kind="party", type=None, name=name, role="guarantor", status=None)],
    )
    assert parties(con) == []


def test_complete_corporate_names_are_visible(con):
    lines = [GUARANTY]
    items = [
        raw(
            lines, 1, kind="party", type=None, name="COREWEAVE, INC.", role="guarantor", status=None
        ),
        raw(
            lines, 1, kind="party", type=None, name="APLD ELN-02 LLC", role="landlord", status=None
        ),
    ]
    write(con, make_doc(lines), items)
    assert parties(con) == [("APLD ELN-02 LLC", "landlord"), ("COREWEAVE, INC.", "guarantor")]
