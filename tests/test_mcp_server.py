"""Task 31: the MCP server (wave 4 plan Task 31, rev 2 W4-10/11/12, rev 2.1).

The server is a thin, read-only wrapper over og.query. Every tool result is parsed
from the real mcp 2.2 CallToolResult envelope (content[0].text JSON), never assumed
to be a plain dict. The real graph fixture (tests/fixtures/graph/real_v4.db) is
copied into a temporary workspace (OG_WORKSPACE) before use.
"""

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import anyio
import pytest

from og import query
from og.store.db import connect

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "graph"
TOOLS = {"list_agreements", "get_obligations", "upcoming_deadlines", "check_change_order"}
PARAMS = {
    "list_agreements": set(),
    "get_obligations": {
        "party",
        "site",
        "type",
        "status",
        "lifecycle",
        "agreement",
        "include_superseded",
        "limit",
        "offset",
    },
    "upcoming_deadlines": {"days", "party", "as_of", "limit", "offset"},
    "check_change_order": {"path"},
}
CARBONITE = "carbonite-2014-ex1024"
A3 = "endurance-2017-ex106"


def make_workspace(root: Path) -> Path:
    """A workspace layout: data/graph.db, data/text/*.json, data/sources.yaml, ui/."""
    (root / "data").mkdir(parents=True)
    shutil.copy(FIX / "real_v4.db", root / "data" / "graph.db")
    shutil.copytree(FIX / "text", root / "data" / "text")
    shutil.copy(ROOT / "data" / "sources.yaml", root / "data" / "sources.yaml")
    return root


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = make_workspace(tmp_path / "ws")
    monkeypatch.setenv("OG_WORKSPACE", str(root))
    return root


@pytest.fixture
def expected_con(tmp_path):
    """A separate copy of the fixture for computing og.query's expected outputs."""
    path = tmp_path / "expected.db"
    shutil.copy(FIX / "real_v4.db", path)
    con = connect(path)
    yield con
    con.close()


def server_for(db_path=None):
    from og.mcp.server import build_server

    return build_server(db_path)


def payload(result):
    """The JSON payload of a CallToolResult (mcp 2.2 envelope)."""
    assert result.content, "tool returned no content"
    return json.loads(result.content[0].text)


def call(server, name, args=None):
    async def run():
        return await server.call_tool(name, args or {})

    return anyio.run(run)


def list_tools(server):
    async def run():
        return await server.list_tools()

    return anyio.run(run)


def roundtrip(value):
    return json.loads(json.dumps(value))


def test_exactly_four_tools_with_documented_parameters(ws):
    tools = {t.name: t for t in list_tools(server_for())}
    assert set(tools) == TOOLS
    for name, tool in tools.items():
        props = set((tool.input_schema or {}).get("properties", {}))
        assert props == PARAMS[name], name


def test_tool_descriptions_have_no_em_dash(ws):
    for tool in list_tools(server_for()):
        assert tool.description, tool.name
        assert "\u2014" not in tool.description, tool.name


def test_check_change_order_description_states_stored_report_no_analysis(ws):
    [tool] = [t for t in list_tools(server_for()) if t.name == "check_change_order"]
    text = tool.description.lower()
    assert "stored" in text
    assert "verified" in text
    assert "no analysis" in text or "does not analyze" in text or "performs no analysis" in text


def test_list_agreements_equals_query(ws, expected_con):
    out = payload(call(server_for(), "list_agreements"))
    assert out == {"agreements": roundtrip(query.list_agreements(expected_con))}
    assert len(out["agreements"]) == 7


def test_get_obligations_equals_query_and_every_item_cites(ws, expected_con):
    args = {"party": "landlord", "limit": 20, "offset": 0}
    out = payload(call(server_for(), "get_obligations", args))
    assert out == roundtrip(query.get_obligations(expected_con, **args))
    assert out["obligations"], "landlord filter should match real rows"
    for ob in out["obligations"]:
        assert len(ob["clauses"]) >= 1
        for c in ob["clauses"]:
            assert c["span_text"]


def test_redacted_carbonite_payment_is_marked(ws):
    args = {"agreement": CARBONITE, "type": "payment", "limit": 500}
    out = payload(call(server_for(), "get_obligations", args))
    by_id = {ob["id"]: ob for ob in out["obligations"]}
    assert 204 in by_id
    ob = by_id[204]
    assert ob["status"] == "redacted"
    assert ob["marker"] == "[REDACTED]"
    assert ob["amount"] is None
    assert ob["clauses"] and ob["clauses"][0]["span_text"]


def test_upcoming_deadlines_equals_query(ws, expected_con):
    args = {"days": 90, "party": "landlord", "as_of": "2018-04-01", "limit": 10, "offset": 0}
    out = payload(call(server_for(), "upcoming_deadlines", args))
    assert out == roundtrip(query.upcoming_deadlines(expected_con, **args))
    assert out["scheduled"] == []
    assert out["pending_total"] > 0
    assert out["note"] == query.PENDING_NOTE


def test_check_change_order_returns_stored_report(ws, expected_con):
    out = payload(call(server_for(), "check_change_order", {"path": A3}))
    assert out["status"] == "ok"
    assert out["stored_report"] is True
    assert out["analysis_performed"] is False
    assert out["change_order_id"] == A3
    assert out == roundtrip(query.change_order(expected_con, A3))


def test_check_change_order_unknown_path(ws, tmp_path):
    stray = tmp_path / "endurance-2017-ex106.htm"
    stray.write_text("<html>not the pinned filing</html>", encoding="utf-8")
    out = payload(call(server_for(), "check_change_order", {"path": str(stray)}))
    assert out["status"] == "unknown_change_order"
    assert out["stored_report"] is True
    assert out["analysis_performed"] is False


def test_missing_db_is_a_structured_error(ws):
    missing = ws / "data" / "nope.db"
    out = payload(call(server_for(missing), "list_agreements"))
    assert "error" in out
    assert "make extract" in out["message"]
    assert not missing.exists(), "a read-only server must not create the db"


def test_older_schema_db_is_a_structured_error(ws):
    old = ws / "data" / "old.db"
    shutil.copy(FIX / "real_v4.db", old)
    con = sqlite3.connect(old)
    con.execute("PRAGMA user_version = 3")
    con.commit()
    con.close()
    out = payload(call(server_for(old), "list_agreements"))
    assert "error" in out
    assert "make extract" in out["message"]


def test_stdio_from_unrelated_cwd(ws, tmp_path):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    errlog_path = tmp_path / "stderr.log"
    transport_errors: list[BaseException] = []

    async def on_message(message):
        if isinstance(message, Exception):
            transport_errors.append(message)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "og.mcp"],
        env={"OG_WORKSPACE": str(ws), "PATH": os.environ.get("PATH", "")},
        cwd=str(elsewhere),
    )

    async def run():
        with errlog_path.open("w", encoding="utf-8") as errlog, anyio.fail_after(60):
            async with (
                stdio_client(params, errlog=errlog) as (read, write),
                ClientSession(read, write, message_handler=on_message) as session,
            ):
                await session.initialize()
                listed = await session.list_tools()
                result = await session.call_tool("list_agreements", {})
                return listed, result

    listed, result = anyio.run(run)
    assert {t.name for t in listed.tools} == TOOLS
    assert not result.is_error
    assert len(payload(result)["agreements"]) == 7
    assert transport_errors == [], "non-protocol bytes reached stdout"
    assert "Traceback" not in errlog_path.read_text(encoding="utf-8")
