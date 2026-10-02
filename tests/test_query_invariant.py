"""Wave 4 read invariant (Rev 2.1 R2-1) and ChangeReport freshness (Rev 2 W4-3).

1. Static allowlist: every identifier after FROM/JOIN in the SQL string literals of the
   readers is in og.query.READ_ALLOWLIST, so citations come only from the projections.
   This is a source-structure check; the projections and the behavioral revocation tests
   (test_query.py, test_schema_v4.py) carry the evidence guarantee.
2. load_change_report never presents a stale run or a missing TextDoc as a completed check.
"""

import ast
import re
from pathlib import Path

import pytest
from graph_fixture import A1, A3, BASE, make_workspace, open_db

from og.change.report import load_change_report
from og.query import READ_ALLOWLIST

SRC = Path(__file__).resolve().parents[1] / "src"
READERS = {
    "og/query.py": None,
    "og/change/report.py": None,
    "og/eval/score.py": "pred_from_db",
    "og/eval/change_score.py": None,
}
_IDENT = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)")
_CTE = re.compile(r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(")


def _string_parts(node: ast.AST) -> list[str]:
    """String constants under node (f-string literal parts included), docstrings excluded."""
    docstrings = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = n.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            out.append(n.value)
    return out


def _sql_identifiers(path: Path, function: str | None) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scope: ast.AST = tree
    if function is not None:
        scope = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == function
        )
    names: set[str] = set()
    for text in _string_parts(scope):
        if "SELECT" not in text and "FROM" not in text and "JOIN" not in text:
            continue
        ctes = set(_CTE.findall(text))
        names |= {n for n in _IDENT.findall(text) if n not in ctes}
    return names


def test_allowlist_helper_sees_raw_tables():
    """The checker itself must flag a raw clause_ref join (guards against a vacuous pass)."""
    code = 'q = "SELECT x FROM visible_obligation o" " JOIN clause_ref c ON c.id = o.id"\n'
    tree = ast.parse(code)
    found = {n for t in _string_parts(tree) for n in _IDENT.findall(t)}
    assert found == {"visible_obligation", "clause_ref"}


@pytest.mark.parametrize("rel,function", sorted(READERS.items()))
def test_readers_use_only_allowlisted_sources(rel, function):
    names = _sql_identifiers(SRC / rel, function)
    assert not (names - READ_ALLOWLIST), sorted(names - READ_ALLOWLIST)


def test_allowlist_excludes_raw_evidence_tables():
    for raw in (
        "obligation",
        "clause_ref",
        "agreement_party",
        "event",
        "change_finding",
        "change_run",
        "supersedes",
        "agreement_site",
    ):
        assert raw not in READ_ALLOWLIST


# ---------------------------------------------------------------- report freshness


@pytest.fixture
def ws(tmp_path, monkeypatch):
    return make_workspace(tmp_path, monkeypatch)


def test_fresh_report_unchanged(ws):
    con = open_db(ws / "data" / "graph.db")
    report = load_change_report(con, A3, "ungated")
    assert "error" not in report
    assert [d["delta"] for d in report["shifted_dates"]] == ["731"]
    assert len(report["price_changes"]) == 3
    assert "2A" in report["unresolved_documents"]
    assert len(load_change_report(con, A1, "gated")["price_changes"]) == 5


def test_stale_report_is_an_error_not_an_empty_check(ws):
    con = open_db(ws / "data" / "graph.db")
    con.execute("UPDATE extraction_run SET textdoc_sha256=? WHERE source_id=?", ("0" * 64, BASE))
    for mode in ("ungated", "gated"):
        report = load_change_report(con, A3, mode)
        assert report["error"] == "stale_change_run"
        assert "make change" in report["message"]
        for key in ("supersessions", "shifted_dates", "price_changes", "gates", "new_obligations"):
            assert key not in report


def test_missing_textdoc_is_an_error_not_an_empty_unresolved_list(tmp_path, monkeypatch):
    ws = make_workspace(tmp_path, monkeypatch, drop_text=(A3,))
    con = open_db(ws / "data" / "graph.db")
    report = load_change_report(con, A3, "ungated")
    assert report["error"] == "missing_textdoc"
    assert "unresolved_documents" not in report
