import hashlib
from pathlib import Path

import pytest

from og.ingest import ingest_file, parse_html

FIX = Path(__file__).parent / "fixtures" / "ingest"
Z = "0" * 64

LEASE_TEXT = "\n".join(
    [
        "EXHIBIT 10.1",
        "This LEASE AGREEMENT is made between Landlord Co (“Landlord”) and Tenant Co.",
        "ARTICLE 1",
        "DEFINITIONS",
        "1.1 “Commencement Date” means [●].",
        "ARTICLE 2 RENT",
        "2.1 Tenant shall pay Base Rent of $[***] per month.",
        "2.2 Tenant shall pay\u00a0Additional Rent within thirty (30) days after invoice.",
        "Site | Building A",
        "Capacity | [●] MW",
        "ARTICLE 3 TERM",
        "3.1 The Term is ten (10) years.",
    ]
)


def lease():
    return parse_html((FIX / "lease_small.htm").read_text(encoding="utf-8"), "lease_small", Z)


def test_exact_text():
    assert lease().text == LEASE_TEXT


def test_validates():
    lease().validate()


def test_sections_flat_finest_numbered_level():
    got = [(s.id, s.number, s.article) for s in lease().sections]
    assert got == [
        ("s0000", None, None),
        ("s0001", "1", "DEFINITIONS"),
        ("s0002", "1.1", "DEFINITIONS"),
        ("s0003", "2", "RENT"),
        ("s0004", "2.1", "RENT"),
        ("s0005", "2.2", "RENT"),
        ("s0006", "3", "TERM"),
        ("s0007", "3.1", "TERM"),
    ]


def test_section_headings():
    by_number = {s.number: s.heading for s in lease().sections}
    assert by_number[None] == "Preamble"
    assert by_number["1"] == "DEFINITIONS"
    assert by_number["2"] == "RENT"
    assert by_number["2.1"] == "Tenant shall pay Base Rent of $[***] per month"


def test_section_offsets_start_at_heading_lines():
    d = lease()
    for s in d.sections[1:]:
        assert d.text[s.char_start - 1] == "\n"
    assert d.sections[-1].char_end == len(d.text)
    assert d.section_for(d.text.index("Building A")).number == "2.2"


def test_segments_are_lines():
    d = lease()
    assert [d.segment_text(s.id) for s in d.segments] == LEASE_TEXT.split("\n")
    assert [s.id for s in d.segments] == [f"p{i:04d}" for i in range(1, 13)]
    seg = d.segments[6]
    assert (seg.section_id, seg.page) == ("s0004", 1)


def test_pages_from_page_break_before_style():
    d = lease()
    assert [(p.page, p.char_start) for p in d.pages] == [(1, 0), (2, d.text.index("ARTICLE 3"))]
    assert d.pages[-1].char_end == len(d.text)


def test_page_markers_after_hr_and_edges():
    d = parse_html((FIX / "pages_mixed.htm").read_text(encoding="utf-8"), "pm", Z)
    assert d.text == "Alpha line.\nBravo line.\nCharlie line.\nDelta line."
    assert [(p.page, p.char_start) for p in d.pages] == [
        (1, 0),
        (2, d.text.index("Charlie")),
        (3, d.text.index("Delta")),
    ]


def test_no_page_markers_single_page_and_preamble():
    d = parse_html((FIX / "no_breaks.htm").read_text(encoding="utf-8"), "nb", Z)
    assert [p.page for p in d.pages] == [1]
    assert [(s.id, s.heading) for s in d.sections] == [("s0000", "Preamble")]
    assert len(d.segments) == 3


def test_script_and_head_excluded():
    t = lease().text
    assert "HIDDEN" not in t and "ex10-1" not in t and "margin" not in t


def test_deterministic():
    assert lease().to_json() == lease().to_json()


def test_ingest_file_verifies_sha(tmp_path):
    raw = (FIX / "lease_small.htm").read_bytes()
    d = ingest_file(FIX / "lease_small.htm", "lease_small", hashlib.sha256(raw).hexdigest())
    assert d.text == LEASE_TEXT
    assert d.source_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("sha", [None, "", Z])
def test_ingest_file_refuses_missing_or_wrong_sha(sha):
    with pytest.raises(ValueError):
        ingest_file(FIX / "lease_small.htm", "lease_small", sha)


def test_pdf_not_supported_yet(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    with pytest.raises(NotImplementedError):
        ingest_file(p, "x", hashlib.sha256(b"%PDF-1.4").hexdigest())


def test_inline_and_loose_page_markers_flush_the_line():
    d = parse_html((FIX / "inline_breaks.htm").read_text(encoding="utf-8"), "ib", Z)
    assert d.text == "Alpha\nBravo\nCharlie\nDelta end.\nEcho Foxtrot\ngolf."
    assert [p.char_start for p in d.pages] == [
        0,
        d.text.index("Bravo"),
        d.text.index("Delta"),
        d.text.index("golf."),
    ]
    assert [d.segment_text(s.id) for s in d.segments] == d.text.split("\n")


def _sections(html):
    return [(s.number, s.heading, s.article) for s in parse_html(html, "x", Z).sections]


def test_article_title_does_not_swallow_a_section_heading():
    html = "<p>ARTICLE 1</p><p>SECTION 2 RENT</p><p>Body text.</p>"
    assert _sections(html) == [("1", "", None), ("2", "RENT", None)]


def test_consecutive_articles_and_uppercase_title():
    html = "<p>ARTICLE 1</p><p>ARTICLE 2</p><p>TERMS</p><p>Body text.</p>"
    assert _sections(html) == [("1", "", None), ("2", "TERMS", "TERMS")]


def test_uppercase_numbered_clause_is_not_an_article_title():
    html = "<p>ARTICLE 3</p><p>3.1 RENT.</p><p>Body text.</p>"
    assert _sections(html) == [("3", "", None), ("3.1", "RENT", None)]


def test_single_level_numbered_clauses():
    html = (
        "<p>AGREEMENT</p><p>1. Definitions. Terms mean things.</p><p>Body.</p>"
        "<p>2.Suite 409 Extension Term.</p><p>14. Taxes.</p>"
    )
    assert _sections(html) == [
        (None, "Preamble", None),
        ("1", "Definitions", None),
        ("2", "Suite 409 Extension Term", None),
        ("14", "Taxes", None),
    ]


def test_number_like_lines_are_not_clauses():
    html = (
        "<p>Intro.</p><p>(1) If Google elects.</p><p>2025. Tenant shall pay.</p>"
        "<p>3. and then lower.</p><p>1.25 | $100.00</p><p>4.5 million dollars</p>"
    )
    assert _sections(html) == [(None, "Preamble", None)]


def test_clause_number_in_its_own_table_cell():
    html = (
        "<table><tr><td>1.1</td><td>In this Agreement, words mean things.</td></tr>"
        "<tr><td>1.25</td><td>$100.00</td></tr></table>"
    )
    assert _sections(html) == [("1.1", "In this Agreement, words mean things", None)]
