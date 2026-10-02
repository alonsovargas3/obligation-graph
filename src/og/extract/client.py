"""The extraction client: strict response parsing and the per-chunk Extractor.

The model only proposes; this module turns an SDK message into validated
RawItems (or a short, typed failure) and drives one API call per chunk through
the cache. Every failure is reduced to a status plus a short error code; an
exception repr never enters a log line. Ok outcomes are cached under the
request fingerprint; failures never are.

Wave 4 (Task 33): the cache is the recorded-response store under
``eval/recorded/extract/``. With ``strict=True`` a cache miss raises
:class:`og.replay.ReplayMiss` before the client is touched, so a strict replay
never constructs an API client and never writes.
"""

from __future__ import annotations

import datetime
import json
import math
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path

import anthropic

from ..replay import ReplayMiss
from ..textdoc import TextDoc
from .cache import ResponseCache
from .chunk import chunk_doc
from .prompt import build_request, prompt_version, request_fingerprint
from .types import (
    KINDS,
    OBL_TYPES,
    RAW_FIELDS,
    ROLES,
    STATUSES,
    Attempt,
    BadResponse,
    Chunk,
    ChunkOutcome,
    ExtractResult,
    RawItem,
    Refused,
    TruncatedResponse,
)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _require_str(value: object, field: str, *, nullable: bool) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise BadResponse(f"bad_type:{field}")


def _require_enum(value: object, field: str, allowed: tuple[str, ...]) -> None:
    if value is None or value in allowed:
        return
    raise BadResponse(f"bad_enum:{field}")


def _require_number(value: object, field: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadResponse(f"bad_type:{field}")
    if not math.isfinite(value):
        raise BadResponse(f"bad_number:{field}")


def _require_int(value: object, field: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadResponse(f"bad_type:{field}")


def _require_date(value: object, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise BadResponse(f"bad_date:{field}")
    year, month, day = (int(part) for part in value.split("-"))
    try:
        datetime.date(year, month, day)
    except ValueError:
        raise BadResponse(f"bad_date:{field}") from None


def _validate_item(item: object) -> None:
    if not isinstance(item, dict):
        raise BadResponse("item_not_object")
    keys = set(item)
    if keys - set(RAW_FIELDS):
        raise BadResponse("extra_field")
    if set(RAW_FIELDS) - keys:
        raise BadResponse("missing_field")
    _require_str(item["span_text"], "span_text", nullable=False)
    _require_str(item["segment_id"], "segment_id", nullable=False)
    _require_enum(item["kind"], "kind", KINDS)
    _require_enum(item["type"], "type", OBL_TYPES)
    _require_str(item["owed_by"], "owed_by", nullable=True)
    _require_str(item["owed_to"], "owed_to", nullable=True)
    _require_str(item["description"], "description", nullable=True)
    _require_number(item["amount"], "amount")
    _require_str(item["currency"], "currency", nullable=True)
    _require_date(item["due_date"], "due_date")
    _require_str(item["anchor_event"], "anchor_event", nullable=True)
    _require_int(item["offset_days"], "offset_days")
    _require_str(item["trigger"], "trigger", nullable=True)
    _require_enum(item["status"], "status", STATUSES)
    _require_str(item["name"], "name", nullable=True)
    _require_date(item["date"], "date")
    _require_enum(item["role"], "role", ROLES)


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
    usage = getattr(message, "usage", None)
    message_model = getattr(message, "model", None)
    iterations = getattr(usage, "iterations", None) if usage is not None else None
    if iterations:
        # usage.iterations is present even without a fallback, and each
        # iteration's model is null when no fallback ran; such an attempt
        # reports the message-level model.
        attempts = []
        for entry in iterations:
            model = getattr(entry, "model", None)
            attempts.append(_attempt(model if model is not None else message_model, entry))
        # Every attempt but the last was superseded by a fallback; only a final
        # attempt can end in the response we are parsing.
        return [
            Attempt(
                model=a.model,
                input_tokens=a.input_tokens,
                output_tokens=a.output_tokens,
                cache_read_tokens=a.cache_read_tokens,
                cache_write_tokens=a.cache_write_tokens,
                refused=i < len(attempts) - 1,
            )
            for i, a in enumerate(attempts)
        ]
    return [_attempt(getattr(message, "model", None), usage)]


def parse_response(message: object) -> tuple[list[RawItem], list[Attempt]]:
    """Validate one SDK message into RawItems, or raise Refused/Truncated/BadResponse."""
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
    if not isinstance(payload, dict) or set(payload) != {"items"}:
        raise BadResponse("bad_shape")
    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        raise BadResponse("bad_shape")
    items = []
    for raw in raw_items:
        _validate_item(raw)
        items.append(RawItem(**{field: raw[field] for field in RAW_FIELDS}))
    return items, _attempts(message)


def _cache_payload(
    doc: TextDoc, chunk: Chunk, version: str, items: list[RawItem], attempts: list[Attempt]
) -> dict:
    return {
        "items": [asdict(item) for item in items],
        "attempts": [asdict(a) for a in attempts],
        "prompt_version": version,
        "doc_id": doc.doc_id,
        "chunk_id": chunk.chunk_id,
    }


class Extractor:
    """Runs one API call per chunk, through the cache, and never stores failures."""

    def __init__(
        self,
        client,
        cache: ResponseCache | None,
        *,
        model: str,
        effort: str,
        no_cache: bool = False,
        archive_dir: str | Path | None = None,
        max_chars: int = 12000,
        strict: bool = False,
    ):
        self.client = client
        self.cache = cache
        self.model = model
        self.effort = effort
        self.no_cache = no_cache
        self.archive_dir = Path(archive_dir) if archive_dir is not None else None
        self.max_chars = max_chars
        self.strict = strict

    def extract(self, doc: TextDoc) -> ExtractResult:
        chunks = chunk_doc(doc, max_chars=self.max_chars)
        version = prompt_version()
        archive = None
        if self.no_cache and self.archive_dir is not None:
            # One archive subtree per extract() run: samples never share a dir
            # with the canonical cache or with each other.
            attempt_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            archive = ResponseCache(self.archive_dir / attempt_id)
        outcomes = [self._run_chunk(doc, chunk, version, archive) for chunk in chunks]
        return ExtractResult(doc_id=doc.doc_id, prompt_version=version, outcomes=outcomes)

    @staticmethod
    def _failed(
        chunk: Chunk,
        status: str,
        latency_ms: int | None,
        fingerprint: str,
        error: str | None = None,
    ) -> ChunkOutcome:
        return ChunkOutcome(
            chunk_id=chunk.chunk_id,
            status=status,
            items=[],
            attempts=[],
            latency_ms=latency_ms,
            cache_hit=False,
            request_fingerprint=fingerprint,
            error=error,
        )

    def _run_chunk(
        self, doc: TextDoc, chunk: Chunk, version: str, archive: ResponseCache | None
    ) -> ChunkOutcome:
        request = build_request(chunk, model=self.model, effort=self.effort)
        fingerprint = request_fingerprint(request, doc)
        if not self.no_cache and self.cache is not None:
            payload = self.cache.get(fingerprint)
            if payload is not None:
                items = [RawItem(**raw) for raw in payload["items"]]
                attempts = [Attempt(**raw) for raw in payload["attempts"]]
                return ChunkOutcome(
                    chunk.chunk_id, "ok", items, attempts, None, True, fingerprint, None
                )
            if self.strict:
                # OG_REPLAY=strict: a miss is an error before any client call,
                # and nothing is written (wave 4 rev 2 W4-5).
                raise ReplayMiss(fingerprint)
        latency_ms = None
        try:
            start = time.monotonic()
            message = self.client.beta.messages.create(**request)
            latency_ms = max(0, int((time.monotonic() - start) * 1000))
            items, attempts = parse_response(message)
        except Refused:
            return self._failed(chunk, "refused", latency_ms, fingerprint)
        except TruncatedResponse:
            return self._failed(chunk, "truncated", latency_ms, fingerprint)
        except BadResponse:
            return self._failed(chunk, "invalid", latency_ms, fingerprint)
        except anthropic.APIError as error:
            return self._failed(chunk, "error", latency_ms, fingerprint, type(error).__name__)
        payload = _cache_payload(doc, chunk, version, items, attempts)
        if self.no_cache:
            if archive is not None:
                archive.put(fingerprint, payload)
        elif self.cache is not None:
            self.cache.put(fingerprint, payload)
        return ChunkOutcome(
            chunk_id=chunk.chunk_id,
            status="ok",
            items=items,
            attempts=attempts,
            latency_ms=latency_ms,
            cache_hit=False,
            request_fingerprint=fingerprint,
            error=None,
        )
