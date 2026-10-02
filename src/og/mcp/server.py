"""The MCP server: four read-only tools over og.query (wave 4, Task 31).

The server is a thin wrapper. og.query owns the invariant (only visible views,
every item cited, redacted and blank rows marked, never inferred), and each tool
call opens a fresh read-only SQLite connection (a `file:...?mode=ro` URI, schema
version checked here, never `og.store.db.connect`, never a created file). A
missing or outdated graph.db is reported inside the tool's JSON as
{"error", "message"} pointing at `make extract`, so an agent reads a structured
answer instead of a protocol error. Nothing but protocol bytes reach stdout;
the SDK logs to stderr.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer

from og import query
from og.paths import db_path as workspace_db_path
from og.store.db import SCHEMA_VERSION

_INSTRUCTIONS = (
    "Read-only access to a graph of obligations extracted from filed data center "
    "contracts. Every obligation, party, site, and change-order finding carries its "
    "verbatim clause citation. Redacted terms are reported as redacted, never inferred."
)


def _read(db: str | Path | None, run: Callable[[sqlite3.Connection], dict]) -> dict:
    """Run one read on a fresh read-only connection; errors stay in the JSON.

    `db` is an explicit database path, or None to resolve the workspace database
    per call (`og.paths.db_path()`, so OG_WORKSPACE is honored). A missing file
    or an older schema returns {"error", "message"} with the pipeline step to
    run; nothing is created and no exception crosses the tool boundary for
    expected failures.
    """
    path = Path(db).resolve() if db is not None else workspace_db_path()
    uri = f"file:{quote(path.as_posix())}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, isolation_level=None)
        try:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                return {
                    "error": "schema_outdated",
                    "message": (
                        f"{path} is schema v{version}, current is v{SCHEMA_VERSION}: "
                        "delete it and run make extract."
                    ),
                }
            return run(con)
        finally:
            con.close()
    except ValueError as exc:
        return {"error": "invalid_arguments", "message": str(exc)}
    except sqlite3.Error as exc:
        return {
            "error": "db_unavailable",
            "message": f"cannot read {path} ({exc}): run make extract to build data/graph.db.",
        }


def build_server(db_path: str | Path | None = None) -> MCPServer:
    """Build the MCP server with exactly four read-only tools.

    `db_path` defaults to the workspace database resolved per call, so the server
    works when Claude Desktop launches it from any directory (rev 2 W4-12).
    """

    def read(run: Callable[[sqlite3.Connection], dict]) -> dict:
        return _read(db_path, run)

    server = MCPServer(name="obligation-graph", instructions=_INSTRUCTIONS)

    @server.tool()
    def list_agreements() -> dict:
        """List every agreement in the graph.

        Each entry carries its cited parties and agreement sites, its obligation
        count, and source metadata (filer, filing date, exhibit, URL), which is
        labeled metadata, not a contract term.
        """
        return read(lambda con: {"agreements": query.list_agreements(con)})

    @server.tool()
    def get_obligations(
        party: str | None = None,
        site: str | None = None,
        type: str | None = None,
        status: str | None = None,
        lifecycle: str | None = None,
        agreement: str | None = None,
        include_superseded: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """List obligations, each with its verbatim clause citations (section, page, span).

        party matches the payee (who is owed): a role word (landlord, tenant,
        guarantor, provider, customer, lender) or a party name, case-insensitive.
        site matches an agreement site name or location. Redacted and blank
        obligations carry a marker and null values, never an inferred term. Page
        with limit (1 to 500) and offset; the response reports total and
        unresolved_party_count alongside the rows.
        """
        return read(
            lambda con: query.get_obligations(
                con,
                party=party,
                site=site,
                type=type,
                status=status,
                lifecycle=lifecycle,
                agreement=agreement,
                include_superseded=include_superseded,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool()
    def upcoming_deadlines(
        days: int = 90,
        party: str | None = None,
        as_of: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Obligations whose effective due date falls in [as_of, as_of + days], plus pending ones.

        as_of is an ISO date, defaulting to today in UTC; the corpus spans 2011
        to 2020, so pass it explicitly for historical windows. Pending means the
        documents give no computable due date; pending rows are listed separately
        and no date is ever guessed. party matches the payee (who is owed).
        """
        return read(
            lambda con: query.upcoming_deadlines(
                con, days=days, party=party, as_of=as_of, limit=limit, offset=offset
            )
        )

    @server.tool()
    def check_change_order(path: str) -> dict:
        """Load the stored, verified change report for a change order.

        Returns the supersessions, shifted dates, price changes, and flagged
        conflicts with their clause citations, plus the gate decisions and the
        skipped checks. This tool performs no analysis and runs no checks: it
        loads a stored, verified report that make change already produced, and
        the result carries the pair id and chain snapshot it was verified
        against. path accepts a change-order id, a pinned local_path, or a bare
        pinned filename; anything else is an unknown_change_order with the
        pipeline steps to run.
        """
        out = read(lambda con: query.change_order(con, path))
        if isinstance(out, dict) and "status" in out:
            # Rev 2 W4-11: the tool result itself states stored_report and
            # analysis_performed. The flags describe this tool (it loads stored
            # reports only), so they hold on every change_order-shaped answer,
            # including the error statuses where og.query reports no stored run.
            out = {**out, "stored_report": True, "analysis_performed": False}
        return out

    return server
