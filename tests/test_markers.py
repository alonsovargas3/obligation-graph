import pytest

from og.markers import is_blank, is_redacted


@pytest.mark.parametrize(
    "s",
    [
        "$[***] per month",
        "[*]",
        "rate of *** per kW",
        "[REDACTED]",
        "[redacted]",
        "[Confidential Treatment Requested]",
        "[ * * * ]",
    ],
)
def test_redacted(s):
    assert is_redacted(s)


@pytest.mark.parametrize("s", ["means [●].", "[•]", "dated as of [  ], 2025", "the sum of $______"])
def test_blank(s):
    assert is_blank(s)


@pytest.mark.parametrize(
    "s", ["Tenant shall pay $1,000.", "Section 2.1 [reserved]", "a * b", "**bold**", "[x]", "___"]
)
def test_neither(s):
    assert not is_redacted(s) and not is_blank(s)
