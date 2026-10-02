"""Run the MCP server over stdio: `python -m og.mcp` (the Makefile's `make mcp`).

Nothing but MCP protocol is written to stdout; the SDK logs to stderr. The
graph database is resolved from the workspace (`OG_WORKSPACE`, else the
directory holding data/sources.yaml, else the repository root), so Claude
Desktop can launch the server from any working directory (rev 2 W4-12).
"""

from __future__ import annotations

from og.mcp.server import build_server


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
