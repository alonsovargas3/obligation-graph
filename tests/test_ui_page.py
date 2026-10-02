"""Task 32: static checks on ui/index.html (wave 4 plan Task 32, rev 2 W4-14).

One self-contained page: no external loads, no dashboards or charts, data rendered
as text (never parsed as HTML), and redacted terms visibly marked.
"""

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "ui" / "index.html"
REQUIRED_IDS = (
    "filter-party",
    "filter-site",
    "filter-type",
    "filter-status",
    "obligations-table",
    "clause-panel",
    "change-view",
    "change-select",
)


@pytest.fixture(scope="module")
def html():
    assert PAGE.exists(), "ui/index.html is missing"
    return PAGE.read_text(encoding="utf-8")


def test_no_external_urls(html):
    assert "http://" not in html
    assert "https://" not in html
    assert "@import" not in html
    assert not re.search(r"""(src|href)\s*=\s*["']//""", html), "protocol-relative load"


def test_no_em_dash(html):
    assert "\u2014" not in html


@pytest.mark.parametrize("element_id", REQUIRED_IDS)
def test_required_element_ids(html, element_id):
    assert re.search(rf"""id\s*=\s*["']{re.escape(element_id)}["']""", html), element_id


def test_noscript_fallback(html):
    m = re.search(r"<noscript>(.*?)</noscript>", html, re.S | re.I)
    assert m and m.group(1).strip()


def test_data_is_rendered_as_text_not_html(html):
    assert "textContent" in html
    for m in re.finditer(r"\.innerHTML\s*=\s*([^;\n]*)", html):
        assert m.group(1).strip() in ('""', "''", "``"), m.group(0)
    assert "insertAdjacentHTML" not in html
    assert not re.search(r"\.outerHTML\s*=", html)
    assert "document.write" not in html


def test_redaction_marker_is_rendered(html):
    assert "marker" in html


def test_no_dashboards_or_charts(html):
    assert "<canvas" not in html.lower()
    assert "chart" not in html.lower()
    assert "dashboard" not in html.lower()
