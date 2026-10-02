"""RulesGate, the deterministic gate tier (wave 3 Task 14; plan rev 2 R10).

Runs on the REAL First Amendment (1A) and Third Amendment (3A) TextDocs. The
expected hit-segment counts reproduce the Astra wave-3 round-2 walkthrough table
and were independently recomputed by the coordinator from the frozen lexicons.
The GateContext mappings are SYNTHETIC except where noted: the real base graph
maps 8.3.1 -> {other} and 9.1.1 -> {other, notice}.
"""

import pytest
from change_fakes import A1_ID, A3_ID, real_doc

from og.gates.rules import RulesGate
from og.gates.types import GateContext, GateDecision, load_questions

QUESTIONS = {q.category: q for q in load_questions()}
EMPTY = GateContext(base_section_types={})
REAL_CTX = GateContext(
    base_section_types={"8.3.1": frozenset({"other"}), "9.1.1": frozenset({"other", "notice"})}
)

EXPECTED_HIT_SEGMENTS = {
    A1_ID: {
        "price": 5,
        "dates": 17,
        "termination": 3,
        "guarantee": 0,
        "sla": 10,
        "parties_or_sites": 39,
    },
    A3_ID: {
        "price": 3,
        "dates": 15,
        "termination": 3,
        "guarantee": 0,
        "sla": 0,
        "parties_or_sites": 10,
    },
}
SIGNATURE_BLOCK = {A1_ID: ("p0062", "p0084"), A3_ID: ("p0043", "p0057")}


@pytest.fixture(scope="module")
def docs():
    return {A1_ID: real_doc(A1_ID), A3_ID: real_doc(A3_ID)}


def decide(docs, doc_id, category, context=EMPTY):
    return RulesGate(list(QUESTIONS.values())).decide(QUESTIONS[category], docs[doc_id], context)


def seg_num(sid):
    return int(sid[1:])


def lexicon_segments(decision):
    return {e.segment_id for e in decision.evidence if e.rule.startswith("lexicon:")}


def test_name():
    assert RulesGate(list(QUESTIONS.values())).name == "rules"


@pytest.mark.parametrize(
    ("doc_id", "category"),
    [(d, c) for d in EXPECTED_HIT_SEGMENTS for c in EXPECTED_HIT_SEGMENTS[d]],
)
def test_lexicon_hit_segment_counts_on_real_amendments(docs, doc_id, category):
    decision = decide(docs, doc_id, category)
    assert isinstance(decision, GateDecision)
    assert len(lexicon_segments(decision)) == EXPECTED_HIT_SEGMENTS[doc_id][category]


@pytest.mark.parametrize("doc_id", [A1_ID, A3_ID])
@pytest.mark.parametrize("category", sorted(QUESTIONS))
def test_signature_block_never_cited(docs, doc_id, category):
    lo, hi = SIGNATURE_BLOCK[doc_id]
    for e in decide(docs, doc_id, category).evidence:
        assert not seg_num(lo) <= seg_num(e.segment_id) <= seg_num(hi), e


def test_exhibits_after_signatures_are_read(docs):
    """1A's SLA exhibit (Table A-1, p0105-p0113) follows its signature block."""
    segs = lexicon_segments(decide(docs, A1_ID, "sla"))
    assert "p0037" in segs  # 3. Service Levels
    assert {"p0105", "p0110", "p0111"} <= segs


@pytest.mark.parametrize("doc_id", [A1_ID, A3_ID])
@pytest.mark.parametrize("category", sorted(QUESTIONS))
def test_evidence_is_an_exact_slice_and_deduplicated(docs, doc_id, category):
    doc = docs[doc_id]
    decision = decide(docs, doc_id, category, REAL_CTX)
    keys = [(e.rule, e.char_start) for e in decision.evidence]
    assert len(keys) == len(set(keys))
    for e in decision.evidence:
        assert e.text == doc.text[e.char_start : e.char_end]
        seg = doc.segment(e.segment_id)
        assert seg.char_start <= e.char_start < e.char_end <= seg.char_end
        assert e.rule.startswith(("lexicon:", "section_ref:"))


def test_hit_decision_shape(docs):
    d = decide(docs, A3_ID, "price")
    assert (d.question, d.backend, d.tier) == ("touches_price", "rules", "rules")
    assert d.answer is True
    assert d.confidence == 1.0
    assert d.run_check is True
    assert d.error is None
    assert d.samples == ()
    assert (d.input_tokens, d.output_tokens) == (0, 0)
    assert d.cost_usd in (None, 0.0)
    assert any(e.rule == "lexicon:rent" for e in d.evidence)


@pytest.mark.parametrize(
    ("doc_id", "category"), [(A1_ID, "guarantee"), (A3_ID, "guarantee"), (A3_ID, "sla")]
)
def test_no_hit_never_decides_a_skip(docs, doc_id, category):
    d = decide(docs, doc_id, category, REAL_CTX)
    assert d.evidence == ()
    assert d.answer is False
    assert d.confidence is None
    assert d.run_check is True
    assert d.tier == "rules"


def section_refs(decision):
    return {e.rule for e in decision.evidence if e.rule.startswith("section_ref:")}


def test_real_section_references_map_to_actual_obligation_types(docs):
    """1A p0035: 'Section 8.3.1 and 9.1.1 of the Lease' (real base types)."""
    parties = decide(docs, A1_ID, "parties_or_sites", REAL_CTX)
    assert section_refs(parties) == {"section_ref:8.3.1->other", "section_ref:9.1.1->other"}
    for category in ("dates", "termination"):
        assert section_refs(decide(docs, A1_ID, category, REAL_CTX)) == {
            "section_ref:9.1.1->notice"
        }
    for category in ("sla", "guarantee", "price"):
        assert section_refs(decide(docs, A1_ID, category, REAL_CTX)) == set()
    for e in parties.evidence:
        if e.rule.startswith("section_ref:"):
            assert e.segment_id == "p0035"
            assert "of the Lease" in e.text


def test_section_ref_without_context_entry_is_not_a_hit(docs):
    assert section_refs(decide(docs, A1_ID, "parties_or_sites", EMPTY)) == set()


def test_reference_to_another_document_is_not_a_base_reference(docs):
    """3A cites 'Section 2.C of 2A', 'Sections 1.A and 1.B of 2A', 'Section 4 of 2A'."""
    ctx = GateContext(
        base_section_types={
            n: frozenset({"guarantee", "sla", "payment"}) for n in ("2.C", "1.A", "1.B", "4")
        }
    )
    for category in ("guarantee", "sla"):
        d = decide(docs, A3_ID, category, ctx)
        assert section_refs(d) == set()
        assert d.answer is False


def test_whole_word_matching_on_real_text(docs):
    """3A p0040 says 'electronic'; 1A says 'square feet' throughout."""
    assert "electronic" in docs[A3_ID].segment_text("p0040")
    assert not any(e.segment_id == "p0040" for e in decide(docs, A3_ID, "sla").evidence)
    feet = [s.id for s in docs[A1_ID].segments if "square feet" in docs[A1_ID].segment_text(s.id)]
    assert feet
    price_terms = {e.text.lower() for e in decide(docs, A1_ID, "price").evidence}
    assert "feet" not in price_terms


def test_prefix_wildcard_matches_to_word_end(docs):
    d = decide(docs, A3_ID, "dates")
    words = {e.text for e in d.evidence if e.rule == "lexicon:expir*"}
    assert "expiring" in {w.lower() for w in words}
