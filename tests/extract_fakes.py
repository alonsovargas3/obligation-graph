"""SYNTHETIC test doubles for the extraction client (wave 2).

Nothing here is a recorded API response. FakeClient stands in for an
`anthropic` client: it exposes `.beta.messages.create(**kwargs)`, records every
call's kwargs, and returns queued messages (or raises queued exceptions). The
message builders produce SDK-shaped objects (attribute access, like the SDK's
pydantic models) for the stop reasons the extractor must handle. Real
responses recorded by the coordinator live under tests/fixtures/api/.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from types import SimpleNamespace

from og.extract.types import RAW_FIELDS
from og.textdoc import Page, Section, Segment, TextDoc

MODEL = "claude-sonnet-5-5"
SENTINEL_KEY = "sk-ant-SENTINEL-0000-do-not-log-0000"


def usage(inp=120, out=40, cache_read=0, cache_write=0, iterations=None):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        iterations=iterations,
    )


def iteration(kind, model, inp=100, out=10):
    """One entry of usage.iterations (assumed shape; C1 confirms the real one)."""
    return SimpleNamespace(
        type=kind,
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def thinking_block():
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


def message(blocks, stop_reason="end_turn", model=MODEL, usage_=None):
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        stop_details=None,
        model=model,
        usage=usage_ if usage_ is not None else usage(),
    )


def item(**over):
    """A schema-complete item dict; every field present, defaults null."""
    base = {f: None for f in RAW_FIELDS}
    base.update(span_text="Tenant shall pay rent.", segment_id="p0001", kind="obligation")
    base.update(type="payment", status="active")
    base.update(over)
    return base


def raw_text_message(text, **kw):
    return message([text_block(text)], **kw)


def ok_message(items, **kw):
    return message([text_block(json.dumps({"items": items}))], **kw)


def refusal_message():
    return message([], stop_reason="refusal")


def max_tokens_message():
    return message([text_block(json.dumps({"items": [item()]}))], stop_reason="max_tokens")


class FakeClient:
    """Records kwargs; answers from a queue or a responder(kwargs) function."""

    def __init__(self, responses=None, responder: Callable | None = None):
        self.queue = list(responses or [])
        self.responder = responder
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.responder(kwargs) if self.responder else self.queue.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


_LINE = re.compile(r"^\[(p\d{4})\] (.*)$", re.M)


def extractable_lines(kwargs):
    """(segment_id, text) for the non-context lines of a request's user message."""
    content = kwargs["messages"][0]["content"]
    return _LINE.findall(content)


def echo_responder(kwargs):
    """Quote every extractable line containing 'shall' as a payment obligation."""
    items = [
        item(
            span_text=text,
            segment_id=sid,
            owed_by="Tenant",
            owed_to="Landlord",
            description="Tenant must perform.",
        )
        for sid, text in extractable_lines(kwargs)
        if "shall" in text
    ]
    return ok_message(items)


def build_doc(sections, doc_id="d1", sha="a" * 64):
    """TextDoc from [(number, heading, [lines])], one segment per line, one page."""
    lines, secs, segs = [], [], []
    pos = 0
    n = 0
    starts = []
    for i, (_num, _head, ls) in enumerate(sections):
        starts.append(pos)
        for line in ls:
            n += 1
            segs.append(Segment(f"p{n:04d}", f"s{i:04d}", 1, pos, pos + len(line)))
            lines.append(line)
            pos += len(line) + 1
    text = "\n".join(lines)
    for i, (num, head, _ls) in enumerate(sections):
        end = starts[i + 1] if i + 1 < len(sections) else len(text)
        secs.append(Section(f"s{i:04d}", num, head, starts[i], end, None))
    doc = TextDoc(doc_id, sha, text, secs, [Page(1, 0, len(text))], segs)
    doc.validate()
    return doc


def filler(tag, n_chars):
    """A deterministic sentence of roughly n_chars characters."""
    words = []
    while len(" ".join(words)) < n_chars:
        words.append(f"{tag}{len(words)}")
    return "Tenant shall " + " ".join(words) + "."
