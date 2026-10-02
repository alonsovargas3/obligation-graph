"""Task 6: a run of table-of-contents entries becomes one "Table of Contents" section."""

from og.ingest import parse_html

Z = "0" * 64


def doc(html):
    return parse_html(html, "toc", Z)


def heads(d):
    return [(s.number, s.heading) for s in d.sections]


CC_STYLE = (
    "<p>Exhibit 10.41</p>"
    "<p>DATACENTER LEASE</p>"
    "<p>TABLE OF CONTENTS</p>"
    "<p>Page</p>"
    "<p>1. LEASE OF TENANT SPACE</p><p>1</p>"
    "<p>1.1 Tenant Space</p><p>1</p>"
    "<p>1.2 Condition of Tenant Space</p><p>1</p>"
    "<p>2. TERM</p><p>2</p>"
    "<p>2.1 Term</p><p>2</p>"
    "<p>1. LEASE OF TENANT SPACE</p>"
    "<p>Landlord leases the Tenant Space to Tenant.</p>"
    "<p>1.1 Tenant Space. Landlord leases to Tenant the Tenant Space.</p>"
    "<p>1.2 Condition of Tenant Space. Tenant accepts the space as is.</p>"
    "<p>2. TERM</p>"
    "<p>The Term is described below.</p>"
    "<p>2.1 Term. The Term is ten years.</p>"
)


def test_cc_style_toc_run_becomes_one_section():
    d = doc(CC_STYLE)
    assert heads(d) == [
        (None, "Preamble"),
        (None, "Table of Contents"),
        ("1", "LEASE OF TENANT SPACE"),
        ("1.1", "Tenant Space"),
        ("1.2", "Condition of Tenant Space"),
        ("2", "TERM"),
        ("2.1", "Term"),
    ]


def test_toc_section_starts_at_heading_and_ends_before_body():
    d = doc(CC_STYLE)
    toc = d.sections[1]
    body = d.text[toc.char_start : toc.char_end]
    assert body.startswith("TABLE OF CONTENTS\nPage\n1. LEASE OF TENANT SPACE\n1\n")
    assert body.rstrip("\n").endswith("2.1 Term\n2")
    assert d.text[toc.char_end :].startswith("1. LEASE OF TENANT SPACE\nLandlord leases")
    assert toc.article is None


def test_section_ids_stay_sequential_and_doc_validates():
    d = doc(CC_STYLE)
    d.validate()
    assert [s.id for s in d.sections] == [f"s{i:04d}" for i in range(len(d.sections))]


def test_toc_segments_belong_to_the_toc_section():
    d = doc(CC_STYLE)
    toc = d.sections[1]
    toc_lines = [d.segment_text(s.id) for s in d.segments if s.section_id == toc.id]
    assert toc_lines[0] == "TABLE OF CONTENTS"
    assert "1.1 Tenant Space" in toc_lines
    assert "Landlord leases the Tenant Space to Tenant." not in toc_lines


def test_toc_without_heading_line_starts_at_first_entry():
    html = (
        "<p>Intro text of the lease.</p>"
        "<p>1. RENT</p><p>3</p>"
        "<p>2. TERM</p><p>4</p>"
        "<p>3. USE</p><p>5</p>"
        "<p>1. RENT</p><p>Tenant shall pay rent.</p>"
        "<p>2. TERM</p><p>The term is ten years.</p>"
        "<p>3. USE</p><p>Tenant may use the space.</p>"
    )
    d = doc(html)
    assert heads(d) == [
        (None, "Preamble"),
        (None, "Table of Contents"),
        ("1", "RENT"),
        ("2", "TERM"),
        ("3", "USE"),
    ]
    toc = d.sections[1]
    assert d.text[toc.char_start :].startswith("1. RENT\n3\n")


def test_roman_page_references_count():
    html = (
        "<p>Intro.</p>"
        "<p>1. RECITALS</p><p>i</p>"
        "<p>2. DEFINITIONS</p><p>ii</p>"
        "<p>3. TERM</p><p>IV</p>"
        "<p>1. RECITALS</p><p>Body one.</p>"
        "<p>2. DEFINITIONS</p><p>Body two.</p>"
        "<p>3. TERM</p><p>Body three.</p>"
    )
    assert [h for _, h in heads(doc(html))] == [
        "Preamble",
        "Table of Contents",
        "RECITALS",
        "DEFINITIONS",
        "TERM",
    ]


def test_two_entry_run_is_not_a_toc():
    html = "<p>Intro.</p><p>1. Rent</p><p>3</p><p>2. Term</p><p>4</p><p>Body text.</p>"
    assert heads(doc(html)) == [(None, "Preamble"), ("1", "Rent"), ("2", "Term")]


def test_body_clause_followed_by_digit_table_cell_is_not_a_toc():
    html = (
        "<p>Intro.</p>"
        "<table><tr><td>3.1 Base Rent. Tenant shall pay rent.</td></tr>"
        "<tr><td>5</td></tr></table>"
        "<p>3.2 Taxes. Tenant pays taxes.</p>"
        "<p>Tenant pays all taxes when due.</p>"
    )
    assert heads(doc(html)) == [(None, "Preamble"), ("3.1", "Base Rent"), ("3.2", "Taxes")]


def test_consecutive_body_clauses_without_page_lines_are_not_a_toc():
    html = (
        "<p>Intro.</p>"
        "<p>1. Rent. Tenant shall pay rent.</p>"
        "<p>2. Term. The term is ten years.</p>"
        "<p>3. Use. Tenant may use the space.</p>"
        "<p>4. Notices. Notices go to the addresses below.</p>"
    )
    assert heads(doc(html)) == [
        (None, "Preamble"),
        ("1", "Rent"),
        ("2", "Term"),
        ("3", "Use"),
        ("4", "Notices"),
    ]


def test_no_toc_leaves_wave1_sections_unchanged():
    html = (
        "<p>ARTICLE 2 RENT</p>"
        "<p>2.1 Tenant shall pay Base Rent.</p>"
        "<p>2.2 Tenant shall pay Additional Rent.</p>"
    )
    assert heads(doc(html)) == [
        ("2", "RENT"),
        ("2.1", "Tenant shall pay Base Rent"),
        ("2.2", "Tenant shall pay Additional Rent"),
    ]
