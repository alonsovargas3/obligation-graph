"""SYNTHETIC test doubles for wave 3 (change checks and gates).

Nothing here is a recorded API response. FakeAnthropic stands in for an
`anthropic` client and exposes:
  - .messages.create(**kw)          (gates: plain Messages API)
  - .messages.count_tokens(**kw)    (every call is counted first; rev 2.1 R2-3)
  - .beta.messages.create(**kw)     (change checks use the same beta surface as extraction)
Every call's kwargs are recorded. Answers come from a responder(kwargs) or a queue.
Real responses recorded by the coordinator live under tests/fixtures/api/.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from og.change.types import RAW_FINDING_FIELDS
from og.textdoc import TextDoc

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-4-5-20251001"
SENTINEL_KEY = "sk-ant-SENTINEL-0000-do-not-log-0000"
FIX = Path(__file__).parent / "fixtures" / "change"
BASE_ID = "constantcontact-2011-ex1041"
A1_ID = "constantcontact-2012-ex101"
A3_ID = "endurance-2017-ex106"


def real_doc(doc_id: str) -> TextDoc:
    """A real ingested TextDoc (public SEC filing) copied from the integration checkout."""
    return TextDoc.load(FIX / f"{doc_id}.json")


def usage(inp=120, out=10, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        iterations=None,
    )


def message(text, stop_reason="end_turn", model=SONNET, usage_=None):
    blocks = [] if text is None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        stop_details=None,
        model=model,
        usage=usage_ if usage_ is not None else usage(),
    )


def gate_message(answer="no", **kw):
    kw.setdefault("model", HAIKU)
    return message(json.dumps({"answer": answer}), **kw)


def finding(**over):
    """A schema-complete finding dict; every field present, defaults null."""
    base = {f: None for f in RAW_FINDING_FIELDS}
    base.update(new_quote="hereby deleted", new_segment_id="p0001", kind="supersedes")
    base.update(over)
    return base


def findings_message(items, **kw):
    return message(json.dumps({"findings": items}), **kw)


class FakeAnthropic:
    """Records kwargs for create and count_tokens; answers from a responder or a queue."""

    def __init__(
        self,
        responses=None,
        responder: Callable | None = None,
        count: int | Callable | BaseException = 1000,
    ):
        self.queue = list(responses or [])
        self.responder = responder
        self.count = count
        self.calls: list[dict] = []
        self.count_calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create, count_tokens=self._count)
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(create=self._create, count_tokens=self._count)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.responder(kwargs) if self.responder else self.queue.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out

    def _count(self, **kwargs):
        self.count_calls.append(kwargs)
        if isinstance(self.count, BaseException):
            raise self.count
        n = self.count(kwargs) if callable(self.count) else self.count
        return SimpleNamespace(input_tokens=n)
