"""Chain building and gate-context loading (wave 3, Task 19; rev 2 R4, R12).

Task 19 owns chain and context building. ``build_snapshot`` turns one
``amends`` entry of data/sources.yaml into the ordered chain (base, then the
corpus amendments of the same base filed earlier, then the change order), each
member pinned to its current extraction run and to the canonical hash of the
TextDoc on disk. A member whose snapshot is missing or stale raises
``ChainError``: the CLI tells the user to (re-)run make extract and never
calls a model. ``build_gate_context`` maps base section numbers to the
obligation types of the visible obligations cited in them, the deterministic
rules tier's section-reference input.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from og.change.types import ChainDoc, ChainMember, ChainSnapshot
from og.eval.gold import textdoc_sha256
from og.gates.types import GateContext
from og.textdoc import TextDoc

TEXT_DIR = Path("data/text")
ALIASES_PATH = Path(__file__).resolve().parents[3] / "prompts" / "change_aliases_v1.yaml"


class ChainError(Exception):
    """The chain cannot be built against the current snapshots; args[0] is a short code."""

    @property
    def code(self) -> str:
        return str(self.args[0]) if self.args else "chain_error"


@dataclass(frozen=True)
class BuiltChain:
    """Everything one change order runs against."""

    snapshot: ChainSnapshot
    docs: dict[str, TextDoc]  # agreement_id -> canonical TextDoc, hash-verified
    chain_docs: list[ChainDoc]  # Checker / verify / gates input, in chain order
    base_agreement_id: str


def _filing_date(entry: Mapping[str, Any]) -> str:
    return str(entry.get("filing_date") or "")


def current_extraction(con: sqlite3.Connection, agreement_id: str) -> tuple[str, str] | None:
    """(run_id, textdoc_sha256) of the agreement's latest extraction run, or None."""
    row = con.execute(
        "SELECT e.run_id, e.textdoc_sha256 FROM agreement a"
        " JOIN extraction_run e ON e.source_id = a.source_id WHERE a.id = ?"
        " ORDER BY e.id DESC LIMIT 1",
        (agreement_id,),
    ).fetchone()
    return (row[0], row[1]) if row is not None else None


def build_snapshot(
    con: sqlite3.Connection,
    entries: list[dict[str, Any]],
    co_entry: Mapping[str, Any],
    *,
    text_dir: str | Path = TEXT_DIR,
) -> BuiltChain:
    """Build the chain of one change order against the stored extraction snapshots.

    Raises ChainError ("missing_extraction", "textdoc_changed", ...) when any
    member has no current extraction run or its TextDoc no longer hashes to
    the pinned canonical hash (plan rev 2 R4).
    """
    co_id = co_entry["id"]
    base_id = co_entry["amends"]
    by_id = {e["id"]: e for e in entries}
    base_entry = by_id.get(base_id)
    if base_entry is None:
        raise ChainError("base_not_in_corpus")
    priors = sorted(
        (
            e
            for e in entries
            if e.get("amends") == base_id
            and e["id"] != co_id
            and _filing_date(e) < _filing_date(co_entry)
        ),
        key=lambda e: (_filing_date(e), e["id"]),
    )
    ordered = [base_entry, *priors, co_entry]
    roles = ["base", *["prior_amendment"] * len(priors), "change_order"]

    members: list[ChainMember] = []
    docs: dict[str, TextDoc] = {}
    chain_docs: list[ChainDoc] = []
    for entry, role in zip(ordered, roles, strict=True):
        doc_id = entry["id"]
        path = Path(text_dir) / f"{doc_id}.json"
        if not path.is_file():
            raise ChainError("missing_textdoc", doc_id)
        doc = TextDoc.load(path)
        extraction = current_extraction(con, doc_id)
        if extraction is None:
            raise ChainError("missing_extraction", doc_id)
        run_id, stored_sha = extraction
        if stored_sha != textdoc_sha256(doc):
            raise ChainError("textdoc_changed", doc_id)
        members.append(
            ChainMember(
                agreement_id=doc_id,
                role=role,
                source_sha256=entry["sha256"],
                textdoc_sha256=stored_sha,
                extraction_run_id=run_id,
            )
        )
        docs[doc_id] = doc
        chain_docs.append(ChainDoc(agreement_id=doc_id, doc=doc, role=role))
    return BuiltChain(
        snapshot=ChainSnapshot(members=tuple(members)),
        docs=docs,
        chain_docs=chain_docs,
        base_agreement_id=base_id,
    )


def build_gate_context(con: sqlite3.Connection, base_agreement_id: str) -> GateContext:
    """Base section number -> obligation types of the visible obligations cited in it.

    Duplicate section numbers union their types (plan rev 2 R10). Sections
    with no grounded citation of a visible obligation never appear: the rules
    tier resolves only references to sections that exist in the map.
    """
    rows = con.execute(
        "SELECT c.section, o.type FROM obligation o"
        " JOIN clause_ref c ON c.obligation_id = o.id AND c.agreement_id = o.agreement_id"
        "   AND c.grounded = 1"
        " WHERE o.agreement_id = ? AND o.id IN (SELECT id FROM visible_obligation)",
        (base_agreement_id,),
    ).fetchall()
    types: dict[str, set[str]] = {}
    for section, obligation_type in rows:
        if section is None:
            continue
        types.setdefault(section, set()).add(obligation_type)
    return GateContext(base_section_types={s: frozenset(t) for s, t in types.items()})


def load_unresolved_aliases(base_agreement_id: str, path: str | Path = ALIASES_PATH) -> list[str]:
    """The frozen unresolved alias list for this chain, or [] when the chain is unknown."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    for chain in (raw or {}).get("chains", []):
        if chain.get("base") == base_agreement_id:
            unresolved = chain.get("unresolved") or []
            return [str(alias) for alias in unresolved]
    return []
