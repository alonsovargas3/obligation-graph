"""The local UI server: a thin GET-only JSON layer over og.query (Task 32).

Serves ui/index.html and /api/* endpoints that return exactly og.query's dicts,
one fresh read-only connection per request. It binds loopback only and never
writes to graph.db and never calls a model (wave 4 rev 2, read-only surfaces).
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from og import paths, query
from og.store.db import SCHEMA_VERSION

DEFAULT_LIMIT = 50
_DEFAULT_PORT = 8765


class _HttpError(Exception):
    """An error with an HTTP status, surfaced as JSON, never a traceback."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _read_only_con(db_path: Path) -> sqlite3.Connection:
    """A fresh read-only connection (mode=ro); the db is never created here."""
    if not db_path.is_file():
        raise _HttpError(
            503,
            "missing_db",
            f"{db_path} not found: run make fetch ingest extract to build the graph.",
        )
    con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, isolation_level=None)
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as err:
        con.close()
        raise _HttpError(503, "unreadable_db", f"{db_path} cannot be read: {err}") from err
    if version < SCHEMA_VERSION:
        con.close()
        raise _HttpError(
            503,
            "schema_outdated",
            f"{db_path} is schema v{version}, current is v{SCHEMA_VERSION}:"
            " delete it and run make fetch ingest extract.",
        )
    return con


def _int_param(params: dict[str, list[str]], name: str, default: int) -> int:
    values = params.get(name)
    if not values:
        return default
    try:
        return int(values[0])
    except ValueError as err:
        raise _HttpError(
            400, "bad_request", f"{name} must be an integer, got {values[0]!r}"
        ) from err


def _str_param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values or values[0] == "":
        return None
    return values[0]


def _bool_param(params: dict[str, list[str]], name: str, default: bool) -> bool:
    values = params.get(name)
    if not values or values[0] == "":
        return default
    raw = values[0].strip().lower()
    if raw in ("true", "1"):
        return True
    if raw in ("false", "0"):
        return False
    raise _HttpError(400, "bad_request", f"{name} must be true or false, got {values[0]!r}")


def _limit_offset(params: dict[str, list[str]]) -> tuple[int, int]:
    return _int_param(params, "limit", DEFAULT_LIMIT), _int_param(params, "offset", 0)


class _UIHandler(BaseHTTPRequestHandler):
    """GET only. The db path is fixed by make_handler(); the page by og.paths."""

    _db_path: Path | None = None  # None: og.paths.db_path() per request
    server_version = "og-ui"
    sys_version = ""

    # ------------------------------------------------------------ plumbing

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # a local controller page does not need per-request stderr noise

    def _db(self) -> Path:
        return self._db_path if self._db_path is not None else paths.db_path()

    def _send(
        self, status: int, content_type: str, body: bytes, extra: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: object, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body, extra)

    def _drain_body(self) -> None:
        length = self.headers.get("Content-Length")
        if length:
            with contextlib.suppress(ValueError, OSError):
                self.rfile.read(int(length))

    def _reject_method(self) -> None:
        self._drain_body()
        self._send_json(
            405, {"error": "method_not_allowed", "message": "GET only."}, {"Allow": "GET"}
        )

    # ------------------------------------------------------------ methods

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        try:
            self._route_get()
        except _HttpError as err:
            self._send_json(err.status, {"error": err.code, "message": err.message})
        except ValueError as err:  # bad parameters from og.query (400, JSON)
            self._send_json(400, {"error": "bad_request", "message": str(err)})
        except (OSError, sqlite3.Error) as err:
            self._send_json(500, {"error": "server_error", "message": str(err)})

    def do_POST(self) -> None:  # noqa: N802
        self._reject_method()

    def do_PUT(self) -> None:  # noqa: N802
        self._reject_method()

    def do_DELETE(self) -> None:  # noqa: N802
        self._reject_method()

    def do_PATCH(self) -> None:  # noqa: N802
        self._reject_method()

    # ------------------------------------------------------------ routing

    def _route_get(self) -> None:
        split = urlsplit(self.path)
        route = split.path
        params = parse_qs(split.query)
        if route == "/":
            return self._serve_page()
        if route == "/api/agreements":
            return self._api_agreements()
        if route == "/api/obligations":
            return self._api_obligations(params)
        if route == "/api/deadlines":
            return self._api_deadlines(params)
        if route.startswith("/api/change/"):
            change_order_id = unquote(route[len("/api/change/") :])
            if not change_order_id or "/" in change_order_id:
                raise _HttpError(404, "not_found", f"Unknown path {route}.")
            return self._api_change(change_order_id)
        raise _HttpError(404, "not_found", f"Unknown path {route}.")

    def _serve_page(self) -> None:
        page = paths.ui_page()
        try:
            body = page.read_bytes()
        except OSError as err:
            raise _HttpError(
                404, "missing_page", f"{page} not found: the page ships with the repo."
            ) from err
        self._send(200, "text/html; charset=utf-8", body)

    def _api_agreements(self) -> None:
        con = _read_only_con(self._db())
        try:
            payload = query.list_agreements(con)
        finally:
            con.close()
        self._send_json(200, payload)

    def _api_obligations(self, params: dict[str, list[str]]) -> None:
        limit, offset = _limit_offset(params)
        con = _read_only_con(self._db())
        try:
            payload = query.get_obligations(
                con,
                party=_str_param(params, "party"),
                site=_str_param(params, "site"),
                type=_str_param(params, "type"),
                status=_str_param(params, "status"),
                lifecycle=_str_param(params, "lifecycle"),
                agreement=_str_param(params, "agreement"),
                include_superseded=_bool_param(params, "include_superseded", False),
                limit=limit,
                offset=offset,
            )
        finally:
            con.close()
        self._send_json(200, payload)

    def _api_deadlines(self, params: dict[str, list[str]]) -> None:
        limit, offset = _limit_offset(params)
        days = _int_param(params, "days", 90)
        con = _read_only_con(self._db())
        try:
            payload = query.upcoming_deadlines(
                con,
                days=days,
                party=_str_param(params, "party"),
                as_of=_str_param(params, "as_of"),
                limit=limit,
                offset=offset,
            )
        finally:
            con.close()
        self._send_json(200, payload)

    def _api_change(self, change_order_id: str) -> None:
        con = _read_only_con(self._db())
        try:
            payload = query.change_order(con, change_order_id)
        finally:
            con.close()
        self._send_json(200, payload)


def make_handler(db_path: str | Path | None = None) -> type[BaseHTTPRequestHandler]:
    """A request handler class. db_path None means og.paths.db_path() per request."""
    handler = type("UIHandler", (_UIHandler,), {"_db_path": Path(db_path) if db_path else None})
    return handler


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a resolvable name other than localhost is not guaranteed loopback


def serve(host: str = "127.0.0.1", port: int = _DEFAULT_PORT) -> None:
    """Serve the UI until interrupted. Loopback only: anything else is a mistake."""
    if not _is_loopback(host):
        raise ValueError(
            f"refusing to bind {host!r}: the UI serves the local graph on loopback only"
            " (127.0.0.1 or localhost)."
        )
    httpd = ThreadingHTTPServer((host, port), make_handler())
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
