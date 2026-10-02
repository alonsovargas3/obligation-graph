import pytest

from og.textdoc import Page, Section, Segment, TextDoc

TEXT = "ARTICLE 1 RENT\n1.1 Tenant shall pay Rent.\nARTICLE 2 TERM\n2.1 The Term is ten years."
S2 = TEXT.index("ARTICLE 2")


def make_doc() -> TextDoc:
    return TextDoc(
        doc_id="d1",
        source_sha256="0" * 64,
        text=TEXT,
        sections=[
            Section("s0001", "1", "RENT", 0, S2, "RENT"),
            Section("s0002", "2", "TERM", S2, len(TEXT), "TERM"),
        ],
        pages=[Page(1, 0, len(TEXT))],
        segments=[
            Segment("p0001", "s0001", 1, 0, TEXT.index("\n")),
            Segment("p0002", "s0001", 1, TEXT.index("1.1"), TEXT.index("Rent.") + 5),
            Segment("p0003", "s0002", 1, S2, TEXT.index("\n2.1")),
            Segment("p0004", "s0002", 1, TEXT.index("2.1"), len(TEXT)),
        ],
    )


def test_lookups():
    d = make_doc()
    assert d.section_for(TEXT.index("Tenant")).id == "s0001"
    assert d.section_for(TEXT.index("Term is")).id == "s0002"
    assert d.section_for(len(TEXT)) is None
    assert d.section_by_id("s0002").heading == "TERM"
    assert d.section_by_id("nope") is None
    assert d.page_for(5) == 1
    assert d.segment_text("p0002") == "1.1 Tenant shall pay Rent."
    with pytest.raises(KeyError):
        d.segment("p9999")


def test_valid_doc_validates():
    make_doc().validate()


def test_roundtrip_json(tmp_path):
    d = make_doc()
    p = tmp_path / "d1.json"
    d.save(p)
    assert TextDoc.load(p) == d


def test_load_validates(tmp_path):
    d = make_doc()
    d.segments.append(Segment("p0005", "s0002", 1, 0, len(TEXT) + 1))
    p = tmp_path / "bad.json"
    p.write_text(d.to_json(), encoding="utf-8")
    with pytest.raises(ValueError):
        TextDoc.load(p)


def test_empty_segments_allowed():
    d = make_doc()
    d.segments = []
    d.validate()


@pytest.mark.parametrize(
    "mutate",
    [
        # segment out of bounds
        lambda d: d.segments.append(Segment("p0005", "s0002", 1, 0, len(TEXT) + 1)),
        # duplicate segment id
        lambda d: d.segments.append(Segment("p0001", "s0002", 1, S2, S2 + 3)),
        # overlapping sections
        lambda d: d.sections.__setitem__(1, Section("s0002", "2", "TERM", 3, len(TEXT), "TERM")),
        # gap between sections (coverage)
        lambda d: d.sections.__setitem__(
            1, Section("s0002", "2", "TERM", S2 + 2, len(TEXT), "TERM")
        ),
        # duplicate section id
        lambda d: d.sections.__setitem__(1, Section("s0001", "2", "TERM", S2, len(TEXT), "TERM")),
        # zero-length section
        lambda d: d.sections.insert(1, Section("s0009", "9", "X", S2, S2, None)),
        # pages do not cover the text
        lambda d: d.pages.__setitem__(0, Page(1, 0, len(TEXT) - 1)),
        # duplicate page number
        lambda d: d.pages.extend([Page(1, len(TEXT), len(TEXT))]),
        # segment section_id disagrees with its offsets
        lambda d: d.segments.__setitem__(
            3, Segment("p0004", "s0001", 1, TEXT.index("2.1"), len(TEXT))
        ),
        # segment page that does not exist
        lambda d: d.segments.__setitem__(
            3, Segment("p0004", "s0002", 9, TEXT.index("2.1"), len(TEXT))
        ),
        # overlapping segments
        lambda d: d.segments.__setitem__(
            1, Segment("p0002", "s0001", 1, 2, TEXT.index("Rent.") + 5)
        ),
        # empty segment
        lambda d: d.segments.append(Segment("p0005", "s0002", 1, S2, S2)),
        # segment crossing a section boundary
        lambda d: d.segments.__setitem__(
            1, Segment("p0002", "s0001", 1, TEXT.index("1.1"), S2 + 3)
        ),
        # unknown section reference
        lambda d: d.segments.__setitem__(
            3, Segment("p0004", "s0042", 1, TEXT.index("2.1"), len(TEXT))
        ),
    ],
)
def test_validate_rejects(mutate):
    d = make_doc()
    mutate(d)
    with pytest.raises(ValueError):
        d.validate()
