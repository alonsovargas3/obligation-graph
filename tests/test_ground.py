import json
import random

import pytest

from og.ground import Span, ground, log_drop, normalize_ws
from og.textdoc import Page, Section, TextDoc

T = (
    "ARTICLE 2 RENT\n"
    "2.1 Tenant shall pay Base Rent monthly.\n"
    "2.2 Tenant shall pay\u00a0Additional\n  Rent within thirty days.\n"
    "2.3 Tenant shall pay taxes.\n"
    "ARTICLE 3 TERM\n"
    "3.1 The “Term” is ten years. Tenant shall pay nothing here.\n"
)
S3 = T.index("ARTICLE 3")
P2 = T.index("2.3")
DOC = TextDoc(
    "d",
    "0" * 64,
    T,
    [Section("s2", "2", "RENT", 0, S3, "RENT"), Section("s3", "3", "TERM", S3, len(T), "TERM")],
    [Page(1, 0, P2), Page(2, P2, len(T))],
    [],
)


def check(r, span):
    assert r.grounded
    assert normalize_ws(T[r.char_start : r.char_end]) == normalize_ws(span.span_text)
    assert r.section_id == DOC.section_for(r.char_start).id
    assert r.page == DOC.page_for(r.char_start)


def test_normalize_ws_only_whitespace():
    assert normalize_ws("  a\u00a0\n\tb  ") == "a b"
    assert normalize_ws("“A”") == "“A”"


def test_exact_in_range():
    i = T.index("Tenant shall pay Base")
    sp = Span("Tenant shall pay Base Rent monthly.", i, i + 35)
    r = ground(DOC, sp)
    assert r.method == "range" and r.char_start == i and r.reason is None
    check(r, sp)


def test_range_is_containment_not_equality():
    sp = Span("Base Rent", T.index("2.1"), T.index("2.2"))
    r = ground(DOC, sp)
    assert r.method == "range"
    check(r, sp)


def test_nbsp_and_newlines_ground():
    sp = Span("Tenant shall pay Additional Rent within thirty days.", T.index("2.2"), P2)
    r = ground(DOC, sp)
    check(r, sp)


def test_result_carries_derived_section_and_page():
    sp = Span("Tenant shall pay taxes.", P2, S3, section_id="s2")
    r = ground(DOC, sp)
    check(r, sp)
    assert (r.section_id, r.page) == ("s2", 2)


def test_wrong_offsets_fall_back_to_section():
    sp = Span("Tenant shall pay taxes.", 0, 5)
    r = ground(DOC, sp)
    assert r.method == "section"
    check(r, sp)


def test_section_fallback_picks_nearest_occurrence():
    sp = Span("Tenant shall pay", P2 - 2, P2 - 1, section_id="s2")
    r = ground(DOC, sp)
    assert r.method == "section" and r.char_start == T.index("Tenant shall pay taxes")


def test_fallback_tie_goes_to_earlier():
    first = T.index("Tenant shall pay Base")
    second = T.index("Tenant shall pay\u00a0Additional")
    mid = (first + second) // 2
    assert mid - first == second - mid
    r = ground(DOC, Span("Tenant shall pay", mid, mid + 1, section_id="s2"))
    assert r.char_start == first


def test_fallback_does_not_leave_section():
    sp = Span("Tenant shall pay nothing here.", 0, 5, section_id="s2")
    r = ground(DOC, sp)
    assert not r.grounded and r.reason == "not_found_in_section"
    assert (r.char_start, r.char_end, r.method) == (None, None, "none")


def test_explicit_section_constrains_range_pass():
    i = T.index("Tenant shall pay nothing")
    sp = Span("Tenant shall pay", i, i + 16, section_id="s2")
    r = ground(DOC, sp)
    assert r.method == "section" and r.section_id == "s2"
    check(r, sp)


def test_unknown_section_id_falls_back_to_offset_section():
    i = T.index("Tenant shall pay taxes")
    sp = Span("Tenant shall pay taxes.", i, i + 3, section_id="nope")
    r = ground(DOC, sp)
    check(r, sp)
    assert r.section_id == "s2"


def test_match_crossing_section_boundary_is_rejected():
    sp = Span("pay taxes. ARTICLE 3 TERM", P2, S3 + 14)
    r = ground(DOC, sp)
    assert not r.grounded


def test_curly_quotes_do_not_match_straight():
    r = ground(DOC, Span('The "Term" is ten years.', S3, len(T)))
    assert not r.grounded


def test_case_sensitive():
    assert not ground(DOC, Span("tenant shall pay taxes.", 0, S3)).grounded


def test_empty_span():
    r = ground(DOC, Span("   \n\u00a0", 0, 10))
    assert not r.grounded and r.reason == "empty_span"


def test_out_of_bounds_offsets_no_section():
    r = ground(DOC, Span("Tenant", len(T) + 5, len(T) + 10))
    assert not r.grounded and r.reason == "no_section"


def test_log_drop_appends_jsonl(tmp_path):
    p = tmp_path / "logs" / "dropped.jsonl"
    log_drop({"doc_id": "d", "reason": "not_found_in_section"}, p)
    log_drop({"doc_id": "d", "reason": "empty_span", "span_text": "“x”"}, p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["reason"] for x in lines] == ["not_found_in_section", "empty_span"]


def _quotes(n=200):
    """Nonempty quotes wholly inside one section, with whitespace runs re-spaced."""
    rng = random.Random(0)
    out = []
    while len(out) < n:
        sec = rng.choice(DOC.sections)
        a = rng.randrange(sec.char_start, sec.char_end)
        b = rng.randrange(a + 1, min(a + 60, sec.char_end) + 1)
        raw = T[a:b]
        if raw[0].isspace() or raw[-1].isspace():
            continue
        out.append((sec, a, b, " ".join(raw.split())))
    return out


@pytest.mark.parametrize("sec,a,b,quote", _quotes())
def test_property_true_range_grounds(sec, a, b, quote):
    r = ground(DOC, Span(quote, a, b, section_id=sec.id))
    assert r.grounded and r.method == "range"
    assert normalize_ws(T[r.char_start : r.char_end]) == quote
    assert sec.char_start <= r.char_start < r.char_end <= sec.char_end


@pytest.mark.parametrize("sec,a,b,quote", _quotes(50))
def test_property_fallback_stays_in_section(sec, a, b, quote):
    # A one-character range cannot contain a multi-character quote, so the range pass misses.
    if len(quote) < 2:
        pytest.skip("single-character quote")
    r = ground(DOC, Span(quote, sec.char_start, sec.char_start + 1, section_id=sec.id))
    assert r.grounded and r.method == "section"
    assert normalize_ws(T[r.char_start : r.char_end]) == quote
    assert sec.char_start <= r.char_start < r.char_end <= sec.char_end
