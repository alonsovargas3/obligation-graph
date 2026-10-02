"""Task 20: change-order reference set, scorer, and `python -m og.eval change`.

Plan: Task 20 plus rev 2 R8 (honest gate metrics) and R9 (finding unit and matcher).
The DB state is inserted directly through the schema-v3 contract (no writer), so this
module depends only on frozen files.

THE GOLD FILE SHAPE BELOW IS THE CONTRACT FOR eval/gold/change/<change_order_id>.yaml (C6):

  change_order_id: <agreement id>
  chain: [<base id>, ..., <change order id>]          # ordered as the ChainSnapshot
  textdoc_sha256: {<agreement id>: <canonical TextDoc hash>, ...}   # every chain member
  provenance: {drafted_by: str, adjudicated_by: str, spot_checked: int}
  scope: full_agreement
  gates:                                               # exactly the six categories
    <category>: {answer: bool, segment_ids: [<change-order segment id>, ...]}
  findings:
    - kind: supersedes | shifted_date | price_change | potential_conflict
      new_segment_id: <change-order segment id>
      new_span_text: <exact substring of that segment>
      old_origin: chain | self | unresolved
      old_doc: <earlier chain agreement id>            # chain only, else null
      old_segment_id: <segment id>                     # chain and self, else null
      old_span_text: <exact substring of that segment> # chain and self, else null
      target_label: <str or null>                      # required for unresolved
      old_value: <str or null>
      new_value: <str or null>
      delta: <str or null>
      currency: <str or null>
"""

import json

import pytest
import yaml
from change_db import BASE, BASE_COOLING, BASE_RENT, CO, CO_INSTALL, CO_SURRENDER, ev

from og.eval.__main__ import main as eval_main
from og.eval.change_gold import load_change_gold
from og.eval.change_score import clopper_pearson_upper, score_change
from og.eval.gold import textdoc_sha256
from og.store.db import connect

DOCS = {"b0": BASE, "x1": CO}
CATS = ("price", "dates", "termination", "guarantee", "sla", "parties_or_sites")
SUP_NEW = "Section 7.2 of the Lease is hereby deleted and replaced"
OLD_SELF = "Currently Tenant is scheduled to surrender on June 30, 2018."
UNRES_NEW = "Section 2.C of 2A is hereby deleted in its entirety."


def gold_dict(**over):
    g = {
        "change_order_id": "x1",
        "chain": ["b0", "x1"],
        "textdoc_sha256": {k: textdoc_sha256(v) for k, v in DOCS.items()},
        "provenance": {"drafted_by": "m", "adjudicated_by": "c", "spot_checked": 12},
        "scope": "full_agreement",
        "gates": {
            "price": {"answer": True, "segment_ids": ["p0002"]},
            "dates": {"answer": True, "segment_ids": ["p0003"]},
            "termination": {"answer": True, "segment_ids": ["p0004"]},
            "guarantee": {"answer": False, "segment_ids": []},
            "sla": {"answer": False, "segment_ids": []},
            "parties_or_sites": {"answer": True, "segment_ids": ["p0002"]},
        },
        "findings": [
            {
                "kind": "supersedes",
                "new_segment_id": "p0002",
                "new_span_text": SUP_NEW,
                "old_origin": "chain",
                "old_doc": "b0",
                "old_segment_id": "p0002",
                "old_span_text": BASE_RENT,
                "target_label": "Section 7.2 of the Original Lease",
                "old_value": None,
                "new_value": None,
                "delta": None,
                "currency": None,
            },
            {
                "kind": "shifted_date",
                "new_segment_id": "p0003",
                "new_span_text": CO_SURRENDER,
                "old_origin": "self",
                "old_doc": None,
                "old_segment_id": "p0003",
                "old_span_text": OLD_SELF,
                "target_label": None,
                "old_value": "2018-06-30",
                "new_value": "2020-06-30",
                "delta": "731",
                "currency": None,
            },
            {
                "kind": "supersedes",
                "new_segment_id": "p0004",
                "new_span_text": UNRES_NEW,
                "old_origin": "unresolved",
                "old_doc": None,
                "old_segment_id": None,
                "old_span_text": None,
                "target_label": "section  2.C OF 2a",
                "old_value": None,
                "new_value": None,
                "delta": None,
                "currency": None,
            },
            {
                "kind": "price_change",
                "new_segment_id": "p0002",
                "new_span_text": "$12,000",
                "old_origin": "unresolved",
                "old_doc": None,
                "old_segment_id": None,
                "old_span_text": None,
                "target_label": None,
                "old_value": None,
                "new_value": "12000.00",
                "delta": None,
                "currency": "USD",
            },
        ],
    }
    g.update(over)
    return g


def write_gold(tmp_path, g):
    path = tmp_path / "x1.yaml"
    path.write_text(yaml.safe_dump(g, allow_unicode=True), encoding="utf-8")
    return path


# --- DB state through the schema contract -----------------------------------------------------


def ref(con, doc, quote):
    e = ev(doc, quote)
    return con.execute(
        "INSERT INTO clause_ref(agreement_id,section,page,char_start,char_end,span_text,grounded)"
        " VALUES(?,?,?,?,?,?,1)",
        (doc.doc_id, e.section_number, e.page, e.char_start, e.char_end, e.span_text),
    ).lastrowid


def setup_db(path, *, gated_baseline="U", gated_pair="P", sla_conflict=True):
    con = connect(path)
    for agr, doc in DOCS.items():
        con.execute(
            "INSERT INTO source(id,url,local_path,sha256) VALUES(?,'u','p',?)",
            (agr, doc.source_sha256),
        )
        con.execute(
            "INSERT INTO agreement(id,title,type,source_id) VALUES(?,?,'lease',?)", (agr, agr, agr)
        )
        con.execute(
            "INSERT INTO extraction_run(run_id,source_id,prompt_version,model,textdoc_sha256)"
            " VALUES(?,?,'v1','m',?)",
            (f"er-{agr}", agr, textdoc_sha256(doc)),
        )
    run_ids = {}
    for mode, run_id, baseline, pair, cost, inc, lat in (
        ("ungated", "U", None, "P", 0.60, 0.60, 9000),
        ("gated", "G", gated_baseline, gated_pair, 0.45, 0.004, 2000),
    ):
        rid = con.execute(
            "INSERT INTO change_run(run_id,pair_id,change_order_id,mode,prompt_version,"
            "question_set_sha256,model,baseline_run_id,chain_size,cost_usd,"
            "incremental_cost_usd,latency_ms,completed_at)"
            " VALUES(?,?,'x1',?,'change_v1@x','q','claude-sonnet-5-5',?,2,?,?,?,datetime('now'))",
            (run_id, pair, mode, baseline, cost, inc, lat),
        ).lastrowid
        run_ids[mode] = rid
        for pos, (agr, role) in enumerate((("b0", "base"), ("x1", "change_order"))):
            con.execute(
                "INSERT INTO change_run_chain(change_run_id,position,agreement_id,role,"
                "textdoc_sha256,extraction_run_id) VALUES(?,?,?,?,?,?)",
                (rid, pos, agr, role, textdoc_sha256(DOCS[agr]), f"er-{agr}"),
            )

    def add(mode, kind, category, new_quote, old=None, origin=None, label=None, **vals):
        old_ref = ref(con, old[0], old[1]) if old else None
        origin = origin or ("unresolved" if old is None else "chain")
        con.execute(
            "INSERT INTO change_finding(change_run_id,kind,category,new_clause_ref_id,"
            "old_clause_ref_id,old_origin,target_label,old_value,new_value,delta,currency)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_ids[mode],
                kind,
                category,
                ref(con, CO, new_quote),
                old_ref,
                origin,
                label,
                vals.get("old_value"),
                vals.get("new_value"),
                vals.get("delta"),
                vals.get("currency"),
            ),
        )

    shift_vals = dict(old_value="2018-06-30", new_value="2020-06-30", delta="731")
    for mode in ("ungated", "gated"):
        add(
            mode,
            "supersedes",
            "price",
            SUP_NEW,
            old=(BASE, BASE_RENT),
            label="Section 7.2 of the Lease",
        )
        add(
            mode,
            "shifted_date",
            "dates",
            CO_SURRENDER,
            old=(CO, OLD_SELF),
            origin="self",
            **shift_vals,
        )
        # The same shift, also proposed by the termination check: one finding, two categories.
        add(
            mode,
            "shifted_date",
            "termination",
            CO_SURRENDER,
            old=(CO, OLD_SELF),
            origin="self",
            **shift_vals,
        )
        add(mode, "supersedes", "termination", UNRES_NEW, label="Section 2.C of 2A")
    if sla_conflict:  # only the ungated run checked sla (the gated run skipped it)
        add("ungated", "potential_conflict", "sla", CO_INSTALL, old=(BASE, BASE_COOLING))

    def decide(mode, cat, backend, tier, answer, conf, samples, run_check, cost=0.0):
        con.execute(
            "INSERT INTO gate_decision(change_run_id,change_order_id,question,backend,tier,"
            "answer,confidence,samples_json,evidence_json,run_check,cost_usd)"
            " VALUES(?,'x1',?,?,?,?,?,?,'[]',?,?)",
            (
                run_ids[mode],
                f"touches_{cat}",
                backend,
                tier,
                answer,
                conf,
                json.dumps(samples),
                run_check,
                cost,
            ),
        )

    hits = {"price", "dates", "termination"}
    for cat in CATS:  # ungated records the rules tier only
        hit = cat in hits
        decide("ungated", cat, "rules", "rules", 1 if hit else 0, 1.0 if hit else None, [], 1)
    haiku = {
        "guarantee": [False, False, False],
        "sla": [False, False, False],
        "parties_or_sites": [True, False, False],
    }
    for cat in CATS:
        if cat in hits:
            decide("gated", cat, "rules", "rules", 1, 1.0, [], 1)
        else:
            s = haiku[cat]
            skip = s == [False, False, False]
            conf = max(s.count(True), s.count(False)) / 3
            decide("gated", cat, "haiku", "classifier", 0, conf, s, 0 if skip else 1, cost=0.001)
    con.close()
    return path


@pytest.fixture
def scored(tmp_path):
    db = setup_db(tmp_path / "g.db")
    gold = load_change_gold(write_gold(tmp_path, gold_dict()), DOCS)
    return score_change(connect(db), gold)


# --- gold loading -------------------------------------------------------------------------------


def test_gold_loads(tmp_path):
    gold = load_change_gold(write_gold(tmp_path, gold_dict()), DOCS)
    assert gold.change_order_id == "x1"
    assert len(gold.findings) == 4
    assert gold.gates["sla"] is False and gold.gates["price"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda g: g["findings"][0].update(new_span_text="not in the segment"),
        lambda g: g["findings"][0].update(old_span_text="not in the base segment"),
        lambda g: g["findings"][1].update(old_segment_id="p0099"),
        lambda g: g["findings"][2].update(target_label=None),
        lambda g: g["findings"][0].update(old_doc="x1"),
        lambda g: g["findings"][0].update(kind="conflict"),
        lambda g: g["gates"].pop("sla"),
        lambda g: g["textdoc_sha256"].update(b0="0" * 64),
    ],
    ids=[
        "new_span",
        "old_span",
        "old_segment",
        "unresolved_needs_label",
        "chain_old_doc_must_be_earlier",
        "kind",
        "missing_gate",
        "textdoc_pin",
    ],
)
def test_gold_validation(tmp_path, mutate):
    g = gold_dict()
    mutate(g)
    with pytest.raises(ValueError):
        load_change_gold(write_gold(tmp_path, g), DOCS)


# --- findings (rev 2 R9) ------------------------------------------------------------------------


def test_finding_recall_and_precision(scored):
    u = scored["findings"]["ungated"]
    assert (u["overall"]["tp"], u["overall"]["fp"], u["overall"]["fn"]) == (3, 1, 1)
    assert u["overall"]["precision"] == pytest.approx(0.75)
    assert u["overall"]["recall"] == pytest.approx(0.75)
    per = u["per_kind"]
    assert (per["supersedes"]["tp"], per["supersedes"]["fn"]) == (2, 0)
    assert per["shifted_date"]["tp"] == 1
    assert per["price_change"]["fn"] == 1
    assert per["potential_conflict"]["fp"] == 1
    g = scored["findings"]["gated"]
    assert (g["overall"]["tp"], g["overall"]["fp"], g["overall"]["fn"]) == (3, 0, 1)


def test_cross_category_duplicates_count_once(scored):
    assert scored["findings"]["ungated"]["overall"]["predicted"] == 4


def test_finding_retention_recall(scored):
    """Gated keeps 3 of the 4 ungated (deduplicated) findings: the sla conflict was skipped."""
    assert scored["findings"]["retention_recall"] == pytest.approx(0.75)


def test_value_accuracy_reported_separately(scored):
    v = scored["values"]
    assert v["delta"] == {"gold": 1, "coverage": 1.0, "accuracy": 1.0}
    assert v["old_value"] == {"gold": 1, "coverage": 1.0, "accuracy": 1.0}
    # Chain matches do not require labels, but label accuracy is still reported:
    # "Section 7.2 of the Lease" vs "Section 7.2 of the Original Lease" is wrong.
    assert v["target_label"] == {"gold": 2, "coverage": 1.0, "accuracy": 0.5}
    assert v["currency"] == {"gold": 0, "coverage": None, "accuracy": None}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda g: g["findings"][0].update(old_segment_id="p0003", old_span_text="Tenant shall pay"),
        lambda g: g["findings"][0].update(new_segment_id="p0003", new_span_text=CO_SURRENDER),
        lambda g: g["findings"][2].update(target_label="Section 2.D of 2A"),
        lambda g: g["findings"][1].update(
            old_origin="chain",
            old_doc="b0",
            old_segment_id="p0004",
            old_span_text="Tenant shall surrender the Premises",
        ),
        lambda g: g["findings"][0].update(kind="potential_conflict"),
    ],
    ids=["chain_old_segment", "new_segment", "unresolved_label", "origin", "kind"],
)
def test_matching_requires_identity(tmp_path, mutate):
    db = setup_db(tmp_path / "g.db")
    g = gold_dict()
    mutate(g)
    out = score_change(connect(db), load_change_gold(write_gold(tmp_path, g), DOCS))
    assert out["findings"]["ungated"]["overall"]["tp"] == 2


def test_unresolved_label_normalization_ignores_case_and_whitespace(tmp_path):
    db = setup_db(tmp_path / "g.db")
    g = gold_dict()
    g["findings"][2]["target_label"] = "section 2.C\u00a0of\n2A"
    out = score_change(connect(db), load_change_gold(write_gold(tmp_path, g), DOCS))
    assert out["findings"]["ungated"]["overall"]["tp"] == 3


# --- gates (rev 2 R8) ---------------------------------------------------------------------------


def test_cascade_against_reference_and_baseline(scored):
    c = scored["gates"]["cascade"]
    ref = c["vs_reference"]
    assert (ref["positives"], ref["misses"], ref["recall"], ref["precision"]) == (4, 0, 1.0, 1.0)
    assert ref["skipped"] == 2 and ref["skip_rate"] == pytest.approx(2 / 6)
    assert ref["miss_upper_95"] == pytest.approx(0.527, abs=1e-3)
    base = c["vs_baseline"]
    assert (base["positives"], base["misses"]) == (4, 1)
    assert base["recall"] == pytest.approx(0.75)
    assert base["precision"] == pytest.approx(0.75)
    assert base["miss_upper_95"] == pytest.approx(0.751, abs=1e-3)


def test_rules_only_backend(scored):
    r = scored["gates"]["rules"]
    assert (r["vs_reference"]["misses"], r["vs_reference"]["recall"]) == (1, 0.75)
    assert r["vs_reference"]["precision"] == 1.0
    assert r["vs_baseline"]["recall"] == 0.75


def test_haiku_is_reported_on_its_observed_subset(scored):
    h = scored["gates"]["haiku"]
    assert h["observed"] == ["guarantee", "parties_or_sites", "sla"]
    assert h["coverage"] == pytest.approx(0.5)
    assert (h["vs_reference"]["positives"], h["vs_reference"]["misses"]) == (1, 1)
    assert h["vs_reference"]["recall"] == 0.0
    assert (h["vs_baseline"]["positives"], h["vs_baseline"]["misses"]) == (1, 1)


def test_haiku_recall_is_null_without_positives(tmp_path):
    db = setup_db(tmp_path / "g.db", sla_conflict=False)
    g = gold_dict()
    g["gates"]["parties_or_sites"] = {"answer": False, "segment_ids": []}
    out = score_change(connect(db), load_change_gold(write_gold(tmp_path, g), DOCS))
    h = out["gates"]["haiku"]
    for side in ("vs_reference", "vs_baseline"):
        assert h[side]["positives"] == 0
        assert h[side]["recall"] is None
        assert h[side]["miss_upper_95"] is None


def test_skips_are_named_honestly(scored):
    assert sorted((s["category"], s["kind"]) for s in scored["skips"]) == [
        ("guarantee", "confirmed_safe_skip"),
        ("sla", "baseline_miss"),
    ]


def test_zero_baseline_skip_that_the_reference_calls_positive(tmp_path):
    db = setup_db(tmp_path / "g.db", sla_conflict=False)
    g = gold_dict()
    g["gates"]["sla"] = {"answer": True, "segment_ids": ["p0005"]}
    out = score_change(connect(db), load_change_gold(write_gold(tmp_path, g), DOCS))
    kinds = {s["category"]: s["kind"] for s in out["skips"]}
    assert kinds == {"guarantee": "confirmed_safe_skip", "sla": "zero_baseline_skip"}


def test_disagreements_are_listed(scored):
    d = {(x["backend"], x["category"]) for x in scored["disagreements"]}
    # The rules tier missed parties_or_sites; haiku answered no on parties_or_sites.
    assert ("rules", "parties_or_sites") in d
    assert ("haiku", "parties_or_sites") in d
    assert ("cascade", "sla") not in d  # the cascade agrees with the reference on sla


@pytest.mark.parametrize(
    "k,n,expected",
    [(0, 9, 0.283), (1, 9, 0.429), (0, 4, 0.527), (1, 4, 0.751), (0, 1, 0.95), (1, 1, 1.0)],
)
def test_clopper_pearson_one_sided_upper(k, n, expected):
    assert clopper_pearson_upper(k, n) == pytest.approx(expected, abs=1e-3)


def test_clopper_pearson_without_cases_is_null():
    assert clopper_pearson_upper(0, 0) is None


# --- cost, pairing, CLI ---------------------------------------------------------------------------


def test_cost_and_latency_both_modes(scored):
    c = scored["cost"]
    assert c["ungated"] == {"cost_usd": 0.60, "incremental_cost_usd": 0.60, "latency_ms": 9000}
    assert c["gated"] == {"cost_usd": 0.45, "incremental_cost_usd": 0.004, "latency_ms": 2000}
    assert c["gate_cost_usd"] == pytest.approx(0.003)
    assert "replay" in c["note"]


@pytest.mark.parametrize(
    "kw", [{"gated_baseline": "OTHER"}, {"gated_pair": "Q"}], ids=["baseline", "pair"]
)
def test_unmatched_pair_is_refused(tmp_path, kw):
    db = setup_db(tmp_path / "g.db", **kw)
    gold = load_change_gold(write_gold(tmp_path, gold_dict()), DOCS)
    with pytest.raises(ValueError, match="unmatched_pair"):
        score_change(connect(db), gold)


def test_cli_change_subcommand(tmp_path):
    db = setup_db(tmp_path / "g.db")
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    for agr, doc in DOCS.items():
        doc.save(text_dir / f"{agr}.json")
    out = tmp_path / "out.json"
    gold = write_gold(tmp_path, gold_dict())
    argv = ["change", "--doc", "x1", "--db", str(db), "--gold", str(gold)]
    argv += ["--text-dir", str(text_dir), "--out", str(out)]
    assert eval_main(argv) == 0
    res = json.loads(out.read_text(encoding="utf-8"))
    assert res["metric"] == "change"
    assert res["change_order_id"] == "x1"
    assert res["pair_id"] == "P"
    assert res["findings"]["ungated"]["overall"]["tp"] == 3
    assert res["gates"]["cascade"]["vs_reference"]["recall"] == 1.0


def test_cli_extract_subcommand_still_parses(tmp_path):
    """Adding `change` must not break the existing `extract` subcommand's argument parsing."""
    with pytest.raises(SystemExit) as exc:
        eval_main(["extract", "--help"])
    assert exc.value.code == 0
