"""Rev 2.2 end-to-end regressions: verify -> write_snapshot -> visible_obligation.

Each case is an executed counterexample from the Astra wave-2 round-2 review
(docs/reviews/2026-10-02-astra-wave2-review.md, section C): a rule gap that
passed verification and reached the visible graph.
"""

import hashlib
import sqlite3

import pytest

from og.extract.types import Attempt, RawItem, RunInfo
from og.extract.verify import verify
from og.store.db import connect
from og.store.writer import write_snapshot
from og.textdoc import Page, Section, Segment, TextDoc

LINES = [
    "LEASE between DIGITAL 55 MIDDLESEX, LLC, as Landlord, and CONSTANT CONTACT, INC., as Tenant.",
    "1. \u201cCommencement Date\u201d means [\u25cf].",
    "2. \u201cDelivery Date\u201d means March 1, 2011.",
    "3. Tenant shall pay Additional Rent within thirty (30) days after the Commencement Date.",
    "4. Tenant shall pay Base Rent of $54,000 per month.",
    "5. Tenant shall pay the deposit by March 1, 2011 within 30 days after the Commencement Date.",
]
SHA = "e" * 64


def make_doc():
    text = "\n".join(LINES)
    sections, segments, pos = [], [], 0
    for i, line in enumerate(LINES):
        end = pos + len(line) + (1 if i < len(LINES) - 1 else 0)
        sections.append(Section(f"s{i:04d}", str(i) if i else None, f"H{i}", pos, end, None))
        segments.append(Segment(f"p{i + 1:04d}", f"s{i:04d}", 1, pos, pos + len(line)))
        pos += len(line) + 1
    doc = TextDoc("lease", SHA, text, sections, [Page(1, 0, len(text))], segments)
    doc.validate()
    return doc


DOC = make_doc()


def seg(n):
    return f"p{n:04d}"


def raw(n, span=None, **kw):
    fields = dict(
        span_text=span if span is not None else LINES[n - 1],
        segment_id=seg(n),
        kind="obligation",
        type="payment",
        owed_by=None,
        owed_to=None,
        description=None,
        amount=None,
        currency=None,
        due_date=None,
        anchor_event=None,
        offset_days=None,
        trigger=None,
        status="active",
        name=None,
        date=None,
        role=None,
    )
    fields.update(kw)
    return RawItem(**fields)


def event(n, name, date=None):
    return raw(n, kind="event", type=None, name=name, date=date, status=None)


def party(name, role):
    return raw(1, kind="party", type=None, name=name, role=role, status=None)


def write(con, items, run_id="r1"):
    result = verify(DOC, items)
    run = RunInfo(
        run_id=run_id,
        prompt_version="extract_v1@abc12345",
        model="claude-sonnet-5-5",
        textdoc_sha256=hashlib.sha256(DOC.to_json().encode()).hexdigest(),
        attempts=[Attempt("claude-sonnet-5-5", 100, 50, 0, 0, False)],
    )
    source = {
        "id": "lease",
        "url": "https://www.sec.gov/lease.htm",
        "filer": "Filer",
        "filing_date": "2011-03-09",
        "form": "10-K",
        "exhibit": "10.41",
        "local_path": "data/raw/lease.htm",
        "sha256": SHA,
    }
    agreement = {
        "id": "lease",
        "title": "Lease",
        "type": "lease",
        "effective_date": None,
        "base_agreement_id": None,
        "is_form": False,
    }
    write_snapshot(con, source=source, agreement=agreement, doc=DOC, run=run, result=result)
    return result


@pytest.fixture
def con(tmp_path):
    return connect(tmp_path / "g.db")


def visible_by_quote(con, quote):
    rows = con.execute(
        "SELECT o.id, o.effective_due, o.lifecycle, o.due_date, o.offset_days,"
        " o.anchor_event_id, o.owed_by FROM visible_obligation o"
        " JOIN clause_ref c ON c.obligation_id = o.id WHERE c.span_text = ?",
        (quote,),
    ).fetchall()
    assert len(rows) == 1, rows
    return rows[0]


def test_swapped_event_name_does_not_schedule_a_deadline(con):
    """R2-2: the Delivery Date clause must not become the Commencement Date."""
    write(
        con,
        [
            event(3, "Commencement Date", date="2011-03-01"),
            raw(4, offset_days=30, anchor_event="Commencement Date"),
        ],
    )
    _, effective_due, lifecycle, *_ = visible_by_quote(con, LINES[3])
    assert effective_due is None
    assert lifecycle == "pending"
    names = [r[0] for r in con.execute("SELECT name FROM event WHERE date IS NOT NULL")]
    assert "Commencement Date" not in names


def test_swapped_party_roles_do_not_make_landlord_the_payer(con):
    """R2-4: name-role co-occurrence in the preamble must not reverse the parties."""
    write(
        con,
        [
            party("DIGITAL 55 MIDDLESEX, LLC", "tenant"),
            party("CONSTANT CONTACT, INC.", "landlord"),
            raw(5, owed_by="Tenant", owed_to="Landlord"),
        ],
    )
    *_, owed_by = visible_by_quote(con, "4. Tenant shall pay Base Rent of $54,000 per month.")
    name = None
    if owed_by is not None:
        name = con.execute("SELECT name FROM party WHERE id = ?", (owed_by,)).fetchone()[0]
    assert name in (None, "CONSTANT CONTACT, INC.")


def test_correct_party_roles_resolve_the_payer(con):
    write(
        con,
        [
            party("DIGITAL 55 MIDDLESEX, LLC", "landlord"),
            party("CONSTANT CONTACT, INC.", "tenant"),
            raw(5, owed_by="Tenant", owed_to="Landlord"),
        ],
    )
    *_, owed_by = visible_by_quote(con, "4. Tenant shall pay Base Rent of $54,000 per month.")
    name = con.execute("SELECT name FROM party WHERE id = ?", (owed_by,)).fetchone()[0]
    assert name == "CONSTANT CONTACT, INC."


def test_deadline_conflict_writes_without_integrity_error(con):
    """R2-5: an absolute date plus a relative pair must not violate the DB CHECK."""
    items = [
        event(2, "Commencement Date"),
        raw(6, due_date="2011-03-01", offset_days=30, anchor_event="Commencement Date"),
    ]
    try:
        write(con, items)
    except sqlite3.IntegrityError as exc:  # pragma: no cover - the regression itself
        pytest.fail(f"deadline conflict reached the CHECK constraint: {exc}")
    _, effective_due, lifecycle, due_date, offset_days, anchor_id, _ = visible_by_quote(
        con, LINES[5]
    )
    assert (due_date, offset_days, anchor_id) == ("2011-03-01", None, None)
    assert (effective_due, lifecycle) == ("2011-03-01", "scheduled")


def test_conflict_rerun_replaces_prior_snapshot(con):
    write(con, [raw(5, owed_by="Tenant")], run_id="r1")
    write(
        con,
        [raw(6, due_date="2011-03-01", offset_days=30, anchor_event="Commencement Date")],
        run_id="r2",
    )
    assert con.execute("SELECT count(*) FROM visible_obligation").fetchone()[0] == 1
    assert con.execute("SELECT run_id FROM extraction_run").fetchall() == [("r2",)]
