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

Wave 4 (Task 33): an optional ``cache`` (a :class:`GateCache`, wired to
``eval/recorded/gate/``) replays each sample by fingerprint. A hit makes no
reservation and no client call and reports the recorded usage, cost, and
latency with ``cache_hit = True``; ``OG_REPLAY=strict`` turns any miss into
:class:`og.replay.ReplayMiss` before the client is touched (ADR-010).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import anthropic

from ..budget import Budget, BudgetExhausted
from ..extract.types import Attempt
from ..pricing import price
from ..replay import ReplayMiss
from ..replay import mode as replay_mode
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


def _content_text(message: object) -> str:
    blocks = getattr(message, "content", None) or []
    return "".join(
        getattr(block, "text", "") for block in blocks if getattr(block, "type", None) == "text"
    )


def _parse_answer(message: object) -> tuple[bool | None, str | None]:
    """One sample from one SDK message: the answer, or a short error code."""
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        return None, "refused"
    if stop_reason == "max_tokens":
        return None, "truncated"
    try:
        payload = json.loads(_content_text(message))
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


def gate_fingerprint(request: dict, change_order_sha256: str, sample_index: int) -> str:
    """Identity of one gate sample: the full effective request, the change-order
    TextDoc sha, and the sample index (wave 4 rev 2 W4-5). No run ids."""
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256()
    digest.update(canonical.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(change_order_sha256.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(str(sample_index).encode("utf-8"))
    return digest.hexdigest()


class GateCache:
    """On-disk gate-sample cache under eval/recorded/gate/: one payload per sample.

    Same allowlist discipline as the extraction and change caches: only a
    usable sample (a parsed answer, its attempts, its latency) is ever stored,
    keyed by ``gate_fingerprint``. Nothing derived from the request can pass
    through ``put``; a file that fails to parse is set aside as ``*.corrupt``
    and treated as a miss.
    """

    PAYLOAD_KEYS = frozenset({"answer_text", "stop_reason", "attempts", "latency_ms"})
    REQUIRED_KEYS = frozenset({"answer_text", "attempts"})

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, fingerprint: str) -> Path:
        return self.root / fingerprint[:2] / f"{fingerprint}.json"

    def get(self, fingerprint: str) -> dict | None:
        """The recorded payload, or None on a miss or a corrupt (set-aside) file."""
        path = self.path_for(fingerprint)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._set_aside(path)
            return None
        if not self._valid(data):
            self._set_aside(path)
            return None
        return data

    def put(self, fingerprint: str, payload: dict) -> None:
        """Atomically store an allowlisted payload. Raises ValueError on foreign keys."""
        if not set(payload) >= self.REQUIRED_KEYS:
            raise ValueError("gate payload missing required keys")
        extra = set(payload) - self.PAYLOAD_KEYS
        if extra:
            raise ValueError(f"unexpected gate payload keys: {sorted(extra)}")
        path = self.path_for(fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def _valid(self, data: object) -> bool:
        return (
            isinstance(data, dict)
            and set(data) >= self.REQUIRED_KEYS
            and not set(data) - self.PAYLOAD_KEYS
            and isinstance(data["answer_text"], str)
            and isinstance(data["attempts"], list)
        )

    @staticmethod
    def _set_aside(path: Path) -> None:
        with contextlib.suppress(OSError):
            os.replace(path, path.with_name(path.name + ".corrupt"))


class HaikuGate:
    """The classifier-tier backend: a small Claude model, sampled three times."""

    name = "haiku"

    def __init__(self, client, model: str, budget: Budget, timeout_s: float = 30, cache=None):
        self.client = client
        self.model = model
        self.budget = budget
        self.timeout_s = timeout_s
        self.cache = cache

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
        # The replay fingerprint pins the full effective request (W4-5), the
        # change order's canonical TextDoc sha, and the sample index. The call
        # timeout is not request identity, so it is excluded.
        doc_sha = hashlib.sha256(change_order.to_json().encode("utf-8")).hexdigest()
        fingerprint_request = {
            "model": count_kwargs["model"],
            "system": count_kwargs["system"],
            "messages": count_kwargs["messages"],
            "output_config": count_kwargs["output_config"],
            "max_tokens": MAX_TOKENS,
        }
        replay = replay_mode()

        samples: list[bool | None] = []
        errors: list[str] = []
        input_tokens = 0
        output_tokens = 0
        cost_usd = 0.0
        latency_ms = 0
        replayed = 0
        for index in range(GATE_POLICY["samples"]):
            fingerprint = gate_fingerprint(fingerprint_request, doc_sha, index)
            outcome = None
            if replay != "off" and self.cache is not None:
                payload = self.cache.get(fingerprint)
                if payload is not None:
                    outcome = self._replayed_sample(payload)
                    if outcome is not None:
                        replayed += 1
            if outcome is None:
                if replay == "strict":
                    # A strict miss is an error before any client is touched;
                    # strict mode never writes (wave 4 rev 2 W4-5).
                    raise ReplayMiss(fingerprint)
                answer, error, usage_in, usage_out, cost, record, sample_ms = self._sample(
                    count_kwargs, create_kwargs
                )
                outcome = (answer, error, usage_in, usage_out, cost, sample_ms)
                if record is not None and replay == "on" and self.cache is not None:
                    self.cache.put(fingerprint, record)
            answer, error, usage_in, usage_out, cost, sample_ms = outcome
            samples.append(answer)
            if error is not None:
                errors.append(error)
            input_tokens += usage_in
            output_tokens += usage_out
            cost_usd += cost
            latency_ms += sample_ms

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
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            error=error,
            run_check=not unanimous_no,
            cache_hit=replayed == GATE_POLICY["samples"],
        )

    @staticmethod
    def _replayed_sample(payload: dict) -> tuple | None:
        """(answer, error, in, out, cost, latency) from one recorded sample.

        None means the payload is unusable and counts as a miss. A replayed
        sample makes no reservation and no client call; it reports the recorded
        usage priced afresh, and the recorded latency (wave 4 rev 2 W4-4).
        """
        try:
            attempts = [Attempt(**raw) for raw in payload["attempts"]]
        except (TypeError, KeyError):
            return None
        message = SimpleNamespace(
            stop_reason=payload.get("stop_reason"),
            content=[SimpleNamespace(type="text", text=payload["answer_text"])],
        )
        answer, _error = _parse_answer(message)
        cost, _basis = price(attempts)
        if answer is None or cost is None:
            return None
        latency = payload.get("latency_ms") or 0
        return (
            answer,
            None,
            sum(a.input_tokens or 0 for a in attempts),
            sum(a.output_tokens or 0 for a in attempts),
            cost,
            latency if isinstance(latency, int) else 0,
        )

    def _sample(
        self, count_kwargs: dict, create_kwargs: dict
    ) -> tuple[bool | None, str | None, int, int, float, dict | None, int]:
        """One gated call: count, reserve, create, settle, then parse.

        Returns (answer, error code, input tokens, output tokens, cost, record
        payload or None, call latency ms). A failed sample returns ``None`` with
        an error code, zero tokens, and no record; only a usable sample is ever
        recorded (wave 4 W4-4).
        """
        latency_ms = 0
        try:
            if self.budget.exhausted is not None:
                raise BudgetExhausted(self.budget.exhausted)
            counted = self.client.messages.count_tokens(**count_kwargs)
            tokens = int(getattr(counted, "input_tokens", 0) or 0)
            reservation = self.budget.reserve(self.model, tokens, MAX_TOKENS)
        except BudgetExhausted:
            return None, "budget_stop", 0, 0, 0.0, None, 0
        except Exception:
            # A count_tokens failure means no call (rev 2.1 R2-3); the stop is
            # sticky for the rest of the invocation.
            self.budget.fail("budget_stop")
            return None, "budget_stop", 0, 0, 0.0, None, 0
        try:
            start = time.monotonic()
            message = self.client.messages.create(**create_kwargs)
            latency_ms = max(0, int((time.monotonic() - start) * 1000))
        except Exception as exc:
            # No usage is available; the full reservation is charged.
            self.budget.settle_unknown(reservation)
            return None, _exception_code(exc), 0, 0, reservation.amount_usd, None, latency_ms
        attempt = _attempt(message, self.model)
        settled = self.budget.settle(reservation, [attempt])
        if settled is None:
            settled = reservation.amount_usd  # unpriced usage: full reservation
        answer, error = _parse_answer(message)
        record = None
        if error is None and answer is not None:
            record = {
                "answer_text": _content_text(message),
                "stop_reason": getattr(message, "stop_reason", None),
                "attempts": [asdict(attempt)],
                "latency_ms": latency_ms,
            }
        return (
            answer,
            error,
            attempt.input_tokens or 0,
            attempt.output_tokens or 0,
            settled,
            record,
            latency_ms,
        )
