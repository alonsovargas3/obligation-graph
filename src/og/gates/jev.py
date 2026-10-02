"""JevGate: a protocol slot for a Jev classifier backend (wave 3 Task 15).

The ``DecisionGate`` protocol allows other classifier backends behind the same
cascade. This wave ships no Jev network code: ``JevGate`` is a documented,
always-fail-open placeholder ("protocol slot, not evaluated"). Whatever the
``OG_JEV_ENABLED`` / ``OG_JEV_URL`` environment says, every decision returns
``answer None`` / ``error "unavailable"`` / ``run_check True``, so the cascade
runs the full check, exactly as ADR-003's fail-open rule demands. A real
backend would be added behind the same protocol, never inline in the cascade.
"""

from __future__ import annotations

from ..textdoc import TextDoc
from .types import GateContext, GateDecision, Question


class JevGate:
    """Protocol slot only; not evaluated in this wave."""

    name = "jev"

    def decide(
        self, question: Question, change_order: TextDoc, context: GateContext
    ) -> GateDecision:
        return GateDecision(
            question=question.id,
            backend=self.name,
            tier="classifier",
            answer=None,
            confidence=None,
            samples=(),
            evidence=(),
            latency_ms=0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            error="unavailable",
            run_check=True,
        )
