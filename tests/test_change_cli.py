"""Task 19: `python -m og.change`, the ChangeReport, and chain/context building.

Plan: docs/superpowers/plans/2026-10-02-wave3-change-gates.md, Task 19 plus rev 2
R4 (snapshot), R5 (cascade), R6/R2-3 (budget), R7 (pairing), R11 (report labels).
The graph is built by the real extraction CLI over SYNTHETIC documents with the
SYNTHETIC tests/extract_fakes client; change runs use tests/change_fakes.FakeAnthropic.
Routing in the fake: a request belongs to the category whose frozen question
definition text it contains (prompts/gate_questions_v1.yaml); Haiku requests are
gate samples, Sonnet requests are full checks.
"""

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import pytest
import yaml
from change_fakes import (
    HAIKU,
    SENTINEL_KEY,
    SONNET,
    FakeAnthropic,
    finding,
    findings_message,
    gate_message,
    message,
)
from extract_fakes import FakeClient, build_doc, echo_responder

from og.change.__main__ import main
from og.change.chain import build_gate_context
from og.change.report import load_change_report
from og.extract.__main__ import main as extract_main
from og.gates.types import load_questions
from og.store.db import connect

BASE, CO = "lease_base", "amend_one"
QUESTIONS = {q.category: q for q in load_questions()}
BASE_DOC = build_doc(
    [
        ("7.2", "Base Rent", ["7.2 Tenant shall pay Base Rent of $10,000 per month."]),
        ("8.1", "Surrender", ["8.1 Tenant shall surrender the Premises on June 30, 2018."]),
        ("9", "Services", ["9 Landlord shall maintain the cooling plant."]),
    ],
    doc_id=BASE,
    sha="b" * 64,
)
CO_DOC = build_doc(
    [
        (None, "Preamble", ["FIRST AMENDMENT between Landlord Co and Tenant Co."]),
        (
            "1",
            "Base Rent",
            [
                "1. Section 7.2 of the Lease is hereby deleted."
                " Tenant shall pay Base Rent of $12,000 per month."
            ],
        ),
        (
            "2",
            "Term",
            [
                "2. Currently Tenant is scheduled to surrender on June 30, 2018.",
                "Tenant shall surrender no later than June 30, 2020.",
            ],
        ),
    ],
    doc_id=CO,
    sha="c" * 64,
)
# Rules-tier hits on CO_DOC (frozen lexicons): price (rent; section_ref 7.2 -> payment),
# dates and termination (surrender*). guarantee, sla, parties_or_sites reach the classifier.
RULES_HIT = {"price", "dates", "termination"}
CLASSIFIED = {"guarantee", "sla", "parties_or_sites"}

SHIFT_ITEM = finding(
    kind="shifted_date",
    new_quote="Tenant shall surrender no later than June 30, 2020.",
    new_segment_id="p0004",
    old_doc="self",
    old_quote="Currently Tenant is scheduled to surrender on June 30, 2018",
    old_segment_id="p0003",
    old_value="2018-06-30",
    new_value="2020-06-30",
)


def category_of(kwargs) -> str:
    blob = json.dumps(kwargs.get("messages")) + json.dumps(kwargs.get("system"))
    hits = [c for c, q in QUESTIONS.items() if q.definition in blob]
    assert len(hits) == 1, hits
    return hits[0]


class Router:
    """Gate answers per category (consumed in order) and check findings per category."""

    def __init__(self, gate=None, checks=None, refuse=()):
        self.gate = {c: list(v) for c, v in (gate or {}).items()}
        self.checks = checks if checks is not None else {"dates": [SHIFT_ITEM]}
        self.refuse = set(refuse)
        self.seen: dict[str, list[str]] = defaultdict(list)

    def __call__(self, kwargs):
        cat = category_of(kwargs)
        if kwargs["model"] == HAIKU:
            self.seen["gate"].append(cat)
            answers = self.gate.get(cat) or ["yes"]
            out = answers.pop(0)
            return out if isinstance(out, BaseException) else gate_message(out)
        self.seen["check"].append(cat)
        if cat in self.refuse:
            return message(None, stop_reason="refusal", model=SONNET)
        return findings_message(self.checks.get(cat, []), model=SONNET)


SKIP_ALL_CLASSIFIED = {
    "guarantee": ["no", "no", "no"],
    "sla": ["no", "no", "no"],
    "parties_or_sites": ["no", "no", "yes"],
}


def write_sources():
    entries = []
    for doc_id, amends in ((BASE, None), (CO, BASE)):
        doc = BASE_DOC if doc_id == BASE else CO_DOC
        entries.append(
            {
                "id": doc_id,
                "url": f"https://www.sec.gov/Archives/example/{doc_id}.htm",
                "filer": "Example Co",
                "form": "8-K",
                "filing_date": "2011-03-09" if amends is None else "2012-05-17",
                "exhibit": "10.1",
                "title": f"{doc_id} (synthetic fixture)",
                "is_form": False,
                "local_path": f"data/raw/{doc_id}.htm",
                "sha256": doc.source_sha256,
                "agreement_type": "amendment" if amends else "lease",
                "amends": amends,
                "effective_date": None,
            }
        )
    Path("data/sources.yaml").write_text(yaml.safe_dump({"documents": entries}), encoding="utf-8")


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    for var in (
        "OG_EXTRACT_MODEL",
        "OG_EXTRACT_EFFORT",
        "OG_GATE_MODEL",
        "OG_CHANGE_EFFORT",
        "OG_BUDGET_USD",
        "OG_JEV_ENABLED",
        "OG_JEV_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    Path("data/text").mkdir(parents=True)
    BASE_DOC.save(Path("data/text") / f"{BASE}.json")
    CO_DOC.save(Path("data/text") / f"{CO}.json")
    write_sources()
    return tmp_path


@pytest.fixture
def extracted(workdir):
    assert extract_main([], client=FakeClient(responder=echo_responder)) == 0
    return workdir


def run(argv, router):
    client = FakeAnthropic(responder=router, count=1000)
    rc = main(argv, client=client)
    return rc, client


def creates(client, model):
    return [c for c in client.calls if c["model"] == model]


def records():
    path = Path("logs/change_runs.jsonl")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def db():
    return connect("data/graph.db")


def runs_in_db():
    con = sqlite3.connect("data/graph.db")
    try:
        return con.execute("SELECT run_id, mode FROM change_run ORDER BY id").fetchall()
    finally:
        con.close()


# --- preconditions -----------------------------------------------------------------------


def test_missing_extraction_exits_2(workdir, capsys):
    rc, client = run([], Router())
    assert rc == 2
    assert "make extract" in capsys.readouterr().err
    assert client.calls == [] and client.count_calls == []


def test_changed_textdoc_after_extraction_exits_2(extracted, capsys):
    changed = build_doc(
        [(None, "Preamble", ["FIRST AMENDMENT between Landlord Co and Tenant Co, revised."])],
        doc_id=CO,
        sha=CO_DOC.source_sha256,
    )
    changed.save(Path("data/text") / f"{CO}.json")
    rc, client = run([], Router())
    assert rc == 2
    assert "make extract" in capsys.readouterr().err
    assert client.calls == []


def test_gated_alone_without_a_stored_baseline_exits_2(extracted):
    rc, client = run(["--mode", "gated"], Router(gate=SKIP_ALL_CLASSIFIED))
    assert rc == 2
    assert creates(client, SONNET) == []
    assert runs_in_db() == []


def test_build_gate_context_maps_base_sections_to_obligation_types(extracted):
    ctx = build_gate_context(db(), BASE)
    assert dict(ctx.base_section_types) == {
        "7.2": frozenset({"payment"}),
        "8.1": frozenset({"payment"}),
        "9": frozenset({"payment"}),
    }


# --- paired run (rev 2 R5, R7; Review Focus 6) ------------------------------------------------


def test_both_modes_pair_and_gate(extracted):
    router = Router(gate=SKIP_ALL_CLASSIFIED)
    rc, client = run(["--mode", "both"], router)
    assert rc == 0
    # Ungated runs all six checks; gated replays them, so no further check calls.
    assert sorted(router.seen["check"]) == sorted(QUESTIONS)
    assert len(creates(client, SONNET)) == 6
    # Only categories without a rules hit reach Haiku, three samples each.
    assert Counter(router.seen["gate"]) == {c: 3 for c in CLASSIFIED}
    # Every model call was counted first (rev 2.1 R2-3) and none uses server-side fallback.
    assert len(client.count_calls) == len(client.calls)
    for kw in client.calls:
        assert "fallbacks" not in kw
        assert not any("fallback" in b for b in kw.get("betas") or [])

    assert [m for _r, m in runs_in_db()] == ["ungated", "gated"]
    ungated_rec, gated_rec = records()
    for rec in (ungated_rec, gated_rec):
        assert set(rec) >= {
            "run_id",
            "pair_id",
            "mode",
            "change_order_id",
            "decisions",
            "outcomes",
            "drops",
            "cost_usd",
            "incremental_cost_usd",
            "latency_ms",
        }
        assert rec["change_order_id"] == CO
    assert ungated_rec["pair_id"] == gated_rec["pair_id"]
    assert (ungated_rec["mode"], gated_rec["mode"]) == ("ungated", "gated")

    gated = load_change_report(db(), CO, "gated")
    gates = {g["question"]: g for g in gated["gates"]}
    assert len(gates) == 6
    assert not gates["touches_guarantee"]["run_check"]
    assert not gates["touches_sla"]["run_check"]
    assert gates["touches_parties_or_sites"]["run_check"]
    for cat in RULES_HIT:
        assert gates[f"touches_{cat}"]["tier"] == "rules"
        assert gates[f"touches_{cat}"]["run_check"]

    ungated = load_change_report(db(), CO, "ungated")
    assert ungated["pair_id"] == gated["pair_id"]
    for rep in (ungated, gated):
        [shift] = rep["shifted_dates"]
        assert shift["new"]["span_text"] == "Tenant shall surrender no later than June 30, 2020."
        assert shift["old_origin"] == "self"
        assert (shift["old_value"], shift["new_value"], shift["delta"]) == (
            "2018-06-30",
            "2020-06-30",
            "731",
        )


def test_no_cache_both_still_replays_for_gated(extracted):
    router = Router(gate=SKIP_ALL_CLASSIFIED)
    rc, client = run(["--mode", "both", "--no-cache"], router)
    assert rc == 0
    assert len(creates(client, SONNET)) == 6


def test_gated_alone_replays_the_stored_baseline(extracted):
    assert run(["--mode", "ungated"], Router())[0] == 0
    rc, client = run(["--mode", "gated"], Router(gate=SKIP_ALL_CLASSIFIED))
    assert rc == 0
    assert creates(client, SONNET) == []
    assert [m for _r, m in runs_in_db()] == ["ungated", "gated"]


def test_gate_sample_error_fails_open(extracted):
    gate = dict(SKIP_ALL_CLASSIFIED, sla=["no", TimeoutError("slow"), "no"])
    rc, _client = run(["--mode", "both"], Router(gate=gate))
    assert rc == 0
    gates = {g["question"]: g for g in load_change_report(db(), CO, "gated")["gates"]}
    assert gates["touches_sla"]["run_check"]
    assert gates["touches_sla"]["error"]
    assert not gates["touches_guarantee"]["run_check"]


# --- failures keep the previous snapshot ----------------------------------------------------


def test_refused_check_exits_3_and_keeps_previous_run(extracted):
    assert run(["--mode", "ungated"], Router())[0] == 0
    before = runs_in_db()
    rc, _client = run(["--mode", "ungated", "--no-cache"], Router(refuse={"price"}))
    assert rc == 3
    assert runs_in_db() == before
    assert any(o["status"] == "refused" for o in records()[-1]["outcomes"])


def test_tiny_budget_stops_before_any_model_call(extracted, monkeypatch):
    monkeypatch.setenv("OG_BUDGET_USD", "0.0001")
    rc, client = run(["--mode", "both"], Router(gate=SKIP_ALL_CLASSIFIED))
    assert rc == 3
    assert client.calls == []
    assert runs_in_db() == []
    assert any(o["status"] == "budget_stop" for o in records()[-1]["outcomes"])


def test_sentinel_key_never_written(extracted):
    run(["--mode", "both"], Router(gate=SKIP_ALL_CLASSIFIED))
    run(["--mode", "ungated", "--no-cache"], Router(refuse={"price"}))
    written = [p for p in Path(".").rglob("*") if p.is_file()]
    assert written
    for p in written:
        assert SENTINEL_KEY.encode() not in p.read_bytes(), p


# --- the report reads visible views only (rev 2 R11) ------------------------------------------


def test_report_drops_a_finding_whose_grounding_is_revoked(extracted):
    assert run(["--mode", "ungated"], Router())[0] == 0
    con = db()
    assert len(load_change_report(con, CO, "ungated")["shifted_dates"]) == 1
    con.execute(
        "UPDATE clause_ref SET grounded = 0 WHERE id IN"
        " (SELECT new_clause_ref_id FROM change_finding)"
    )
    report = load_change_report(con, CO, "ungated")
    assert report["shifted_dates"] == []
    assert report["supersessions"] == report["price_changes"] == []


def test_report_shape(extracted):
    assert run(["--mode", "ungated"], Router())[0] == 0
    report = load_change_report(db(), CO, "ungated")
    assert set(report) >= {
        "change_order_id",
        "mode",
        "run_id",
        "pair_id",
        "chain",
        "unresolved_documents",
        "supersessions",
        "shifted_dates",
        "price_changes",
        "potential_conflicts",
        "new_obligations",
        "gates",
        "cost_usd",
        "incremental_cost_usd",
    }
    assert [m["agreement_id"] for m in report["chain"]] == [BASE, CO]
    [shift] = report["shifted_dates"]
    assert set(shift["new"]) >= {
        "agreement_id",
        "section",
        "page",
        "char_start",
        "char_end",
        "span_text",
    }
    assert shift["categories"] == ["dates"]
    text = CO_DOC.text
    assert text[shift["new"]["char_start"] : shift["new"]["char_end"]] == shift["new"]["span_text"]


def test_new_obligations_exclude_resolved_supersession_edges(extracted):
    assert run(["--mode", "ungated"], Router())[0] == 0
    con = db()
    report = load_change_report(con, CO, "ungated")
    listed = {o["obligation_id"] for o in report["new_obligations"]}
    co_obligations = {
        r[0]
        for r in con.execute(
            "SELECT id FROM visible_obligation WHERE agreement_id = ?", (CO,)
        ).fetchall()
    }
    assert listed == co_obligations and len(listed) == 2
    for o in report["new_obligations"]:
        assert o["clause"]["span_text"]
    # Add a resolved, cited supersession edge from the rent obligation (by hand: the
    # report only reads visible views, whoever wrote the edge).
    new_id = con.execute(
        "SELECT o.id FROM visible_obligation o JOIN clause_ref c ON c.obligation_id = o.id"
        " WHERE o.agreement_id = ? AND c.span_text LIKE '%Base Rent%'",
        (CO,),
    ).fetchone()[0]
    old_id = con.execute(
        "SELECT o.id FROM visible_obligation o JOIN clause_ref c ON c.obligation_id = o.id"
        " WHERE o.agreement_id = ? AND c.span_text LIKE '%Base Rent%'",
        (BASE,),
    ).fetchone()[0]
    run_id = con.execute("SELECT id FROM change_run WHERE mode = 'ungated'").fetchone()[0]
    cite = con.execute("SELECT new_clause_ref_id FROM change_finding LIMIT 1").fetchone()[0]
    con.execute(
        "INSERT INTO supersedes(obligation_id, superseded_obligation_id, change_order_id,"
        " clause_ref_id, change_run_id) VALUES(?,?,?,?,?)",
        (new_id, old_id, CO, cite, run_id),
    )
    report = load_change_report(con, CO, "ungated")
    assert {o["obligation_id"] for o in report["new_obligations"]} == co_obligations - {new_id}
