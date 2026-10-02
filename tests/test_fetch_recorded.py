"""Recorded test against the real TeraWulf filing index (fetched once, verbatim).

The synthetic fixture in filing_index.htm pins the parser contract; this file
pins that the contract holds on the live EDGAR layout.
"""

from pathlib import Path

from og import fetch

INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/1083301/000110465925078084/"
    "0001104659-25-078084-index.htm"
)
RECORDED = Path(__file__).parent / "fixtures" / "fetch" / "terawulf_index.htm"


def test_resolve_exhibit_from_recorded_real_index():
    html = RECORDED.read_text(encoding="utf-8")
    assert (
        fetch.resolve_exhibit(html, INDEX_URL, "10.1")
        == "https://www.sec.gov/Archives/edgar/data/1083301/000110465925078084/"
        "tm2523008d2_ex10-1.htm"
    )
