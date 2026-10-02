import hashlib
from pathlib import Path

import httpx
import pytest
import yaml

from og import fetch

BODY = b"<html><body>EXHIBIT 10.1 FORM OF RECOGNITION AGREEMENT</body></html>"
BASE = "https://www.sec.gov/Archives/edgar/data/1/2"
INDEX_URL = f"{BASE}/0000000000-25-000002-index.htm"
INDEX_HTML = (Path(__file__).parent / "fixtures" / "fetch" / "filing_index.htm").read_text()
UA = "og test a@b.co"


class CountingLimiter(fetch.RateLimiter):
    def __init__(self):
        super().__init__(5, clock=lambda: 0.0, sleep=lambda s: None)
        self.waits = 0

    def wait(self):
        self.waits += 1


def write_sources(tmp_path, docs):
    p = tmp_path / "sources.yaml"
    p.write_text(yaml.safe_dump({"documents": docs}))
    return p


def doc(tmp_path, id="d1", sha=None, url=f"{BASE}/ex10-1.htm", **extra):
    return {
        "id": id,
        "url": url,
        "exhibit": "10.1",
        "local_path": str(tmp_path / "raw" / f"{id}.htm"),
        "sha256": sha,
        **extra,
    }


def run(path, handler, limiter=None):
    return fetch.fetch_all(
        path, transport=httpx.MockTransport(handler), limiter=limiter or CountingLimiter()
    )


@pytest.fixture
def ua(monkeypatch):
    monkeypatch.setenv("OG_EDGAR_USER_AGENT", UA)


def test_requires_user_agent(tmp_path, monkeypatch):
    monkeypatch.delenv("OG_EDGAR_USER_AGENT", raising=False)
    with pytest.raises(SystemExit, match="OG_EDGAR_USER_AGENT"):
        run(write_sources(tmp_path, [doc(tmp_path)]), lambda r: httpx.Response(200))


def test_user_agent_needs_email(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_EDGAR_USER_AGENT", "no contact here")
    with pytest.raises(SystemExit, match="email"):
        run(write_sources(tmp_path, [doc(tmp_path)]), lambda r: httpx.Response(200))


def test_fetch_writes_file_and_sha(tmp_path, ua):
    seen = {}

    def h(req):
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, content=BODY)

    p = write_sources(tmp_path, [doc(tmp_path)])
    run(p, h)
    assert seen["ua"] == UA
    assert (tmp_path / "raw" / "d1.htm").read_bytes() == BODY
    assert (
        yaml.safe_load(p.read_text())["documents"][0]["sha256"] == hashlib.sha256(BODY).hexdigest()
    )


def test_sha_mismatch_fails_and_writes_nothing(tmp_path, ua):
    p = write_sources(tmp_path, [doc(tmp_path, sha="0" * 64)])
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        run(p, lambda r: httpx.Response(200, content=BODY))
    assert not (tmp_path / "raw" / "d1.htm").exists()


def test_skips_existing_matching_file(tmp_path, ua):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "d1.htm").write_bytes(BODY)
    p = write_sources(tmp_path, [doc(tmp_path, sha=hashlib.sha256(BODY).hexdigest())])

    def h(req):
        raise AssertionError("should not hit network")

    run(p, h)


def test_corrupted_cached_file_is_refetched(tmp_path, ua):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "d1.htm").write_bytes(b"corrupted")
    p = write_sources(tmp_path, [doc(tmp_path, sha=hashlib.sha256(BODY).hexdigest())])
    run(p, lambda r: httpx.Response(200, content=BODY))
    assert (raw / "d1.htm").read_bytes() == BODY


def test_http_error_names_the_document(tmp_path, ua):
    p = write_sources(tmp_path, [doc(tmp_path)])
    with pytest.raises(SystemExit, match="d1"):
        run(p, lambda r: httpx.Response(404))


def test_partial_failure_keeps_completed_pins(tmp_path, ua):
    p = write_sources(
        tmp_path,
        [doc(tmp_path, "ok", url=f"{BASE}/ok.htm"), doc(tmp_path, "bad", url=f"{BASE}/bad.htm")],
    )

    def h(req):
        return (
            httpx.Response(200, content=BODY)
            if req.url.path.endswith("ok.htm")
            else httpx.Response(500)
        )

    with pytest.raises(SystemExit):
        run(p, h)
    docs = {d["id"]: d for d in yaml.safe_load(p.read_text())["documents"]}
    assert docs["ok"]["sha256"] == hashlib.sha256(BODY).hexdigest()
    assert docs["bad"]["sha256"] is None


def test_rate_limiter_spacing():
    t = [0.0]

    def sleep(s):
        t[0] += s

    rl = fetch.RateLimiter(5, clock=lambda: t[0], sleep=sleep)
    starts = []
    for _ in range(4):
        rl.wait()
        starts.append(round(t[0], 9))
    assert starts == [0.0, 0.2, 0.4, 0.6]


@pytest.mark.parametrize("rate", [0, -1, 11])
def test_rate_limiter_rejects_invalid_rates(rate):
    with pytest.raises(ValueError):
        fetch.RateLimiter(rate)


def test_every_request_including_redirects_is_rate_limited(tmp_path, ua):
    def h(req):
        if req.url.path.endswith("old.htm"):
            return httpx.Response(301, headers={"Location": f"{BASE}/new.htm"})
        return httpx.Response(200, content=BODY)

    limiter = CountingLimiter()
    run(write_sources(tmp_path, [doc(tmp_path, url=f"{BASE}/old.htm")]), h, limiter)
    assert limiter.waits == 2


def test_resolve_missing_url_from_filing_index(tmp_path, ua):
    d = doc(tmp_path, url=None, filing_index_url=INDEX_URL, filing_date=None)
    p = write_sources(tmp_path, [d])

    def h(req):
        if str(req.url) == INDEX_URL:
            return httpx.Response(200, text=INDEX_HTML)
        assert str(req.url) == (
            "https://www.sec.gov/Archives/edgar/data/1083301/000110465925078084/"
            "tm2523008d2_ex10-1.htm"
        )
        return httpx.Response(200, content=BODY)

    run(p, h)
    out = yaml.safe_load(p.read_text())["documents"][0]
    assert out["url"].endswith("tm2523008d2_ex10-1.htm")
    assert out["filing_date"] == "2025-08-14"
    assert out["sha256"] == hashlib.sha256(BODY).hexdigest()


def row(type_, href):
    link = f'<td><a href="{href}">f</a></td>'
    return f"<table><tr><td>2</td><td>X</td>{link}<td>{type_}</td></tr></table>"


@pytest.mark.parametrize(
    "href,expected",
    [
        ("/Archives/edgar/data/1/2/ex.htm", f"{BASE}/ex.htm"),
        ("ex.htm", f"{BASE}/ex.htm"),
        (f"{BASE}/ex.htm", f"{BASE}/ex.htm"),
    ],
)
def test_resolve_exhibit_url_forms(href, expected):
    assert fetch.resolve_exhibit(row("EX-10.1", href), INDEX_URL, "10.1") == expected


def test_resolve_exhibit_from_fixture():
    url = fetch.resolve_exhibit(INDEX_HTML, INDEX_URL, "10.1")
    assert url.endswith("/000110465925078084/tm2523008d2_ex10-1.htm")


def test_resolve_exhibit_absent():
    with pytest.raises(SystemExit, match="not found"):
        fetch.resolve_exhibit(INDEX_HTML, INDEX_URL, "10.2")


def test_resolve_exhibit_does_not_prefix_match():
    with pytest.raises(SystemExit, match="not found"):
        fetch.resolve_exhibit(row("EX-10.10", "ex.htm"), INDEX_URL, "10.1")


def test_resolve_exhibit_ambiguous():
    html = row("EX-10.1", "a.htm") + row("EX-10.1", "b.htm")
    with pytest.raises(SystemExit, match="ambiguous"):
        fetch.resolve_exhibit(html, INDEX_URL, "10.1")


def test_resolve_exhibit_rejects_non_sec_host():
    with pytest.raises(SystemExit, match="sec.gov"):
        fetch.resolve_exhibit(row("EX-10.1", "https://evil.example/ex.htm"), INDEX_URL, "10.1")


def test_parse_filing_date():
    assert fetch.parse_filing_date(INDEX_HTML) == "2025-08-14"
    assert fetch.parse_filing_date("<html></html>") is None
