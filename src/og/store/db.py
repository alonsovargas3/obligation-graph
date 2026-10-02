"""SQLite connection with the schema applied. No ORM (ADR-001).

graph.db is derived data, fully reproducible from data/sources.yaml and the raw
files, so an older schema is rebuilt rather than migrated (ADR-008).
"""

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 3


class SchemaOutdated(Exception):
    """The database file predates the current schema version."""


def connect(path: str | Path = "data/graph.db") -> sqlite3.Connection:
    path = Path(path)
    existed = path.exists() and path.stat().st_size > 0
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if existed and version < SCHEMA_VERSION:
        con.close()
        raise SchemaOutdated(
            f"{path} is schema v{version}, current is v{SCHEMA_VERSION}: "
            f"delete {path} and run make extract"
        )
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return con
