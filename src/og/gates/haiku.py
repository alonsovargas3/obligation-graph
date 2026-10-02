"""HaikuGate: the classifier tier of the gate cascade (wave 3 Task 15).

Renders ``prompts/gate_v1.md`` plus the question definition plus every
operative segment of the change order, asks the small gate model
``GATE_POLICY["samples"]`` times through the plain Messages API, and folds
the answers into one fail-open :class:`GateDecision`.

A sample is usable only when the API returned a parseable
``{"answer": "yes" | "no"}``. Every other outcome (refusal, truncation,
invalid JSON, timeout, any exception, or a budget stop) fails that sample
open: it counts as dissent, never as a "no". The decision can therefore
propose a skip only on an error-free unanimous "no" (ADR-003, plan rev 2 R5).

Budget handling follows rev 2.1 R2-3: before every call, ``count_tokens`` runs
on the complete effective request (``output_config`` included), the worst case
is reserved, and the actual usage is settled before the response is parsed, so
refused and truncated samples are still charged. There is no server-side
fallback, so one call bills at most one attempt.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import anthropic

from ..budget import Budget, BudgetExhausted
from ..extract.types import Attempt
from ..textdoc import TextDoc
from .types import GATE_POLICY, GateContext, GateDecision, Question

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
MAX_TOKENS = 64
_SYSTEM_FILE = PROMPTS_DIR / "gate_v1.md"
_SCHEMA_FILE = PROMPTS_DIR / "gate_v1.schema.json"


def _signature_block(segments: list[str]) -> tuple[int, int] | None:
    """The [start, end) index range of the signature block, if any.

    From the segment that starts with ``IN WITNESS WHEREOF`` up to, but not
    including, the next segment that starts with ``EXHIBIT``, or to the end of
    the document. Signature blocks carry no operative terms; exhibits after
    them stay in (plan rev 2 R10).
    """
    start: int | None = None
    for i, text in enumerate(segments):
        stripped = text.strip().upper()
        if start is None:
            if stripped.startswith("IN WITNESS WHEREOF"):
                start = i
        elif stripped.startswith("EXHIBIT"):
            return (start, i)
    if start is not None:
        return (start, len(segments))
    return None


def _render_user(question: Question, change_order: TextDoc) -> str:
    """The gate user message: the question, then the operative segments."""
    texts = [change_order.segment_text(seg.id) for seg in change_order.segments]
    block = _signature_block(texts)
    lines = [
        f"Question: {question.definition}",
        "",
        "Change order, one paragraph per line:",
        "",
    ]
    for i, (seg, text) in enumerate(zip(change_order.segments, texts, strict=True)):
        if block is not None and block[0] <= i < block[1]:
            continue
        lines.append(f"[{seg.id}] {text}")
    return "\n".join(lines)


def _attempt(message: object, default_model: str) -> Attempt:
    usage = getattr(message, "usage", None)
    model = getattr(message, "model", None)
    return Attempt(
        model=model if isinstance(model, str) else default_model,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
        refused=False,
    )


def _parse_answer(message: object) -> tuple[bool | None, str | None]:
    """One sample from one SDK message: the answer, or a short error code."""
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        return None, "refused"
    if stop_reason == "max_tokens":
        return None, "truncated"
    blocks = getattr(message, "content", None) or []
    text = "".join(
        getattr(block, "text", "") for block in blocks if getattr(block, "type", None) == "text"
    )
    try:
        payload = json.loads(text)
    except ValueError:
        return None, "invalid"
    if not isinstance(payload, dict):
        return None, "invalid"
    answer = payload.get("answer")
    if answer == "yes":
        return True, None
    if answer == "no":
        return False, None
    return None, "invalid"


def _exception_code(exc: BaseException) -> str:
    if isinstance(exc, (TimeoutError, anthropic.APITimeoutError)):
        return "timeout"
    return type(exc).__name__


class HaikuGate:
    """The classifier-tier backend: a small Claude model, sampled three times."""

    name = "haiku"

    def __init__(self, client, model: str, budget: Budget, timeout_s: float = 30):
        self.client = client
        self.model = model
        self.budget = budget
        self.timeout_s = timeout_s

    def decide(
        self, question: Question, change_order: TextDoc, context: GateContext
    ) -> GateDecision:
        system = _SYSTEM_FILE.read_text(encoding="utf-8")
        schema = json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
        count_kwargs: dict = {
            "model": self.model,
            "system": system,
            "messages": [{"role": "user", "content": _render_user(question, change_order)}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        create_kwargs = {**count_kwargs, "max_tokens": MAX_TOKENS, "timeout": self.timeout_s}

        started = time.perf_counter()
        samples: list[bool | None] = []
        errors: list[str] = []
        input_tokens = 0
        output_tokens = 0
        cost_usd = 0.0
        for _ in range(GATE_POLICY["samples"]):
            answer, error, usage_in, usage_out, cost = self._sample(count_kwargs, create_kwargs)
            samples.append(answer)
            if error is not None:
                errors.append(error)
            input_tokens += usage_in
            output_tokens += usage_out
            cost_usd += cost

        usable = [s for s in samples if s is not None]
        yes = sum(1 for s in usable if s is True)
        no = len(usable) - yes
        if usable:
            # A 1:1 split between valid samples answers yes (rev 2.2): ties
            # fail open, and only a unanimous "no" can ever propose a skip.
            answer = yes >= no
            confidence: float | None = max(yes, no) / GATE_POLICY["samples"]
        else:
            answer = None
            confidence = None
        error = errors[0] if errors else None  # only the first error is kept
        unanimous_no = (
            error is None
            and answer is False
            and confidence == 1.0
            and len(samples) == GATE_POLICY["samples"]
            and all(s is False for s in samples)
        )
        return GateDecision(
            question=question.id,
            backend=self.name,
            tier="classifier",
            answer=answer,
            confidence=confidence,
            samples=tuple(samples),
            evidence=(),
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            error=error,
            run_check=not unanimous_no,
        )

    def _sample(
        self, count_kwargs: dict, create_kwargs: dict
    ) -> tuple[bool | None, str | None, int, int, float]:
        """One gated call: count, reserve, create, settle, then parse.

        Returns (answer, error code, input tokens, output tokens, cost). A
        failed sample returns ``None`` with an error code and zero tokens.
        """
        try:
            if self.budget.exhausted is not None:
                raise BudgetExhausted(self.budget.exhausted)
            counted = self.client.messages.count_tokens(**count_kwargs)
            tokens = int(getattr(counted, "input_tokens", 0) or 0)
            reservation = self.budget.reserve(self.model, tokens, MAX_TOKENS)
        except BudgetExhausted:
            return None, "budget_stop", 0, 0, 0.0
        except Exception:
            # A count_tokens failure means no call (rev 2.1 R2-3); the stop is
            # sticky for the rest of the invocation.
            self.budget.fail("budget_stop")
            return None, "budget_stop", 0, 0, 0.0
        try:
            message = self.client.messages.create(**create_kwargs)
        except Exception as exc:
            # No usage is available; the full reservation is charged.
            self.budget.settle_unknown(reservation)
            return None, _exception_code(exc), 0, 0, reservation.amount_usd
        attempt = _attempt(message, self.model)
        settled = self.budget.settle(reservation, [attempt])
        if settled is None:
            settled = reservation.amount_usd  # unpriced usage: full reservation
        answer, error = _parse_answer(message)
        return (
            answer,
            error,
            attempt.input_tokens or 0,
            attempt.output_tokens or 0,
            settled,
        )
