"""On-disk response cache: fingerprint-keyed, atomic, strictly allowlisted.

Only validated ok outcomes are ever stored, and only with the allowlisted
payload keys. Nothing derived from the request (system prompt, headers, key
material) can pass through ``put``, so a cache file can never leak request
material. Files are written atomically (temp + ``os.replace``) so a crash
mid-write cannot leave a half-written entry; a file that fails to parse is
set aside as ``*.corrupt`` and treated as a miss.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

PAYLOAD_KEYS = frozenset({"items", "attempts", "prompt_version", "doc_id", "chunk_id"})


class ResponseCache:
    """A directory tree of cached chunk payloads, sharded by fingerprint prefix."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, fingerprint: str) -> Path:
        return self.root / fingerprint[:2] / f"{fingerprint}.json"

    def get(self, fingerprint: str) -> dict | None:
        """The cached payload, or None on a miss or a corrupt (set-aside) file."""
        path = self.path_for(fingerprint)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._set_aside(path)
            return None
        if not isinstance(data, dict):
            self._set_aside(path)
            return None
        return data

    def put(self, fingerprint: str, payload: dict) -> None:
        """Atomically store an allowlisted payload. Raises ValueError on foreign keys."""
        extra = set(payload) - PAYLOAD_KEYS
        if extra:
            raise ValueError(f"unexpected cache payload keys: {sorted(extra)}")
        path = self.path_for(fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    @staticmethod
    def _set_aside(path: Path) -> None:
        with contextlib.suppress(OSError):
            os.replace(path, path.with_name(path.name + ".corrupt"))
