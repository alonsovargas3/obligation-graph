"""Build tests/fixtures/graph/real_v5.db: real_v4.db rows copied into schema v5.

No obligation_timing rows are written here; the wave 5 writer derives them, and tests
that need timing rows insert them into a tmp copy. Run from the repo root:
    uv run --locked python tests/fixtures/graph/build_fixture_v5.py
"""

from pathlib import Path

from og.store.db import connect

HERE = Path(__file__).parent
SRC, OUT = HERE / "real_v4.db", HERE / "real_v5.db"
TABLES = ["source", "party", "agreement", "site", "extraction_run", "obligation", "clause_ref",
          "agreement_party", "agreement_site", "event", "defined_term", "change_run",
          "change_run_chain", "change_finding", "supersedes", "guarantees", "triggers",
          "gate_decision"]

OUT.unlink(missing_ok=True)
con = connect(OUT)
con.execute("PRAGMA foreign_keys = OFF")
con.execute("ATTACH ? AS v4", (str(SRC),))
con.execute("BEGIN")
for t in TABLES:
    cols = ",".join(f'"{r[1]}"' for r in con.execute(f"PRAGMA v4.table_info({t})"))
    con.execute(f'INSERT INTO main."{t}"({cols}) SELECT {cols} FROM v4."{t}"')
con.execute("COMMIT")
con.execute("DETACH v4")
con.execute("PRAGMA foreign_keys = ON")
assert not con.execute("PRAGMA foreign_key_check").fetchall()
q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
print("user_version", q("pragma user_version"), "visible", q("select count(*) from visible_obligation"),
      "timing rows", q("select count(*) from obligation_timing"))
con.execute("VACUUM")
con.close()
