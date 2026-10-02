"""SYNTHETIC wave-3 store fixtures: a two-document chain with a real extraction graph.

The base lease (b0) and its change order (x1) are tiny TextDocs written through
og.store.writer.write_snapshot, so obligations, ClauseRefs, and extraction runs are
real rows. Findings and gate decisions are built directly from the frozen contract
types (og.change.types, og.gates.types), as verify and the cascade would emit them.
"""

from __future__ import annotations

from og.change.types import ChainMember, ChainSnapshot, ChangeRunInfo, CitedSpan, Finding
from og.eval.gold import textdoc_sha256
from og.extract.types import (
    Attempt,
    Evidence,
    RunInfo,
    VerifiedObligation,
    VerifiedParty,
    VerifyResult,
)
from og.gates.types import GateDecision, GateEvidence
from og.store.writer import write_snapshot
from og.textdoc import Page, Section, Segment, TextDoc

BASE_ID, CO_ID, OTHER_ID = "b0", "x1", "z9"

BASE_LINES = [
    (None, "DATACENTER LEASE between Landlord Co as Landlord and Tenant Co as Tenant."),
    ("7.2", "7.2 Tenant shall pay Base Rent of $10,000 per month."),
    ("7.3", "7.3 Tenant shall pay the Pathway Fee. Tenant shall pay the Cross Connect Fee."),
    ("8.1", "8.1 Tenant shall surrender the Premises on June 30, 2018."),
    ("9", "9 Landlord shall maintain the cooling plant."),
]
CO_LINES = [
    (None, "FIRST AMENDMENT between Landlord Co as Landlord and Tenant Co as Tenant."),
    (
        "1",
        "1. Section 7.2 of the Lease is hereby deleted and replaced:"
        " Tenant shall pay Base Rent of $12,000 per month.",
    ),
    (
        "2",
        "2. Currently Tenant is scheduled to surrender on June 30, 2018."
        " Tenant shall surrender no later than June 30, 2020.",
    ),
    ("3", "3. Section 2.C of 2A is hereby deleted in its entirety."),
    ("4", "4. Landlord shall install the cooling plant upgrade."),
]


def make_doc(doc_id: str, lines, sha: str) -> TextDoc:
    text = "\n".join(line for _n, line in lines)
    sections, segments, pos = [], [], 0
    for i, (number, line) in enumerate(lines):
        sid = f"s{i:04d}"
        end = pos + len(line) + (1 if i < len(lines) - 1 else 0)
        sections.append(Section(sid, number, f"H{i}", pos, end, None))
        segments.append(Segment(f"p{i + 1:04d}", sid, 1, pos, pos + len(line)))
        pos += len(line) + 1
    doc = TextDoc(doc_id, sha, text, sections, [Page(1, 0, len(text))], segments)
    doc.validate()
    return doc


BASE = make_doc(BASE_ID, BASE_LINES, "sha-b0")
CO = make_doc(CO_ID, CO_LINES, "sha-x1")
OTHER = make_doc(OTHER_ID, BASE_LINES, "sha-z9")
DOCS = {BASE_ID: BASE, CO_ID: CO, OTHER_ID: OTHER}


def ev(doc: TextDoc, quote: str, nth: int = 0) -> Evidence:
    start = -1
    for _ in range(nth + 1):
        start = doc.text.index(quote, start + 1)
    end = start + len(quote)
    seg = next(s for s in doc.segments if s.char_start <= start < s.char_end)
    sec = doc.section_by_id(seg.section_id)
    return Evidence(seg.id, sec.id, sec.number, seg.page, start, end, quote)


def cited(doc: TextDoc, quote: str, nth: int = 0) -> CitedSpan:
    return CitedSpan(doc.doc_id, ev(doc, quote, nth))


def obligation(doc: TextDoc, quote: str, type_: str = "payment") -> VerifiedObligation:
    return VerifiedObligation(
        evidence=ev(doc, quote),
        type=type_,
        status="active",
        owed_by=None,
        owed_to=None,
        description=quote,
        amount=None,
        currency=None,
        due_date=None,
        anchor_event=None,
        offset_days=None,
        trigger=None,
    )


# Obligation quotes, by document. Overlap with findings decides edge eligibility.
BASE_RENT = "Tenant shall pay Base Rent of $10,000 per month."
BASE_FEE_1 = "Tenant shall pay the Pathway Fee."
BASE_FEE_2 = "Tenant shall pay the Cross Connect Fee."
BASE_SURRENDER = "Tenant shall surrender the Premises on June 30, 2018."
BASE_COOLING = "Landlord shall maintain the cooling plant."
CO_RENT = "Tenant shall pay Base Rent of $12,000 per month."
CO_SURRENDER = "Tenant shall surrender no later than June 30, 2020."
CO_INSTALL = "Landlord shall install the cooling plant upgrade."

OBLIGATIONS = {
    BASE_ID: [
        (BASE_RENT, "payment"),
        (BASE_FEE_1, "payment"),
        (BASE_FEE_2, "payment"),
        (BASE_SURRENDER, "delivery"),
        (BASE_COOLING, "sla"),
    ],
    CO_ID: [(CO_RENT, "payment"), (CO_SURRENDER, "delivery"), (CO_INSTALL, "delivery")],
    OTHER_ID: [(BASE_RENT, "payment")],
}


def extract(con, doc_id: str, run_id: str, *, base: str | None = None, with_party=False):
    """Write a real extraction snapshot for one synthetic document."""
    doc = DOCS[doc_id]
    parties = []
    if with_party:
        parties = [VerifiedParty(ev(doc, "Landlord Co as Landlord"), "Landlord Co", "landlord")]
    result = VerifyResult(
        obligations=[obligation(doc, q, t) for q, t in OBLIGATIONS[doc_id]],
        events=[],
        parties=parties,
        drops=[],
        corrections=[],
    )
    write_snapshot(
        con,
        source={
            "id": doc_id,
            "url": f"https://www.sec.gov/{doc_id}.htm",
            "filer": "Filer",
            "filing_date": "2012-05-17",
            "form": "8-K",
            "exhibit": "10.1",
            "local_path": f"data/raw/{doc_id}.htm",
            "sha256": doc.source_sha256,
        },
        agreement={
            "id": doc_id,
            "title": doc_id,
            "type": "amendment" if base else "lease",
            "effective_date": None,
            "base_agreement_id": base,
            "is_form": False,
        },
        doc=doc,
        run=RunInfo(
            run_id=run_id,
            prompt_version="extract_v1@abc12345",
            model="claude-sonnet-5-5",
            textdoc_sha256=textdoc_sha256(doc),
            attempts=[Attempt("claude-sonnet-5-5", 10, 5, 0, 0, False)],
        ),
        result=result,
    )


def build_graph(con, *, with_party=False):
    extract(con, BASE_ID, "er-b0-1")
    extract(con, CO_ID, "er-x1-1", base=BASE_ID, with_party=with_party)
    extract(con, OTHER_ID, "er-z9-1")


def snapshot(con, *, override: dict | None = None) -> ChainSnapshot:
    """The current chain snapshot [b0, x1], read from extraction_run like Task 19 does."""
    members = []
    for agr, role in ((BASE_ID, "base"), (CO_ID, "change_order")):
        run_id = con.execute(
            "SELECT run_id FROM extraction_run WHERE source_id = ?", (agr,)
        ).fetchone()[0]
        m = dict(
            agreement_id=agr,
            role=role,
            source_sha256=DOCS[agr].source_sha256,
            textdoc_sha256=textdoc_sha256(DOCS[agr]),
            extraction_run_id=run_id,
        )
        if override and agr in override:
            m.update(override[agr])
        members.append(ChainMember(**m))
    return ChainSnapshot(tuple(members))


def info(mode="ungated", run_id=None, pair_id="pair-1", baseline=None) -> ChangeRunInfo:
    if mode == "gated" and baseline is None:
        baseline = "run-ungated"
    return ChangeRunInfo(
        run_id=run_id or f"run-{mode}",
        pair_id=pair_id,
        mode=mode,
        prompt_version="change_v1@abcd1234",
        question_set_sha256="q" * 64,
        model="claude-sonnet-5-5",
        fingerprints={"price": "f1", "dates": "f2"},
        baseline_run_id=baseline,
        cost_usd=0.25,
        incremental_cost_usd=0.2,
        latency_ms=1234,
    )


def find(
    kind,
    category,
    new_quote,
    *,
    old=None,
    origin=None,
    target_label=None,
    target_resolution=None,
    old_value=None,
    new_value=None,
    delta=None,
    currency=None,
    context=None,
    new_doc=CO,
) -> Finding:
    if origin is None and old is None:
        origin = "unresolved"
    elif origin is None:
        origin = "self" if old.agreement_id == CO_ID else "chain"
    return Finding(
        kind=kind,
        category=category,
        new=cited(new_doc, new_quote),
        old=old,
        old_origin=origin,
        target_label=target_label,
        target_resolution=target_resolution,
        old_value=old_value,
        new_value=new_value,
        delta=delta,
        currency=currency,
        context=context,
    )


# The canonical findings for the [b0, x1] chain.
SUP_RENT = find(
    "supersedes",
    "price",
    "Section 7.2 of the Lease is hereby deleted and replaced:"
    " Tenant shall pay Base Rent of $12,000 per month.",
    old=cited(BASE, BASE_RENT),
    target_label="Section 7.2 of the Lease",
    target_resolution="section",
)
SHIFT = find(
    "shifted_date",
    "dates",
    "Tenant shall surrender no later than June 30, 2020.",
    old=cited(CO, "Currently Tenant is scheduled to surrender on June 30, 2018."),
    old_value="2018-06-30",
    new_value="2020-06-30",
    delta="731",
)
UNRESOLVED = find(
    "supersedes",
    "termination",
    "Section 2.C of 2A is hereby deleted in its entirety.",
    target_label="Section 2.C of 2A",
    target_resolution="unresolved",
)
FINDINGS = [SUP_RENT, SHIFT, UNRESOLVED]

CATEGORIES = ("price", "dates", "termination", "guarantee", "sla", "parties_or_sites")


def decisions(skip=("guarantee",)) -> list[GateDecision]:
    out = []
    for cat in CATEGORIES:
        if cat in skip:
            out.append(
                GateDecision(
                    question=f"touches_{cat}",
                    backend="haiku",
                    tier="classifier",
                    answer=False,
                    confidence=1.0,
                    samples=(False, False, False),
                    evidence=(),
                    latency_ms=300,
                    input_tokens=600,
                    output_tokens=15,
                    cost_usd=0.0007,
                    error=None,
                    run_check=False,
                )
            )
        else:
            text = CO.text[CO.text.index("Rent") : CO.text.index("Rent") + 4]
            start = CO.text.index("Rent")
            out.append(
                GateDecision(
                    question=f"touches_{cat}",
                    backend="rules",
                    tier="rules",
                    answer=True,
                    confidence=1.0,
                    samples=(),
                    evidence=(GateEvidence("lexicon:rent", "p0002", start, start + 4, text),),
                    latency_ms=0,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    error=None,
                    run_check=True,
                )
            )
    return out


def counts(con) -> dict[str, int]:
    tables = ("change_run", "change_run_chain", "change_finding", "supersedes", "gate_decision")
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def obligation_id(con, agreement: str, quote: str) -> int:
    return con.execute(
        "SELECT o.id FROM obligation o JOIN clause_ref c ON c.obligation_id = o.id"
        " WHERE o.agreement_id = ? AND c.span_text = ?",
        (agreement, quote),
    ).fetchone()[0]


def lifecycle(con, oid: int) -> str | None:
    row = con.execute("SELECT lifecycle FROM visible_obligation WHERE id = ?", (oid,)).fetchone()
    return row[0] if row else None
