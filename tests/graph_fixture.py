"""Helpers for the real graph fixture (tests/fixtures/graph/).

`real_v5.db` is the real wave-3 integration graph plus the four cited site pins, copied
row for row from `real_v4.db` into schema v5 (wave 5) with no timing rows. See
tests/fixtures/graph/README.md. Tests always work on a copy: the committed file is never
opened for writing.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from og.textdoc import TextDoc

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "graph"
REAL_DB = FIX / "real_v5.db"
TEXT = FIX / "text"

BASE = "constantcontact-2011-ex1041"
A1 = "constantcontact-2012-ex101"
A3 = "endurance-2017-ex106"
CARBONITE = "carbonite-2014-ex1024"
APPLIED = "applieddigital-2026-ex101"
CC_CHAIN = (BASE, A1, A3)

# Expected real-fixture values (README).
VISIBLE = 525
OWED_TO_BOUND = 168
LANDLORD_PAYEE = 114
TENANT_PAYEE = 54
UNRESOLVED_PARTY = 357  # payer or payee unbound
PER_AGREEMENT = {
    APPLIED: 25,
    CARBONITE: 202,
    BASE: 166,
    A1: 5,
    A3: 7,
    "mawson-2025-ex101": 87,
    "terawulf-2025-ex10-1": 33,
}
REDACTED = 19
PAYMENTS = 152

REF_LANDLORD = 65  # CC base landlord party binding citation
REF_TENANT = 66
OBL_34 = 34  # CC base termination_right, payer tenant, payee landlord
OBL_34_REF = 92
REF_SITE_CARBONITE = 835
REDACTED_ROWS = (204, 381, 490, 504)


def copy_db(tmp_path: Path, name: str = "graph.db") -> Path:
    dst = tmp_path / name
    shutil.copyfile(REAL_DB, dst)
    return dst


def open_db(path: Path) -> sqlite3.Connection:
    """A plain connection to a copied fixture (no schema re-application)."""
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def make_workspace(tmp_path: Path, monkeypatch, *, drop_text: tuple[str, ...] = ()) -> Path:
    """A workspace layout (data/graph.db, data/text, data/sources.yaml) under tmp_path.

    Sets OG_WORKSPACE and also chdirs there, so code resolving paths through og.paths
    and code using cwd-relative data/ paths both see the same files.
    """
    ws = tmp_path / "ws"
    (ws / "data" / "text").mkdir(parents=True)
    shutil.copyfile(REAL_DB, ws / "data" / "graph.db")
    shutil.copyfile(ROOT / "data" / "sources.yaml", ws / "data" / "sources.yaml")
    for p in TEXT.glob("*.json"):
        if p.stem not in drop_text:
            shutil.copyfile(p, ws / "data" / "text" / p.name)
    monkeypatch.setenv("OG_WORKSPACE", str(ws))
    monkeypatch.chdir(ws)
    return ws


def textdoc(doc_id: str) -> TextDoc:
    return TextDoc.load(TEXT / f"{doc_id}.json")
