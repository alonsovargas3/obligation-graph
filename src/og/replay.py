"""Recorded-response replay (wave 4 rev 2 W4-4/W4-5, ADR-010; coordinator-authored, frozen).

Recorded model responses live under eval/recorded/<kind>/ and are tracked in git.
OG_REPLAY selects the mode:
  - "on" (default): read recorded responses; on a miss, call the API and record.
  - "strict": a miss raises ReplayMiss before any client is constructed; never writes.
  - "off": bypass recorded responses entirely (equivalent to --no-cache).
"""

from __future__ import annotations

import os
from pathlib import Path

from og.paths import recorded_root

KINDS = ("extract", "change", "gate")
MODES = ("on", "strict", "off")


class ReplayMiss(Exception):
    """Strict replay found no recorded response; args[0] is the fingerprint."""


def mode() -> str:
    value = os.environ.get("OG_REPLAY") or "on"
    if value not in MODES:
        raise ValueError(f"OG_REPLAY must be one of {MODES}, got {value!r}")
    return value


def cache_dir(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown recorded kind {kind!r}")
    return recorded_root() / kind
