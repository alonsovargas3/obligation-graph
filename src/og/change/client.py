"""The change-check client: render, request, parse, cache (wave 3, Task 16).

The model proposes RawFindings for one category against the rendered chain.
This module turns one SDK message into validated RawFindings (or a typed
failure), drives exactly one beta call per check through the count-tokens
reservation and the on-disk cache, and never caches a failure. Change checks
send no server-side fallback (rev 2.1 R2-3), so a call bills at most one model
attempt. Message usage is captured before status rejection, so refused and
truncated responses are still charged (rev 2 R6).
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

from ..budget import Budget, BudgetExhausted
from ..extract.types import Attempt, BadResponse, Refused, TruncatedResponse
from ..gates.types import Question
from ..replay import ReplayMiss
from .types import FINDING_KINDS, RAW_FINDING_FIELDS, ChainDoc, CheckOutcome, RawFinding

ROOT = Path(__file__).resolve().parents[3]
PROMPT_PATH = ROOT / "prompts" / "change_v1.md"
SCHEMA_PATH = ROOT / "prompts" / "change_v1.schema.json"

MAX_TOKENS = 4096
# Wave 4: the CLI passes the recorded-response directory (og.replay.cache_dir("change"));
# a bare Checker() simply never reads or writes recordings.
DEFAULT_CACHE_DIR = None

# Nullable string fields of one finding, in schema order after the required
# new_quote / new_segment_id / kind triple.
_NULLABLE_STR_FIELDS = (
    "old_doc",
    "old_quote",
    "old_segment_id",
    "old_value",
    "new_value",
    "target_label",
    "context_quote",
    "context_segment_id",
)

_PARSE_FAILURE_STATUS = {
    Refused: "refused",
    TruncatedResponse: "truncated",
    BadResponse: "invalid",
}


def prompt_version() -> str:
    """The change-check prompt identity: name + short digest of prompt and schema bytes."""
    digest = hashlib.sha256(PROMPT_PATH.read_bytes() + SCHEMA_PATH.read_bytes()).hexdigest()
    return f"change_v1@{digest[:8]}"


def _render_doc(member: ChainDoc) -> str:
    lines = [
        f"[{member.agreement_id} {seg.id}] {member.doc.text[seg.char_start : seg.char_end]}"
        for seg in member.doc.segments
    ]
    return f"## {member.agreement_id} ({member.role})\n" + "\n".join(lines)


def _category_block(category: str, question: Question) -> str:
    """The uncached tail: names the category and pastes its question definition."""
    return (
        "Check the change order against the chain for this category only.\n\n"
        f"Category: {category}\n\n{question.definition}\n"
    )


def build_request(
    chain: list[ChainDoc],
    category: str,
    question: Question,
    *,
    model: str,
    effort: str,
    max_tokens: int = MAX_TOKENS,
) -> dict:
    """The exact create() kwargs for one category check, per the wave 3 API contract.

    The chain block (base and prior amendments), then the change-order block,
    then the uncached category tail; the system block, the chain block, and the
    change-order block each end with an ephemeral cache breakpoint. No
    temperature, thinking, tools, tool_choice, betas, or fallbacks.
    """
    change_orders = [d for d in chain if d.role == "change_order"]
    if len(change_orders) != 1:
        raise ValueError(f"chain needs exactly one change_order document, got {len(change_orders)}")
    chain_text = "\n\n".join(_render_doc(d) for d in chain if d.role != "change_order")
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {
                "type": "text",
                "text": PROMPT_PATH.read_text(encoding="utf-8"),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": chain_text,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": _render_doc(change_orders[0]),
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": _category_block(category, question)},
                ],
            }
        ],
        "output_config": {
            "effort": effort,
            "format": {
                "type": "json_schema",
                "schema": json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
            },
        },
    }


def request_fingerprint(request: dict, chain: list[ChainDoc]) -> str:
    """Identity of (request, chain): canonical request JSON + each document's identity.

    The rendered request pins the prompt, schema, model, effort, max_tokens,
    category, question definition, and the chain text; the per-document digests
    additionally pin source and structure, so a stale answer can never be
    replayed against changed documents or a changed prompt.
    """
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256()
    digest.update(canonical.encode("utf-8"))
    for member in chain:
        textdoc_sha = hashlib.sha256(member.doc.to_json().encode("utf-8")).hexdigest()
        digest.update(b"\x00")
        digest.update(member.agreement_id.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(member.doc.source_sha256.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(textdoc_sha.encode("utf-8"))
    return digest.hexdigest()


def _require_str(value: object, field: str, *, nullable: bool) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise BadResponse(f"bad_type:{field}")


def _require_enum(value: object, field: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise BadResponse(f"bad_enum:{field}")


def _validate_finding(item: object) -> None:
    if not isinstance(item, dict):
        raise BadResponse("item_not_object")
    keys = set(item)
    if keys - set(RAW_FINDING_FIELDS):
        raise BadResponse("extra_field")
    if set(RAW_FINDING_FIELDS) - keys:
        raise BadResponse("missing_field")
    _require_str(item["new_quote"], "new_quote", nullable=False)
    _require_str(item["new_segment_id"], "new_segment_id", nullable=False)
    _require_enum(item["kind"], "kind", FINDING_KINDS)
    for field in _NULLABLE_STR_FIELDS:
        _require_str(item[field], field, nullable=True)


def _attempt(model: object, usage: object) -> Attempt:
    return Attempt(
        model=model,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
        refused=False,
    )


def _attempts(message: object) -> list[Attempt]:
    """One attempt per call: no fallback is sent, so a call bills at most one."""
    return [_attempt(getattr(message, "model", None), getattr(message, "usage", None))]


def parse_findings(message: object) -> tuple[list[RawFinding], list[Attempt]]:
    """Validate one SDK message into RawFindings, or raise Refused/Truncated/BadResponse."""
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        raise Refused()
    if stop_reason == "max_tokens":
        raise TruncatedResponse()
    blocks = getattr(message, "content", None) or []
    text_blocks = [b for b in blocks if getattr(b, "type", None) == "text"]
    if len(text_blocks) != 1:
        raise BadResponse("no_text")
    try:
        payload = json.loads(text_blocks[0].text)
    except ValueError:
        raise BadResponse("not_json") from None
    if not isinstance(payload, dict) or set(payload) != {"findings"}:
        raise BadResponse("bad_shape")
    raw_findings = payload["findings"]
    if not isinstance(raw_findings, list):
        raise BadResponse("bad_shape")
    items = []
    for raw in raw_findings:
        _validate_finding(raw)
        items.append(RawFinding(**{field: raw[field] for field in RAW_FINDING_FIELDS}))
    return items, _attempts(message)


class ChangeCache:
    """On-disk check cache: fingerprint-keyed, atomic, strictly allowlisted.

    Same approach as the wave 2 extraction cache, with the change payload keys.
    Only validated ok outcomes are ever stored; nothing derived from the
    request (system prompt, headers, key material) can pass through ``put``.
    A file that fails to parse or carries foreign keys is set aside as
    ``*.corrupt`` and treated as a miss.
    """

    PAYLOAD_KEYS = frozenset(
        {"findings", "attempts", "prompt_version", "category", "request_fingerprint", "latency_ms"}
    )
    REQUIRED_KEYS = frozenset({"findings", "attempts"})

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, fingerprint: str) -> Path:
        return self.root / fingerprint[:2] / f"{fingerprint}.json"

    def get(self, fingerprint: str) -> dict | None:
        """The cached payload, or None on a miss or a corrupt (set-aside) file."""
        path = self.path_for(fingerprint)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._set_aside(path)
            return None
        if not isinstance(data, dict) or not self._valid_keys(data):
            self._set_aside(path)
            return None
        return data

    def put(self, fingerprint: str, payload: dict) -> None:
        """Atomically store an allowlisted payload. Raises ValueError on foreign keys."""
        if not set(payload) >= self.REQUIRED_KEYS:
            raise ValueError("cache payload missing required keys")
        extra = set(payload) - self.PAYLOAD_KEYS
        if extra:
            raise ValueError(f"unexpected cache payload keys: {sorted(extra)}")
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

    def _valid_keys(self, data: dict) -> bool:
        return set(data) >= self.REQUIRED_KEYS and not set(data) - self.PAYLOAD_KEYS

    @staticmethod
    def _set_aside(path: Path) -> None:
        with contextlib.suppress(OSError):
            os.replace(path, path.with_name(path.name + ".corrupt"))


class Checker:
    """Runs one category check per call, through the cache, and never stores failures."""

    def __init__(
        self,
        client,
        *,
        model: str,
        effort: str,
        max_tokens: int = MAX_TOKENS,
        cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
        budget: Budget | None = None,
        strict: bool = False,
    ):
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.cache = ChangeCache(cache_dir) if cache_dir is not None else None
        self.budget = budget if budget is not None else Budget(None)
        self.strict = strict

    def check(self, chain: list[ChainDoc], category: str, question: Question) -> CheckOutcome:
        request = build_request(
            chain,
            category,
            question,
            model=self.model,
            effort=self.effort,
            max_tokens=self.max_tokens,
        )
        fingerprint = request_fingerprint(request, chain)
        cached = self.cache.get(fingerprint) if self.cache is not None else None
        if cached is not None:
            return self._outcome(
                category,
                "ok",
                [RawFinding(**raw) for raw in cached["findings"]],
                [Attempt(**raw) for raw in cached["attempts"]],
                True,
                cached.get("latency_ms"),
                fingerprint,
                None,
            )
        if self.strict:
            # OG_REPLAY=strict: a miss is an error before any client call,
            # and nothing is written (wave 4 rev 2 W4-5).
            raise ReplayMiss(fingerprint)
        try:
            counted = self.client.beta.messages.count_tokens(
                **{k: request[k] for k in ("model", "system", "messages", "output_config")}
            ).input_tokens
        except Exception:  # noqa: BLE001 - reduced to a short code below
            # A count failure means no call (R2-3); the budget stops for good.
            self.budget.fail("count_tokens_error")
            return self._outcome(
                category, "budget_stop", [], [], False, None, fingerprint, "count_tokens_error"
            )
        try:
            reservation = self.budget.reserve(self.model, int(counted), self.max_tokens)
        except BudgetExhausted as exhausted:
            code = str(exhausted) or "budget_exhausted"
            return self._outcome(category, "budget_stop", [], [], False, None, fingerprint, code)
        latency_ms = None
        try:
            start = time.monotonic()
            message = self.client.beta.messages.create(**request)
            latency_ms = max(0, int((time.monotonic() - start) * 1000))
        except Exception as error:  # noqa: BLE001 - only the class name is kept
            # No message, no usage: the whole reservation is charged (R6).
            self.budget.settle_unknown(reservation)
            return self._outcome(
                category, "error", [], [], False, latency_ms, fingerprint, type(error).__name__
            )
        try:
            items, attempts = parse_findings(message)
        except (Refused, TruncatedResponse, BadResponse) as error:
            # Usage is captured before status rejection, so the call is charged.
            attempts = _attempts(message)
            self.budget.settle(reservation, attempts)
            status = _PARSE_FAILURE_STATUS[type(error)]
            return self._outcome(
                category, status, [], attempts, False, latency_ms, fingerprint, None
            )
        self.budget.settle(reservation, attempts)
        if self.cache is not None:
            self.cache.put(
                fingerprint,
                {
                    "findings": [asdict(item) for item in items],
                    "attempts": [asdict(a) for a in attempts],
                    "prompt_version": prompt_version(),
                    "category": category,
                    "request_fingerprint": fingerprint,
                    "latency_ms": latency_ms,
                },
            )
        return self._outcome(category, "ok", items, attempts, False, latency_ms, fingerprint, None)

    @staticmethod
    def _outcome(
        category: str,
        status: str,
        items: list[RawFinding],
        attempts: list[Attempt],
        cache_hit: bool,
        latency_ms: int | None,
        fingerprint: str,
        error: str | None = None,
    ) -> CheckOutcome:
        return CheckOutcome(
            category=category,
            status=status,
            items=items,
            attempts=attempts,
            cache_hit=cache_hit,
            latency_ms=latency_ms,
            request_fingerprint=fingerprint,
            error=error,
        )
