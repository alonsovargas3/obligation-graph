"""C11: the committed README's generated tables match the committed aggregate.

Task 34 tested the renderer and checker on temporary fixtures; this test activates the
check on the real README, as the plan's rev 2 W4-14 requires. Edit the results, never
the block.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_tables_match_the_committed_aggregate(monkeypatch):
    monkeypatch.setenv("OG_WORKSPACE", str(ROOT))
    proc = subprocess.run(
        [sys.executable, "-m", "og.eval", "readme-tables", "--check", "README.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_readme_has_no_em_dashes():
    assert "—" not in (ROOT / "README.md").read_text(encoding="utf-8")
