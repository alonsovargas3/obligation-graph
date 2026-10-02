"""The fail-open gate cascade (wave 3 Task 15; plan rev 2 R5).

For each of the six questions: the deterministic rules tier runs first. A
rules hit returns the rules decision and the classifier is never called.
Otherwise the classifier tier decides, and its decision can skip the check
only under the pre-registered policy: an error-free, unanimous three-sample
"no" from the classifier tier. Anything else (an exception, a malformed
decision object, a missing backend, any error, any dissent, anything but
three literal ``False`` samples) runs the check. A gate may skip work; it may
never suppress a finding.

Wave 4 (rev 2.2): ``og.replay.ReplayMiss`` is the one exception that is
re-raised instead of failing open, so ``OG_REPLAY=strict`` surfaces a missing
recorded response as an error rather than silently paying for a live call.
"""

from __future__ import annotations

from dataclasses import replace

from ..change.types import CATEGORIES
from ..replay import ReplayMiss
from ..textdoc import TextDoc
from .types import GATE_POLICY, GateContext, GateDecision, Question


def _is_unanimous_skip(decision: GateDecision) -> bool:
    """The pre-registered skip policy: ``GATE_POLICY["skip"] == "unanimous_false"``.

    Requires exactly ``GATE_POLICY["samples"]`` literal ``False`` samples (so
    ``0`` and a one-element list of ``False`` both fail), no error, the
    classifier tier, and an answer/confidence consistent with them.
    """
    samples = decision.samples
    return bool(
        decision.tier == "classifier"
        and decision.error is None
        and decision.answer is False
        and decision.confidence == 1.0
        and type(samples) is tuple
        and len(samples) == GATE_POLICY["samples"]
        and all(sample is False for sample in samples)
    )


def _fail_open(question: Question, *, backend: str, tier: str, error: str) -> GateDecision:
    return GateDecision(
        question=question.id,
        backend=backend,
        tier=tier,
        answer=None,
        confidence=None,
        samples=(),
        evidence=(),
        latency_ms=0,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        error=error,
        run_check=True,
    )


def _backend_name(gate: object, default: str) -> str:
    name = getattr(gate, "name", None)
    return name if isinstance(name, str) else default


def run_cascade(
    questions, change_order: TextDoc, context: GateContext, rules, classifier
) -> list[GateDecision]:
    """One decision per question, cheapest tier first, failing open.

    ``questions`` must cover exactly the six unique categories; anything else
    raises ``ValueError`` before either tier is called. The returned decisions
    are in question order, one per question.
    """
    questions = list(questions)
    categories = sorted(q.category for q in questions)
    if categories != sorted(CATEGORIES):
        raise ValueError(
            f"question set must be exactly the six categories {sorted(CATEGORIES)}, "
            f"got {categories}"
        )

    decisions: list[GateDecision] = []
    for question in questions:
        rules_backend = _backend_name(rules, "rules")
        try:
            rules_decision = rules.decide(question, change_order, context)
        except ReplayMiss:
            raise
        except Exception as exc:
            decisions.append(
                _fail_open(question, backend=rules_backend, tier="rules", error=type(exc).__name__)
            )
            continue
        if not isinstance(rules_decision, GateDecision):
            decisions.append(
                _fail_open(question, backend=rules_backend, tier="rules", error="exception")
            )
            continue
        if rules_decision.answer is True:
            # A rules hit answers yes without a model call; the rules tier
            # never decides a skip, so its hit always runs the check.
            decisions.append(rules_decision)
            continue

        if classifier is None:
            decisions.append(_fail_open_classifier_absent(question))
            continue
        classifier_backend = _backend_name(classifier, "classifier")
        try:
            decision = classifier.decide(question, change_order, context)
        except ReplayMiss:
            raise
        except Exception as exc:
            decisions.append(
                _fail_open(
                    question,
                    backend=classifier_backend,
                    tier="classifier",
                    error=type(exc).__name__,
                )
            )
            continue
        if not isinstance(decision, GateDecision):
            decisions.append(
                _fail_open(
                    question, backend=classifier_backend, tier="classifier", error="exception"
                )
            )
            continue
        decisions.append(replace(decision, run_check=not _is_unanimous_skip(decision)))
    return decisions


def _fail_open_classifier_absent(question: Question) -> GateDecision:
    return GateDecision(
        question=question.id,
        backend="none",
        tier="none",
        answer=None,
        confidence=None,
        samples=(),
        evidence=(),
        latency_ms=0,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        error=None,
        run_check=True,
    )
