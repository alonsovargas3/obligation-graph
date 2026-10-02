"""Fail-open gate cascade (wave 3 Task 15; plan rev 2 R5, Review Focus 4).

The rules tier and classifier here are SYNTHETIC stand-ins (they return chosen
GateDecisions or raise), except the Review Focus 4 test, which drives the real
HaikuGate through the synthetic FakeAnthropic client. The change order is the
REAL Third Amendment (3A) TextDoc.
"""

from types import SimpleNamespace

import pytest
from change_fakes import A3_ID, HAIKU, FakeAnthropic, gate_message, real_doc

from og.budget import Budget
from og.change.types import CATEGORIES
from og.gates.cascade import run_cascade
from og.gates.haiku import HaikuGate
from og.gates.types import GateContext, GateDecision, GateEvidence, load_questions

QUESTIONS = load_questions()
BY_CAT = {q.category: q for q in QUESTIONS}
CTX = GateContext(base_section_types={})


@pytest.fixture(scope="module")
def a3():
    return real_doc(A3_ID)


def decision(
    question="touches_sla",
    *,
    backend="fake",
    tier="classifier",
    samples=(False,) * 3,
    answer=False,
    confidence=1.0,
    error=None,
    run_check=False,
    evidence=(),
):
    return GateDecision(
        question=question,
        backend=backend,
        tier=tier,
        answer=answer,
        confidence=confidence,
        samples=samples,
        evidence=evidence,
        latency_ms=1,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        error=error,
        run_check=run_check,
    )


class FakeRules:
    """SYNTHETIC rules tier: hits exactly the given categories."""

    name = "rules"

    def __init__(self, hits=(), raise_on=()):
        self.hits = set(hits)
        self.raise_on = set(raise_on)
        self.calls = []

    def decide(self, question, change_order, context):
        self.calls.append(question.category)
        if question.category in self.raise_on:
            raise RuntimeError("rules failed")
        if question.category in self.hits:
            ev = GateEvidence("lexicon:rent", "p0014", 0, 4, change_order.text[0:4])
            return decision(
                question.id,
                backend="rules",
                tier="rules",
                samples=(),
                answer=True,
                run_check=True,
                evidence=(ev,),
            )
        return decision(
            question.id,
            backend="rules",
            tier="rules",
            samples=(),
            answer=False,
            confidence=None,
            run_check=True,
        )


class FakeClassifier:
    """SYNTHETIC classifier: a per-category decision, other object, or exception."""

    name = "fake"

    def __init__(self, by_category=None, default=None):
        self.by_category = by_category or {}
        self.default = default
        self.calls = []

    def decide(self, question, change_order, context):
        self.calls.append(question.category)
        out = self.by_category.get(question.category, self.default)
        if isinstance(out, BaseException):
            raise out
        if callable(out):
            return out(question)
        return out


def unanimous_no(question):
    return decision(question.id)


def cascade(a3, rules, classifier, questions=QUESTIONS):
    return run_cascade(questions, a3, CTX, rules, classifier)


def test_one_decision_per_question_in_order(a3):
    out = cascade(a3, FakeRules(), FakeClassifier(default=unanimous_no))
    assert [d.question for d in out] == [q.id for q in QUESTIONS]
    assert {q.category for q in QUESTIONS} == set(CATEGORIES)


def test_unanimous_three_false_skips(a3):
    out = cascade(a3, FakeRules(), FakeClassifier(default=unanimous_no))
    assert all(d.run_check is False for d in out)
    assert all(d.tier == "classifier" for d in out)


@pytest.mark.parametrize(
    "samples",
    [
        (),
        (False,),
        (False, False),
        (0, 0, 0),
        (False, False, None),
        (False, False, True),
        (False,) * 4,
        [False] * 3,
    ],
    ids=["empty", "one", "two", "ints", "none", "one_yes", "four", "list"],
)
def test_anything_but_three_literal_false_runs(a3, samples):
    clf = FakeClassifier(
        by_category={"sla": lambda q: decision(q.id, samples=samples, run_check=False)},
        default=unanimous_no,
    )
    out = {d.question: d for d in cascade(a3, FakeRules(), clf)}
    assert out["touches_sla"].run_check is True
    assert out["touches_guarantee"].run_check is False


@pytest.mark.parametrize(
    "over",
    [
        dict(error="timeout"),
        dict(answer=True),
        dict(answer=None),
        dict(confidence=2 / 3),
        dict(confidence=None),
        dict(tier="rules"),
        dict(tier="none"),
    ],
)
def test_skip_requires_clean_classifier_decision(a3, over):
    clf = FakeClassifier(
        by_category={"sla": lambda q: decision(q.id, **over)}, default=unanimous_no
    )
    out = {d.question: d for d in cascade(a3, FakeRules(), clf)}
    assert out["touches_sla"].run_check is True


def test_rules_hit_short_circuits_classifier(a3):
    rules = FakeRules(hits={"price", "dates"})
    clf = FakeClassifier(default=unanimous_no)
    out = {d.question: d for d in cascade(a3, rules, clf)}
    assert "price" not in clf.calls and "dates" not in clf.calls
    assert out["touches_price"].tier == "rules"
    assert out["touches_price"].run_check is True
    assert out["touches_price"].answer is True
    assert sorted(clf.calls) == sorted(set(CATEGORIES) - {"price", "dates"})


def test_no_classifier_runs_every_check(a3):
    out = cascade(a3, FakeRules(), None)
    assert all(d.tier == "none" for d in out)
    assert all(d.run_check is True for d in out)
    assert all(d.answer is None for d in out)


def test_rules_exception_fails_open(a3):
    clf = FakeClassifier(default=unanimous_no)
    out = {d.question: d for d in cascade(a3, FakeRules(raise_on={"sla"}), clf)}
    assert out["touches_sla"].run_check is True
    assert out["touches_sla"].error == "RuntimeError"
    assert out["touches_guarantee"].run_check is False


def test_classifier_exception_fails_open(a3):
    clf = FakeClassifier(by_category={"sla": ValueError("bad")}, default=unanimous_no)
    out = {d.question: d for d in cascade(a3, FakeRules(), clf)}
    assert out["touches_sla"].run_check is True
    assert out["touches_sla"].error == "ValueError"
    assert out["touches_sla"].tier == "classifier"


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "no",
        {
            "samples": (False,) * 3,
            "error": None,
            "answer": False,
            "confidence": 1.0,
            "tier": "classifier",
        },
        SimpleNamespace(
            samples=(False,) * 3,
            error=None,
            answer=False,
            confidence=1.0,
            tier="classifier",
            run_check=False,
        ),
    ],
    ids=["none", "str", "dict", "namespace"],
)
def test_malformed_decision_runs_the_check(a3, bad):
    clf = FakeClassifier(by_category={"sla": lambda q: bad}, default=unanimous_no)
    out = {d.question: d for d in cascade(a3, FakeRules(), clf)}
    assert isinstance(out["touches_sla"], GateDecision)
    assert out["touches_sla"].run_check is True


@pytest.mark.parametrize(
    "questions",
    [
        QUESTIONS[:5],
        QUESTIONS + [QUESTIONS[0]],
        QUESTIONS[:5] + [QUESTIONS[0]],
        [],
    ],
    ids=["missing", "seven", "duplicate", "empty"],
)
def test_question_set_must_be_the_six_categories(a3, questions):
    rules, clf = FakeRules(), FakeClassifier(default=unanimous_no)
    with pytest.raises(ValueError):
        cascade(a3, rules, clf, questions=questions)
    assert rules.calls == [] and clf.calls == []


def test_review_focus_4_one_sample_times_out(a3):
    """Real HaikuGate: one of three samples times out, so the check runs and the error is logged."""
    client = FakeAnthropic(
        responses=[gate_message("no"), TimeoutError("read timed out"), gate_message("no")]
    )
    haiku = HaikuGate(client, HAIKU, Budget(limit_usd=None))
    only_sla = FakeRules(hits=set(CATEGORIES) - {"sla"})
    out = {d.question: d for d in run_cascade(QUESTIONS, a3, CTX, only_sla, haiku)}
    sla = out["touches_sla"]
    assert len(client.calls) == 3
    assert sla.samples == (False, None, False)
    assert sla.error == "timeout"
    assert sla.backend == "haiku"
    assert sla.run_check is True
