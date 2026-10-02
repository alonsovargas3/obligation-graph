"""`python -m og.ingest`: ingest every pinned sources.yaml document to data/text."""

from __future__ import annotations

from pathlib import Path

import yaml

from og.ingest import ingest_file

SOURCES = Path("data/sources.yaml")
OUT_DIR = Path("data/text")


def main() -> None:
    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for entry in sources.get("documents", []):
        doc_id = entry["id"]
        pin = entry.get("sha256")
        if not pin:
            print(f"warning: {doc_id}: no sha256 pin, skipping")
            continue
        local = entry.get("local_path")
        if not local or not Path(local).exists():
            print(f"warning: {doc_id}: local_path {local!r} not found, skipping")
            continue
        doc = ingest_file(local, doc_id, pin)
        doc.save(OUT_DIR / f"{doc_id}.json")
        print(f"{doc_id} {len(doc.text)} {len(doc.sections)} {len(doc.pages)} {len(doc.segments)}")


if __name__ == "__main__":
    main()
