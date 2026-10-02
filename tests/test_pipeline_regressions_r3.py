"""Rev 2.3 end-to-end regressions: verify -> write_snapshot -> visible_obligation.

Executed counterexamples from the Astra wave-2 round-3 review
(docs/reviews/2026-10-02-astra-wave2-review.md, Round 3, section C).
"""

import hashlib

import pytest

from og.extract.types import Attempt, RawItem, RunInfo
from og.extract.verify import verify
from og.store.db import connect
from og.store.writer import write_snapshot
from og.textdoc import Page, Section, Segment, TextDoc

SHA = "f" * 64


def make_doc(lines):
    text = "\n".join(lines)
    sections, segments, pos = [], [], 0
    for i, line in enumerate(lines):
        end = pos + len(line) + (1 if i < len(lines) - 1 else 0)
        sections.append(Section(f"s{i:04d}", str(i) if i else None, f"H{i}", pos, end, None))
        segments.append(Segment(f"p{i + 1:04d}", f"s{i:04d}", 1, pos, pos + len(line)))
        pos += len(line) + 1
    doc = TextDoc("lease", SHA, text, sections, [Page(1, 0, len(text))], segments)
    doc.validate()
    return doc


def raw(lines, n, **kw):
    fields = dict(
        span_text=lines[n - 1],
        segment_id=f"p{n:04d}",
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


def write(con, doc, items):
    result = verify(doc, items)
    run = RunInfo(
        run_id="r1",
        prompt_version="extract_v1@abc12345",
        model="claude-sonnet-5-5",
        textdoc_sha256=hashlib.sha256(doc.to_json().encode()).hexdigest(),
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
    write_snapshot(con, source=source, agreement=agreement, doc=doc, run=run, result=result)
    return result


@pytest.fixture
def con(tmp_path):
    return connect(tmp_path / "g.db")


DATES = [
    "“Commencement Date” means January 1, 2011. Rent is payable March 1, 2011.",
    "Tenant shall pay Additional Rent within thirty (30) days after the Commencement Date.",
]


def due(con):
    return con.execute("SELECT effective_due, lifecycle FROM visible_obligation").fetchall()


def test_later_unrelated_date_does_not_schedule_the_deadline(con):
    items = [
        raw(DATES, 1, kind="event", type=None, name="Commencement Date", date="2011-03-01"),
        raw(DATES, 2, offset_days=30, anchor_event="Commencement Date"),
    ]
    write(con, make_doc(DATES), items)
    assert due(con) == [(None, "pending")]


def test_defining_date_schedules_the_deadline(con):
    items = [
        raw(DATES, 1, kind="event", type=None, name="Commencement Date", date="2011-01-01"),
        raw(DATES, 2, offset_days=30, anchor_event="Commencement Date"),
    ]
    write(con, make_doc(DATES), items)
    assert due(con) == [("2011-01-31", "scheduled")]


PARTIES = [
    "This lease is between Landlord Alpha LLC and Tenant Beta Inc.",
    "Tenant shall pay Base Rent of $1,000 per month.",
]


def payer(con):
    rows = con.execute(
        "SELECT p.name FROM visible_obligation o LEFT JOIN party p ON p.id = o.owed_by"
    ).fetchall()
    assert len(rows) == 1
    return rows[0][0]


def test_next_party_role_does_not_make_alpha_the_payer(con):
    items = [
        raw(PARTIES, 1, kind="party", type=None, name="Alpha LLC", role="tenant", status=None),
        raw(PARTIES, 2, owed_by="Tenant", owed_to="Landlord", amount=1000.0),
    ]
    write(con, make_doc(PARTIES), items)
    assert payer(con) != "Alpha LLC"


def test_bound_roles_resolve_the_real_payer(con):
    items = [
        raw(PARTIES, 1, kind="party", type=None, name="Alpha LLC", role="landlord", status=None),
        raw(PARTIES, 1, kind="party", type=None, name="Beta Inc.", role="tenant", status=None),
        raw(PARTIES, 2, owed_by="Tenant", owed_to="Landlord", amount=1000.0),
    ]
    write(con, make_doc(PARTIES), items)
    assert payer(con) == "Beta Inc."
