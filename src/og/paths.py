"""Workspace-rooted paths (wave 4 rev 2 W4-12; coordinator-authored, frozen).

Every data asset (graph db, TextDocs, sources, recorded responses, UI page)
resolves from one root, so the MCP server works when Claude Desktop launches it
from an unrelated working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def workspace() -> Path:
    """OG_WORKSPACE if set; else the working directory if it holds data/sources.yaml;
    else the repository root that contains this package (Claude Desktop launches)."""
    env = os.environ.get("OG_WORKSPACE")
    if env:
        return Path(env).resolve()
    cwd = Path.cwd()
    if (cwd / "data" / "sources.yaml").is_file():
        return cwd.resolve()
    return _REPO_ROOT


def db_path() -> Path:
    return workspace() / "data" / "graph.db"


def text_dir() -> Path:
    return workspace() / "data" / "text"


def sources_path() -> Path:
    return workspace() / "data" / "sources.yaml"


def recorded_root() -> Path:
    return workspace() / "eval" / "recorded"


def ui_page() -> Path:
    return workspace() / "ui" / "index.html"
