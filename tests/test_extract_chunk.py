import re

from extract_fakes import build_doc, filler

from og.extract.chunk import chunk_doc

LINE = re.compile(r"^\[(p\d{4})\] ", re.M)
CTX = re.compile(r"^\[ctx (p\d{4})\] ", re.M)


def doc_with_toc():
    return build_doc(
        [
            (
                None,
                "Preamble",
                ["This LEASE is made between Landlord Co and Tenant Co.", "Recitals."],
            ),
            (None, "Table of Contents", ["1.1 Rent", "1", "1.2 Term", "2", "1.3 Notices", "3"]),
            ("1.1", "Rent", [filler("r", 300), filler("s", 300)]),
            ("1.2", "Term", [filler("t", 300)]),
            ("1.3", "Notices", [filler("n", 300), filler("m", 300)]),
        ]
    )


def all_ids(chunks):
    return [sid for c in chunks for sid in c.segment_ids]


def test_deterministic():
    d = doc_with_toc()
    assert chunk_doc(d, max_chars=800) == chunk_doc(d, max_chars=800)


def test_chunk_ids_and_doc_id():
    chunks = chunk_doc(doc_with_toc(), max_chars=800)
    assert [c.chunk_id for c in chunks] == [f"c{i:04d}" for i in range(1, len(chunks) + 1)]
    assert {c.doc_id for c in chunks} == {"d1"}


def test_every_non_toc_segment_exactly_once_in_order():
    d = doc_with_toc()
    toc = {s.id for s in d.sections if s.heading == "Table of Contents"}
    expected = [s.id for s in d.segments if s.section_id not in toc]
    for cap in (200, 800, 12000):
        assert all_ids(chunk_doc(d, max_chars=cap)) == expected


def test_toc_segments_never_rendered():
    d = doc_with_toc()
    toc_ids = {s.id for s in d.segments if s.section_id == "s0001"}
    for c in chunk_doc(d, max_chars=800):
        rendered = set(LINE.findall(c.text)) | set(CTX.findall(c.text))
        assert not rendered & toc_ids


def test_lines_rendered_with_ids():
    d = doc_with_toc()
    for c in chunk_doc(d, max_chars=800):
        for sid in c.segment_ids:
            assert f"[{sid}] {d.segment_text(sid)}\n" in c.text
        assert LINE.findall(c.text) == c.segment_ids


def test_one_chunk_when_everything_fits():
    chunks = chunk_doc(doc_with_toc())
    assert len(chunks) == 1
    assert "CONTEXT" not in chunks[0].text
    assert not CTX.findall(chunks[0].text)


def test_context_block_only_after_first_chunk():
    d = doc_with_toc()
    chunks = chunk_doc(d, max_chars=800)
    assert len(chunks) >= 3
    assert not CTX.findall(chunks[0].text)
    for c in chunks[1:]:
        assert c.text.startswith("CONTEXT (do not extract)")
        ctx_ids = CTX.findall(c.text)
        assert ctx_ids and ctx_ids[0] == "p0001"
        assert not set(ctx_ids) & set(c.segment_ids)
        for sid in ctx_ids:
            assert f"[ctx {sid}] {d.segment_text(sid)}\n" in c.text


def test_context_is_leading_segments_capped_at_1500_chars():
    long_pre = [filler("a", 700), filler("b", 700), filler("c", 700)]
    d = build_doc([(None, "Preamble", long_pre), ("1.1", "Rent", [filler("r", 900)])])
    chunks = chunk_doc(d, max_chars=2500)
    later = chunks[-1]
    ctx = CTX.findall(later.text)
    assert ctx[0] == "p0001"
    assert sum(len(d.segment_text(s)) for s in ctx) <= 1500 or len(ctx) == 1


def test_sections_not_split_when_they_fit():
    d = doc_with_toc()
    chunks = chunk_doc(d, max_chars=800)
    where = {sid: c.chunk_id for c in chunks for sid in c.segment_ids}
    for sec in d.sections:
        ids = [s.id for s in d.segments if s.section_id == sec.id and s.id in where]
        size = sum(len(d.segment_text(s)) + 8 for s in ids)
        if ids and size < 500:
            assert len({where[s] for s in ids}) == 1


def test_soft_cap_respected_except_single_oversize_segment():
    d = doc_with_toc()
    for c in chunk_doc(d, max_chars=800):
        assert len(c.text) <= 800 or len(c.segment_ids) == 1


def test_oversize_segment_is_its_own_chunk():
    big = filler("x", 3000)
    d = build_doc(
        [(None, "Preamble", ["Intro line."]), ("1.1", "Rent", ["Short one.", big, "Short two."])]
    )
    chunks = chunk_doc(d, max_chars=1000)
    big_id = next(s.id for s in d.segments if d.segment_text(s.id) == big)
    owner = next(c for c in chunks if big_id in c.segment_ids)
    assert owner.segment_ids == [big_id]
    assert all_ids(chunks) == [s.id for s in d.segments]


def test_large_section_splits_at_segment_boundaries():
    lines = [filler(f"k{i}", 250) for i in range(8)]
    d = build_doc([(None, "Preamble", ["Intro."]), ("2.1", "Long", lines)])
    chunks = chunk_doc(d, max_chars=900)
    assert len(chunks) > 2
    assert all_ids(chunks) == [s.id for s in d.segments]
