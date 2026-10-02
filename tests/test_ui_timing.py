"""Wave 5 Task 42: UI server and page show timing (plan rev 2 W5-1/W5-6, rev 2.1).

The JSON endpoints still return exactly og.query's dicts, now with timing; the page has
a timing column and a timing section in the clause panel, explains the pending kinds,
and renders a strict `lt` bound as "before", never as a due-on date.
"""

import json
import re
import shutil
import sqlite3
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from test_ui_server import get, roundtrip
from timing_fixture import SCHEDULED, TEXT, timed_v5

from og import query

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "index.html"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    timed_v5(root / "data" / "graph.db")
    shutil.copytree(TEXT, root / "data" / "text")
    shutil.copy(ROOT / "data" / "sources.yaml", root / "data" / "sources.yaml")
    (root / "ui").mkdir()
    if PAGE.exists():
        shutil.copy(PAGE, root / "ui" / "index.html")
    monkeypatch.setenv("OG_WORKSPACE", str(root))
    return root


@pytest.fixture
def expected_con(tmp_path):
    path, _ = timed_v5(tmp_path / "expected.db")
    con = sqlite3.connect(path, isolation_level=None)
    yield con
    con.close()


@pytest.fixture
def base_url(ws):
    from og.ui.server import make_handler

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler())
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_obligations_endpoint_carries_timing(base_url, expected_con):
    status, _, body = get(f"{base_url}/api/obligations?lifecycle=scheduled&limit=50")
    assert status == 200
    out = json.loads(body)
    assert out == roundtrip(query.get_obligations(expected_con, lifecycle="scheduled", limit=50))
    assert {o["id"] for o in out["obligations"]} == set(SCHEDULED)
    assert all(o["deadline"] is not None for o in out["obligations"])


def test_deadlines_endpoint_carries_contingent(base_url, expected_con):
    status, _, body = get(f"{base_url}/api/deadlines?as_of=2010-12-15&days=90&limit=50")
    assert status == 200
    out = json.loads(body)
    expected = query.upcoming_deadlines(expected_con, as_of="2010-12-15", days=90, limit=50)
    assert out == roundtrip(expected)
    assert "contingent" in out and "contingent_total" in out


@pytest.fixture
def html():
    assert PAGE.exists(), "ui/index.html is missing"
    return PAGE.read_text(encoding="utf-8")


@pytest.mark.parametrize("element_id", ["col-timing", "clause-timing"])
def test_timing_element_ids(html, element_id):
    assert re.search(rf"""id\s*=\s*["']{re.escape(element_id)}["']""", html), element_id


@pytest.mark.parametrize("phrase", ["contingent", "unresolved", "no stated deadline"])
def test_page_explains_pending_kinds(html, phrase):
    assert phrase in html.lower(), phrase


def test_strict_bound_reads_as_before(html):
    """The relation code "lt" is rendered with the word "before" (a strict bound is never
    shown as a due-on date)."""
    for m in re.finditer(r"""["']lt["']""", html):
        window = html[max(0, m.start() - 200) : m.end() + 200]
        if "before" in window.lower():
            return
    pytest.fail('no "lt" relation rendered as "before" in ui/index.html')


def test_timing_text_is_rendered_as_text_not_html(html):
    assert "textContent" in html
    for m in re.finditer(r"\.innerHTML\s*=\s*([^;\n]*)", html):
        assert m.group(1).strip() in ('""', "''", "``"), m.group(0)
    assert chr(0x2014) not in html
