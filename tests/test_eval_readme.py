"""Task 34: README tables generated from the pinned aggregate (wave 4 rev 2 W4-13, W4-14).

og.eval.readme.render_tables(aggregate) -> str returns deterministic markdown ending in a
newline. A README carries it as START + "\n" + render_tables(aggregate) + END. The CLI:
  python -m og.eval readme-tables [--results PATH] (--check README | --write README)
--results defaults to the lexicographically last eval/results/*-aggregate.json in the
workspace. --check exits 0 when the README's block equals the rendering, 1 when it
differs or the block is missing. --write replaces only the block's content.
These tests use temporary README fixtures; the coordinator adds the real README check
in C11.
"""

import json

import pytest
from eval_workspace import A1, A3, BASE, build

from og.eval.__main__ import main
from og.eval.readme import END, START, render_tables

PROSE_BEFORE = "# Obligation Graph\n\nIntro prose stays put.\n\n"
PROSE_AFTER = "\n\n## Where this goes\n\nMore prose.\n"


@pytest.fixture
def agg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OG_WORKSPACE", str(tmp_path))
    info = build(tmp_path)
    out = tmp_path / "eval" / "results" / "2026-10-02-aggregate.json"
    assert main(["all", "--manifest", str(info["manifest"]), "--out", str(out)]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def readme(tmp_path, block):
    path = tmp_path / "README.md"
    path.write_text(f"{PROSE_BEFORE}{START}\n{block}{END}{PROSE_AFTER}", encoding="utf-8")
    return path


def test_markers():
    assert START == "<!-- og:tables:start -->"
    assert END == "<!-- og:tables:end -->"


def test_rendering_is_deterministic_and_plain(agg):
    first = render_tables(agg)
    assert first == render_tables(json.loads(json.dumps(agg)))
    assert first.endswith("\n")
    assert "\u2014" not in first  # no em dashes in user-facing copy
    for name in (BASE, A1, A3):
        assert name in first
    assert "confirmed_safe_skip" in first or "confirmed safe" in first.lower()
    assert "|" in first  # markdown tables
    assert "historical" in first.lower()


def test_check_passes_on_an_up_to_date_block(agg, tmp_path):
    path = readme(tmp_path, render_tables(agg))
    assert main(["readme-tables", "--check", str(path)]) == 0


def test_check_fails_on_a_tampered_value(agg, tmp_path):
    rendered = render_tables(agg)
    digits = [i for i, ch in enumerate(rendered) if ch.isdigit()]
    assert digits
    i = digits[len(digits) // 2]
    tampered = rendered[:i] + ("1" if rendered[i] != "1" else "2") + rendered[i + 1 :]
    path = readme(tmp_path, tampered)
    assert main(["readme-tables", "--check", str(path)]) == 1


def test_check_fails_on_a_missing_block(agg, tmp_path):
    path = tmp_path / "README.md"
    path.write_text(PROSE_BEFORE + "no generated tables here" + PROSE_AFTER, encoding="utf-8")
    assert main(["readme-tables", "--check", str(path)]) == 1


def test_check_fails_on_a_stale_table(agg, tmp_path):
    old = json.loads(json.dumps(agg))
    old["change"][A3]["findings"]["ungated"]["overall"]["tp"] = 3
    old["change"][A3]["findings"]["ungated"]["overall"]["recall"] = 3 / 7
    path = readme(tmp_path, render_tables(old))
    assert render_tables(old) != render_tables(agg)
    assert main(["readme-tables", "--check", str(path)]) == 1


def test_default_results_is_the_latest_aggregate(agg, tmp_path):
    older = json.loads(json.dumps(agg))
    older["change"][A1]["findings"]["ungated"]["overall"]["tp"] = 1
    (tmp_path / "eval" / "results" / "2026-01-01-aggregate.json").write_text(
        json.dumps(older), encoding="utf-8"
    )
    path = readme(tmp_path, render_tables(agg))
    assert main(["readme-tables", "--check", str(path)]) == 0
    explicit = tmp_path / "eval" / "results" / "2026-01-01-aggregate.json"
    assert main(["readme-tables", "--results", str(explicit), "--check", str(path)]) == 1


def test_write_replaces_only_the_block(agg, tmp_path):
    path = readme(tmp_path, "stale\n")
    assert main(["readme-tables", "--write", str(path)]) == 0
    text = path.read_text(encoding="utf-8")
    assert text.startswith(PROSE_BEFORE + START + "\n")
    assert text.endswith(END + PROSE_AFTER)
    assert render_tables(agg) in text
    assert main(["readme-tables", "--check", str(path)]) == 0
