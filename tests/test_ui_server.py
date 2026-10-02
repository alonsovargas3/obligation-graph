"""Task 32: the local UI server (wave 4 plan Task 32, rev 2 W4-10/14).

GET-only JSON endpoints that return exactly og.query's dicts, plus the page.
The real graph fixture is copied into a temporary workspace (OG_WORKSPACE).
"""

import inspect
import json
import shutil
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from og import query
from og.store.db import connect

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "graph"
A3 = "endurance-2017-ex106"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    shutil.copy(FIX / "real_v5.db", root / "data" / "graph.db")
    shutil.copytree(FIX / "text", root / "data" / "text")
    shutil.copy(ROOT / "data" / "sources.yaml", root / "data" / "sources.yaml")
    (root / "ui").mkdir()
    page = ROOT / "ui" / "index.html"
    if page.exists():
        shutil.copy(page, root / "ui" / "index.html")
    monkeypatch.setenv("OG_WORKSPACE", str(root))
    return root


@pytest.fixture
def expected_con(tmp_path):
    path = tmp_path / "expected.db"
    shutil.copy(FIX / "real_v5.db", path)
    con = connect(path)
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


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get("Content-Type", ""), err.read()


def request(url, method):
    req = urllib.request.Request(url, method=method, data=b"{}" if method != "DELETE" else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code


def roundtrip(value):
    return json.loads(json.dumps(value))


def test_root_serves_the_page(base_url, ws):
    status, ctype, body = get(base_url + "/")
    assert status == 200
    assert ctype.startswith("text/html")
    assert body == (ws / "ui" / "index.html").read_bytes()


def test_agreements_endpoint_equals_query(base_url, expected_con):
    status, ctype, body = get(base_url + "/api/agreements")
    assert status == 200 and ctype.startswith("application/json")
    assert json.loads(body) == roundtrip(query.list_agreements(expected_con))


def test_obligations_endpoint_maps_params_one_to_one(base_url, expected_con):
    url = (
        base_url + "/api/obligations?party=landlord&type=payment&limit=5&offset=0"
        "&include_superseded=false"
    )
    status, _, body = get(url)
    assert status == 200
    expected = query.get_obligations(
        expected_con, party="landlord", type="payment", limit=5, offset=0, include_superseded=False
    )
    assert json.loads(body) == roundtrip(expected)


def test_obligations_endpoint_status_and_agreement_filters(base_url, expected_con):
    url = base_url + "/api/obligations?agreement=carbonite-2014-ex1024&status=redacted&limit=50"
    status, _, body = get(url)
    assert status == 200
    expected = query.get_obligations(
        expected_con, agreement="carbonite-2014-ex1024", status="redacted", limit=50
    )
    out = json.loads(body)
    assert out == roundtrip(expected)
    assert out["obligations"] and all(o["marker"] == "[REDACTED]" for o in out["obligations"])


def test_deadlines_endpoint_equals_query(base_url, expected_con):
    url = base_url + "/api/deadlines?days=90&as_of=2018-04-01&party=landlord&limit=10&offset=0"
    status, _, body = get(url)
    assert status == 200
    expected = query.upcoming_deadlines(
        expected_con, days=90, as_of="2018-04-01", party="landlord", limit=10, offset=0
    )
    assert json.loads(body) == roundtrip(expected)


def test_change_endpoint_equals_query(base_url, expected_con):
    status, _, body = get(base_url + f"/api/change/{A3}")
    assert status == 200
    assert json.loads(body) == roundtrip(query.change_order(expected_con, A3))


@pytest.mark.parametrize(
    "path",
    [
        "/api/obligations?limit=abc",
        "/api/obligations?offset=-x",
        "/api/obligations?include_superseded=maybe",
        "/api/deadlines?days=ninety",
    ],
)
def test_bad_params_are_400_json(base_url, path):
    status, ctype, body = get(base_url + path)
    assert status == 400
    assert ctype.startswith("application/json")
    assert "error" in json.loads(body)


def test_unknown_path_is_404(base_url):
    status, _, _ = get(base_url + "/api/nope")
    assert status == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_non_get_methods_are_405(base_url, method):
    assert request(base_url + "/api/agreements", method) == 405


def test_serve_refuses_non_loopback_hosts():
    from og.ui import server

    params = inspect.signature(server.serve).parameters
    assert "host" in params and "port" in params
    for host in ("0.0.0.0", "::", "192.168.1.10"):
        with pytest.raises(ValueError):
            server.serve(host, 0)


def test_main_binds_loopback_and_reads_port(monkeypatch):
    import importlib

    main = importlib.import_module("og.ui.__main__")
    assert main.HOST == "127.0.0.1"
    monkeypatch.delenv("OG_UI_PORT", raising=False)
    assert main.port() == 8765
    monkeypatch.setenv("OG_UI_PORT", "9123")
    assert main.port() == 9123
