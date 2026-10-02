"""Wave 5 Task 43: timing reference labels and the timing scorer (plan rev 2 W5-9).

THE TIMING REFERENCE FILE SHAPE BELOW IS THE CONTRACT FOR C14
(eval/gold/timing/<name>.yaml):

  version: timing_gold_v1
  name: <str>                        # e.g. "reference" (50 CC 2011 items) or "challenge"
  documents: {<agreement_id>: <canonical TextDoc sha256>, ...}   # every agreement used
  provenance: {drafted_by: str, adjudicated_by: str, spot_checked: int}
  scope: sampled
  items:
    - agreement_id: <agreement id>
      segment_id: <segment containing the obligation quote>
      span_text: <the obligation quote, an exact substring of that segment>
      timing_kind: scheduled | contingent | unresolved | untimed
      relation: lt | lte | eq | gte | gt | null
      bound_date: <ISO date>         # required iff timing_kind == scheduled, else null
      anchor:                         # null, or the cited declaration of the anchor date
        name: <defined term>
        agreement_id: <agreement id>  # the obligation's agreement or its recorded base
        segment_id: <segment>
        span_text: <exact substring of that segment>
      offset_days: <int or null>
      offset_unit: calendar | business | hours | months | null
      trigger_span_text: <exact substring of span_text, or null>
      reason: <og.timing.UNRESOLVED_REASONS value>   # required iff timing_kind == unresolved

og.eval.timing_gold.load_timing_gold(path, docs) validates every span exactly (span_text
inside its segment; trigger_span_text inside span_text; anchor span inside its segment),
the document hashes, the enums, and the iff rules, raising ValueError on any violation.
It returns an object with `.name` and `.items`; each item exposes agreement_id,
char_start, char_end (absolute offsets of the quote), and the labeled fields.

og.eval.timing_score.score_timing(con, gold) matches each labeled item to at most one
visible obligation of the same agreement whose grounded extraction citation has
IoU >= 0.3 with the labeled quote (maximum-cardinality matching, as the extraction
scorer; type is not part of a timing label). Predictions come only from the read
projections (visible_obligation, visible_obligation_clause, visible_obligation_timing);
an obligation with no visible timing row predicts "untimed". It returns:

  {name, labeled, matched, missing: [{agreement_id, segment_id}],
   timing_kind: {correct, denominator, accuracy},    # over matched
   relation:    {correct, denominator, accuracy},    # matched with a labeled relation
   bound_date:  {correct, denominator, accuracy, invented},
                # denominator: matched with a labeled bound; invented: matched with no
                # labeled bound but a predicted one (a date the reference does not support)
   trigger:     {matched, denominator, rate},        # IoU >= 0.5 of predicted vs labeled
                                                     # trigger span, over matched with a
                                                     # labeled trigger
   reason:      {correct, denominator, accuracy},    # matched labeled unresolved
   confusion:   {<labeled kind>: {<predicted kind>: n}}}

accuracy/rate is null when the denominator is 0. Bound-date metrics never read the legacy
`due_date` field.

The results manifest gains an optional "timing" list:
  "timing": [{"name": <str>, "gold": <workspace-relative path>, "gold_sha256": <sha256>}]
and the aggregate gains "timing": {<name>: <score_timing dict>}; readme-tables renders a
"### Timing" section with one row per named set.
"""

import hashlib
import json
import shutil
import sqlite3

import pytest
import yaml
from eval_workspace import build
from test_query_invariant import _sql_identifiers
from timing_fixture import BASE, obligation_quote, textdoc, timed_v5

from og.eval.__main__ import main
from og.eval.gold import textdoc_sha256
from og.eval.readme import render_tables
from og.query import READ_ALLOWLIST

APPLIED = "applieddigital-2026-ex101"
CARBONITE = "carbonite-2014-ex1024"
A1 = "constantcontact-2012-ex101"
A3 = "endurance-2017-ex106"
TERAWULF = "terawulf-2025-ex10-1"


def segment_of(doc, start, end):
    for seg in doc.segments:
        if seg.char_start <= start and end <= seg.char_end:
            return seg
    raise AssertionError(f"no single segment holds [{start}, {end})")


def item(con, oid, **labels):
    agreement_id, start, end, quote = obligation_quote(con, oid)
    seg = segment_of(textdoc(agreement_id), start, end)
    base = {
        "agreement_id": agreement_id,
        "segment_id": seg.id,
        "span_text": quote,
        "timing_kind": "untimed",
        "relation": None,
        "bound_date": None,
        "anchor": None,
        "offset_days": None,
        "offset_unit": None,
        "trigger_span_text": None,
        "reason": None,
    }
    base.update(labels)
    return base


def base_cd_anchor():
    doc = textdoc(BASE)
    seg = segment_of(doc, 44806, 44806 + len("(b) Commencement Date:"))
    return {
        "name": "Commencement Date",
        "agreement_id": BASE,
        "segment_id": seg.id,
        "span_text": "Commencement Date",
    }


def missing_item():
    """A label on a segment where no obligation was extracted (the filing header)."""
    doc = textdoc(BASE)
    seg = doc.segments[0]
    text = doc.text[seg.char_start : seg.char_end]
    return {
        "agreement_id": BASE,
        "segment_id": seg.id,
        "span_text": text[: min(20, len(text))],
        "timing_kind": "untimed",
        "relation": None,
        "bound_date": None,
        "anchor": None,
        "offset_days": None,
        "offset_unit": None,
        "trigger_span_text": None,
        "reason": None,
    }


def gold_dict(con):
    items = [
        item(
            con,
            62,
            timing_kind="scheduled",
            relation="lt",
            bound_date="2011-01-01",
            anchor=base_cd_anchor(),
            trigger_span_text="prior to the Commencement Date",
        ),
        item(
            con,
            14,
            timing_kind="contingent",
            relation="lte",
            offset_days=15,
            offset_unit="calendar",
            trigger_span_text=(
                "within fifteen (15) days after the receipt of a correct, itemized invoice"
            ),
        ),
        # Labeled relation differs from the prediction (lte): one relation miss.
        item(
            con,
            57,
            timing_kind="contingent",
            relation="lt",
            offset_days=30,
            offset_unit="calendar",
            trigger_span_text="no later than thirty (30) days following receipt of an invoice",
        ),
        # A narrower labeled trigger still overlaps the prediction with IoU >= 0.5.
        item(
            con,
            159,
            timing_kind="unresolved",
            relation="lte",
            offset_days=10,
            offset_unit="business",
            trigger_span_text="ten (10) business days after the Effective Date",
            reason="business_days",
        ),
        item(con, 34),
        item(
            con,
            490,
            timing_kind="unresolved",
            relation="lte",
            trigger_span_text="within [***] days after the occurrence thereof",
            reason="redacted_offset",
        ),
        # The reference withholds a date the prediction schedules: kind miss, reason miss,
        # and one invented bound.
        item(con, 519, timing_kind="unresolved", reason="anchor_without_date"),
        missing_item(),
    ]
    agreements = {i["agreement_id"] for i in items} | {BASE}
    return {
        "version": "timing_gold_v1",
        "name": "reference",
        "documents": {a: textdoc_sha256(textdoc(a)) for a in sorted(agreements)},
        "provenance": {"drafted_by": "m", "adjudicated_by": "c", "spot_checked": 0},
        "scope": "sampled",
        "items": items,
    }


@pytest.fixture
def timed(tmp_path):
    path, ids = timed_v5(tmp_path / "graph.db")
    con = sqlite3.connect(path, isolation_level=None)
    yield con
    con.close()


def docs_for(gold):
    return {a: textdoc(a) for a in gold["documents"]}


def write_gold(path, gold):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(gold, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load(tmp_path, gold):
    from og.eval.timing_gold import load_timing_gold

    return load_timing_gold(write_gold(tmp_path / "timing.yaml", gold), docs_for(gold))


# ---------------------------------------------------------------- loader


def test_loader_resolves_absolute_offsets(timed, tmp_path):
    gold = load(tmp_path, gold_dict(timed))
    assert gold.name == "reference"
    assert len(gold.items) == 8
    first = gold.items[0]
    _agreement, start, end, quote = obligation_quote(timed, 62)
    assert (first.agreement_id, first.char_start, first.char_end) == (BASE, start, end)
    assert textdoc(BASE).text[first.char_start : first.char_end] == quote


@pytest.mark.parametrize(
    "mutate",
    [
        lambda g: g["items"][0].update(span_text=g["items"][0]["span_text"] + " extra"),
        lambda g: g["items"][1].update(trigger_span_text="within sixteen (16) days"),
        lambda g: g["items"][0]["anchor"].update(span_text="Completion Date"),
        lambda g: g["items"][1].update(bound_date="2011-01-01"),
        lambda g: g["items"][0].update(bound_date=None),
        lambda g: g["items"][3].update(reason=None),
        lambda g: g["items"][4].update(reason="business_days"),
        lambda g: g["items"][0].update(timing_kind="overdue"),
        lambda g: g["items"][0].update(relation="before"),
        lambda g: g["documents"].update({BASE: "0" * 64}),
    ],
    ids=[
        "span_not_in_segment",
        "trigger_not_in_span",
        "anchor_not_in_segment",
        "bound_on_non_scheduled",
        "scheduled_without_bound",
        "unresolved_without_reason",
        "reason_on_untimed",
        "bad_kind",
        "bad_relation",
        "textdoc_hash_mismatch",
    ],
)
def test_loader_rejects_invalid_labels(timed, tmp_path, mutate):
    gold = gold_dict(timed)
    mutate(gold)
    with pytest.raises(ValueError):
        load(tmp_path, gold)


# ---------------------------------------------------------------- scorer


@pytest.fixture
def scored(timed, tmp_path):
    from og.eval.timing_score import score_timing

    return score_timing(timed, load(tmp_path, gold_dict(timed)))


def test_denominators_and_missing(scored):
    assert scored["name"] == "reference"
    assert scored["labeled"] == 8
    assert scored["matched"] == 7
    assert len(scored["missing"]) == 1
    assert scored["missing"][0]["agreement_id"] == BASE


def test_kind_accuracy_and_confusion(scored):
    assert scored["timing_kind"] == {
        "correct": 6,
        "denominator": 7,
        "accuracy": pytest.approx(6 / 7),
    }
    assert scored["confusion"]["unresolved"]["scheduled"] == 1
    assert scored["confusion"]["scheduled"]["scheduled"] == 1
    assert scored["confusion"]["untimed"]["untimed"] == 1


def test_relation_accuracy(scored):
    assert scored["relation"] == {"correct": 4, "denominator": 5, "accuracy": pytest.approx(0.8)}


def test_bound_date_is_scored_separately_and_invented_dates_are_counted(scored):
    assert scored["bound_date"]["correct"] == 1
    assert scored["bound_date"]["denominator"] == 1
    assert scored["bound_date"]["accuracy"] == pytest.approx(1.0)
    assert scored["bound_date"]["invented"] == 1


def test_trigger_span_match(scored):
    assert scored["trigger"] == {"matched": 5, "denominator": 5, "rate": pytest.approx(1.0)}


def test_reason_accuracy(scored):
    assert scored["reason"] == {"correct": 2, "denominator": 3, "accuracy": pytest.approx(2 / 3)}


def test_empty_denominator_gives_null(timed, tmp_path):
    from og.eval.timing_score import score_timing

    gold = gold_dict(timed)
    gold["items"] = [i for i in gold["items"] if i["timing_kind"] == "untimed"]
    out = score_timing(timed, load(tmp_path, gold))
    assert out["bound_date"]["denominator"] == 0
    assert out["bound_date"]["accuracy"] is None
    assert out["reason"]["accuracy"] is None
    assert out["trigger"]["rate"] is None


def test_scorer_reads_only_allowlisted_sources():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "src" / "og" / "eval" / "timing_score.py"
    assert _sql_identifiers(path, None) <= READ_ALLOWLIST


# ---------------------------------------------------------------- aggregate + README


@pytest.fixture
def agg_ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OG_WORKSPACE", str(tmp_path))
    info = build(tmp_path)
    timed_v5(tmp_path / "graph.v5.db")
    shutil.copy(tmp_path / "graph.v5.db", tmp_path / "data" / "graph.db")
    con = sqlite3.connect(tmp_path / "data" / "graph.db")
    gold = gold_dict(con)
    con.close()
    rel = "eval/gold/timing/reference.yaml"
    path = write_gold(tmp_path / rel, gold)
    manifest = json.loads(info["manifest"].read_text(encoding="utf-8"))
    manifest["timing"] = [
        {
            "name": "reference",
            "gold": rel,
            "gold_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    ]
    info["manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    info["root"] = tmp_path
    return info


def run_all(ws):
    out = ws["root"] / "agg.json"
    rc = main(["all", "--manifest", str(ws["manifest"]), "--out", str(out)])
    return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


def test_aggregate_gains_a_timing_block(agg_ws):
    rc, agg = run_all(agg_ws)
    assert rc == 0
    block = agg["timing"]["reference"]
    assert block["labeled"] == 8 and block["matched"] == 7
    assert block["timing_kind"]["correct"] == 6
    text = render_tables(agg)
    assert "### Timing" in text
    assert "reference" in text


def test_aggregate_without_timing_entries_has_no_timing_section(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OG_WORKSPACE", str(tmp_path))
    info = build(tmp_path)
    timed_v5(tmp_path / "graph.v5.db")
    shutil.copy(tmp_path / "graph.v5.db", tmp_path / "data" / "graph.db")
    info["root"] = tmp_path
    rc, agg = run_all(info)
    assert rc == 0
    assert agg.get("timing", {}) == {}
    assert "### Timing" not in render_tables(agg)


def test_timing_gold_sha_mismatch_is_refused(agg_ws, capsys):
    manifest = json.loads(agg_ws["manifest"].read_text(encoding="utf-8"))
    manifest["timing"][0]["gold_sha256"] = "0" * 64
    agg_ws["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
    rc, _ = run_all(agg_ws)
    assert rc == 2
    assert "gold_sha_mismatch" in capsys.readouterr().err
