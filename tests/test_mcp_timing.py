"""Wave 5 Task 42: MCP tools carry timing (plan rev 2 W5-1/W5-6, rev 2.1).

The tools stay thin wrappers over og.query: results parsed from the real mcp 2.2
CallToolResult envelope equal og.query's output on an identical copy of the timed
real v5 graph (tests/timing_fixture.py).
"""

import shutil
import sqlite3
from pathlib import Path

import pytest
from test_mcp_server import call, list_tools, payload, roundtrip
from timing_fixture import CONTINGENT, SCHEDULED, TEXT, timed_v5

from og import query

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    timed_v5(root / "data" / "graph.db")
    shutil.copytree(TEXT, root / "data" / "text")
    shutil.copy(ROOT / "data" / "sources.yaml", root / "data" / "sources.yaml")
    monkeypatch.setenv("OG_WORKSPACE", str(root))
    return root


@pytest.fixture
def expected_con(tmp_path):
    path, _ = timed_v5(tmp_path / "expected.db")
    con = sqlite3.connect(path, isolation_level=None)
    yield con
    con.close()


def server():
    from og.mcp.server import build_server

    return build_server()


def test_scheduled_obligations_carry_timing_and_deadline(ws, expected_con):
    out = payload(call(server(), "get_obligations", {"lifecycle": "scheduled"}))
    assert out == roundtrip(query.get_obligations(expected_con, lifecycle="scheduled"))
    got = {o["id"]: o for o in out["obligations"]}
    assert set(got) == set(SCHEDULED)
    for oid, (relation, bound) in SCHEDULED.items():
        assert got[oid]["timing"]["kind"] == "scheduled"
        assert got[oid]["deadline"] == {
            "relation": relation,
            "date": bound,
            "clause": got[oid]["timing"]["anchor"]["clause"],
        }


def test_upcoming_deadlines_tool_exposes_contingent(ws, expected_con):
    args = {"as_of": "2010-12-15", "days": 90, "limit": 50}
    out = payload(call(server(), "upcoming_deadlines", args))
    assert out == roundtrip(query.upcoming_deadlines(expected_con, **args))
    assert [o["id"] for o in out["scheduled"]] == [62, 65]
    assert {o["id"] for o in out["contingent"]} == CONTINGENT
    for key in ("contingent_total", "unresolved_total", "untimed_total"):
        assert isinstance(out[key], int)


def test_tool_descriptions_explain_timing_kinds(ws):
    tools = {t.name: t for t in list_tools(server())}
    text = " ".join(
        (tools[name].description or "") for name in ("get_obligations", "upcoming_deadlines")
    ).lower()
    for word in ("scheduled", "contingent", "unresolved"):
        assert word in text, word
    for tool in tools.values():
        assert chr(0x2014) not in (tool.description or "")
