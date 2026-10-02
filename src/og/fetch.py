"""Corpus fetch: download EDGAR exhibits listed in data/sources.yaml, pin by sha256.

EDGAR requires a descriptive User-Agent with a contact email; it is read from
OG_EDGAR_USER_AGENT at fetch time, never hardcoded. One shared rate limiter
applies to every request, index pages and redirects included.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv

SOURCES_PATH = "data/sources.yaml"


class RateLimiter:
    """Sleep so consecutive wait() calls start at least 1/rate apart. The first call is free."""

    def __init__(
        self,
        rate_per_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 < rate_per_s <= 10:
            raise ValueError(f"rate must be in (0, 10] requests per second, got {rate_per_s}")
        self._interval = 1.0 / rate_per_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            target = self._last + self._interval
            now = self._clock()
            if now < target:
                self._sleep(target - now)
        self._last = self._clock()


def user_agent() -> str:
    ua = os.environ.get("OG_EDGAR_USER_AGENT", "").strip()
    if not ua:
        raise SystemExit(
            "OG_EDGAR_USER_AGENT is not set; EDGAR requires a descriptive User-Agent"
            " with a contact email"
        )
    if "@" not in ua:
        raise SystemExit("OG_EDGAR_USER_AGENT must contain a contact email address")
    return ua


def parse_filing_date(index_html: str) -> str | None:
    """Return the Filing Date from an EDGAR filing index page, or None."""
    soup = BeautifulSoup(index_html, "lxml")
    for head in soup.find_all("div", class_="infoHead"):
        if head.get_text(strip=True) == "Filing Date":
            info = head.find_next_sibling("div", class_="info")
            if info is not None:
                return info.get_text(strip=True)
    return None


def _type_column(soup: BeautifulSoup) -> int:
    """Index of the Type column, taken from the header row when one exists.

    EDGAR document tables are Seq, Description, Document, Type, Size, so 3 is
    the default when no header row names the columns.
    """
    for tr in soup.find_all("tr"):
        headers = tr.find_all("th")
        if not headers:
            continue
        for i, th in enumerate(headers):
            if th.get_text(strip=True).strip().lower() == "type":
                return i
        return 3
    return 3


def resolve_exhibit(index_html: str, index_url: str, exhibit: str) -> str:
    """Resolve the document URL for `exhibit` (e.g. "10.1") from a filing index page.

    Only rows whose Type cell equals EX-<exhibit> exactly match; EX-10.10 is
    not EX-10.1. Zero matches and multiple matches are both fatal.
    """
    soup = BeautifulSoup(index_html, "lxml")
    want = f"EX-{exhibit}".upper()
    type_idx = _type_column(soup)
    matches = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) > type_idx and cells[type_idx].get_text(strip=True).strip().upper() == want:
            matches.append(tr)
    label = f"EX-{exhibit}"
    if not matches:
        raise SystemExit(f"exhibit {label} not found in filing index {index_url}")
    if len(matches) > 1:
        raise SystemExit(
            f"exhibit {label} ambiguous in filing index {index_url}: {len(matches)} rows"
        )
    link = matches[0].find("a", href=True)
    if link is None:
        raise SystemExit(f"exhibit {label} row has no document link in {index_url}")
    url = urljoin(index_url, link["href"])
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.sec.gov":
        raise SystemExit(f"resolved exhibit URL is not on https://www.sec.gov: {url}")
    return url


def fetch_all(
    sources_path: str | Path = SOURCES_PATH,
    *,
    transport: httpx.BaseTransport | None = None,
    limiter: RateLimiter | None = None,
) -> list[dict]:
    """Fetch every document in sources.yaml, writing bytes and pins atomically.

    Each completed document updates its sha256 pin and rewrites sources.yaml,
    so pins from earlier documents survive a later failure.
    """
    sources_path = Path(sources_path)
    ua = user_agent()
    limiter = limiter if limiter is not None else RateLimiter(5)
    sources = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    documents: list[dict] = sources.get("documents") or []
    with httpx.Client(
        transport=transport,
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": ua},
        event_hooks={"request": [lambda request: limiter.wait()]},
    ) as client:
        for doc in documents:
            _fetch_document(client, doc, sources_path, sources)
    return documents


def _fetch_document(client: httpx.Client, doc: dict, sources_path: Path, sources: dict) -> None:
    doc_id = doc.get("id", "<no id>")
    if not doc.get("url"):
        index_url = doc.get("filing_index_url")
        if not index_url:
            raise SystemExit(f"document {doc_id} has neither url nor filing_index_url")
        index_html = _get(client, index_url, doc_id).text
        doc["url"] = resolve_exhibit(index_html, index_url, str(doc.get("exhibit", "")))
        doc["filing_date"] = parse_filing_date(index_html)

    local = Path(doc["local_path"])
    pin = doc.get("sha256")
    if pin and local.is_file() and _file_sha256(local) == pin:
        return  # already downloaded and pinned; no network

    content = _get(client, doc["url"], doc_id).content
    digest = hashlib.sha256(content).hexdigest()
    if pin and pin != digest:
        raise SystemExit(f"sha256 mismatch for {doc_id}: pinned {pin}, fetched {digest}")
    _atomic_write(local, content)
    doc["sha256"] = digest
    _atomic_dump(sources_path, sources)


def _get(client: httpx.Client, url: str, doc_id: str) -> httpx.Response:
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SystemExit(f"fetch failed for {doc_id}: {url}: {exc}") from None
    return response


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _atomic_dump(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def main() -> None:
    load_dotenv()
    for doc in fetch_all():
        print(f"{doc.get('id')} {doc.get('sha256')}")


if __name__ == "__main__":
    main()
