"""Redaction and form-blank markers. Matching text is reported, never inferred."""

import re

_REDACTED = re.compile(
    r"\[\s*\*(?:\s*\*)*\s*\]|(?<!\*)\*{3,}(?!\*)|\[\s*REDACTED\s*\]"
    r"|\[\s*Confidential Treatment Requested\s*\]",
    re.IGNORECASE,
)
_BLANK = re.compile(r"\[\s*[●•]\s*\]|\[\s+\]|_{4,}")


def is_redacted(s: str) -> bool:
    return bool(_REDACTED.search(s))


def is_blank(s: str) -> bool:
    return bool(_BLANK.search(s))
