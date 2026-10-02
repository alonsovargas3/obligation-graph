"""Task 8: deterministic verification of model-proposed items (field rules).

The model proposes RawItems; verify() decides what may be stored. Every stored
field is either the copied source slice or proven present in it by a field
rule (plan task 8 with the rev 2.1 details and the rev 2.2/2.4/2.5 overrides:
token-bounded money and day counts, deadline-conflict pairing, the rev 2.4
declaration grammar for event dates and party roles, and the rev 2.5
source-sentence governing words, whole-name fields, and finite descriptors).
Anything that fails is dropped or nulled with a FieldCorrection, never inferred.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date as _date
from decimal import Decimal

from og.extract.types import (
    KINDS,
    OBL_TYPES,
    ROLES,
    Drop,
    Evidence,
    FieldCorrection,
    RawItem,
    VerifiedEvent,
    VerifiedObligation,
    VerifiedParty,
    VerifyResult,
)
from og.ground import Span, ground
from og.markers import is_blank, is_redacted
from og.textdoc import Segment, TextDoc

# ---------------------------------------------------------------- folded search


def _fold(s: str, *, ci: bool) -> tuple[str, list[int]]:
    """Collapse whitespace runs to one space (and casefold if ci) with an index map."""
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            j = i + 1
            while j < n and s[j].isspace():
                j += 1
            out.append(" ")
            idx.append(i)
            i = j
        else:
            out.append(c.casefold() if ci else c)
            idx.append(i)
            i += 1
    folded = "".join(out)
    lo, hi = 0, len(folded)
    if folded.startswith(" "):
        lo = 1
    if folded.endswith(" ") and hi > lo:
        hi -= 1
    return folded[lo:hi], idx[lo:hi]


def _find_all(text: str, needle: str, *, ci: bool) -> list[tuple[int, int]]:
    """Whitespace-normalized (and optionally case-insensitive) substring offsets."""
    hay, hidx = _fold(text, ci=ci)
    ndl, _ = _fold(needle, ci=ci)
    if not ndl:
        return []
    hits: list[tuple[int, int]] = []
    pos = hay.find(ndl)
    while pos != -1:
        hits.append((hidx[pos], hidx[pos + len(ndl) - 1] + 1))
        pos = hay.find(ndl, pos + 1)
    return hits


# ---------------------------------------------------------------- calendar dates

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_MONTH_ALT = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
    "|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
)
_RE_D_MDY = re.compile(r"\b(" + _MONTH_ALT + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b")
_RE_D_DMY = re.compile(r"\b(\d{1,2})\s+(" + _MONTH_ALT + r")\.?,?\s+(\d{4})\b")
_RE_D_US = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_RE_D_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RE_CUE = re.compile(r"\b(?:on or before|no later than|by|until|due|prior to)\b", re.IGNORECASE)


def _mk(y: int, m: int, d: int) -> str | None:
    try:
        return _date(y, m, d).isoformat()
    except ValueError:
        return None


def _model_iso(s: str) -> str | None:
    try:
        return _date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def _iso_of(s: str) -> str | None:
    """Parse one supported date form out of a string of exactly that form."""
    m = _RE_D_MDY.search(s)
    if m:
        iso = _mk(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        if iso:
            return iso
    m = _RE_D_DMY.search(s)
    if m:
        iso = _mk(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        if iso:
            return iso
    m = _RE_D_US.search(s)
    if m:
        iso = _mk(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if iso:
            return iso
    m = _RE_D_ISO.search(s)
    if m:
        iso = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            return iso
    return None


def _find_dates(text: str) -> list[tuple[str, int, int]]:
    """Every supported date occurrence in the text, as (iso, start, end)."""
    out: list[tuple[str, int, int]] = []
    for m in _RE_D_MDY.finditer(text):
        iso = _mk(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        if iso:
            out.append((iso, m.start(), m.end()))
    for m in _RE_D_DMY.finditer(text):
        iso = _mk(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        if iso:
            out.append((iso, m.start(), m.end()))
    for m in _RE_D_US.finditer(text):
        iso = _mk(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if iso:
            out.append((iso, m.start(), m.end()))
    for m in _RE_D_ISO.finditer(text):
        iso = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            out.append((iso, m.start(), m.end()))
    out.sort(key=lambda t: (t[1], t[2]))
    return out


# ---------------------------------------------------------------- money (rule 4)


def _money(int_part: str, cents: str | None, negative: bool) -> Decimal:
    text = int_part.replace(",", "") + (f".{cents}" if cents else "")
    return Decimal(("-" if negative else "") + text)


_NUM = r"\d{1,3}(?:,\d{3})+|\d+"
_RE_MONEY_SIGN = re.compile(r"(?<![\d.,])(-?)\$\s?(" + _NUM + r")(?:\.(\d{2}))?(?![\d,]|\.\d)")
_RE_MONEY_PAREN = re.compile(
    r"(?<![\d.,])\(\s*\$\s?(" + _NUM + r")(?:\.(\d{2}))?\s*\)(?![\d,]|\.\d)"
)
_RE_MONEY_WORD = re.compile(r"(?<![\d.,])(" + _NUM + r")(?:\.(\d{2}))?\s+dollars\b", re.IGNORECASE)


def _money_candidates(quote: str) -> list[Decimal]:
    """Values of every complete money token in the quote (R2-6 boundaries)."""
    out: list[Decimal] = []
    for m in _RE_MONEY_SIGN.finditer(quote):
        out.append(_money(m.group(2), m.group(3), bool(m.group(1))))
    for m in _RE_MONEY_PAREN.finditer(quote):
        out.append(_money(m.group(1), m.group(2), True))
    for m in _RE_MONEY_WORD.finditer(quote):
        out.append(_money(m.group(1), m.group(2), False))
    return out


# ---------------------------------------------------------------- days (rule 6)

_RE_DAYS = re.compile(r"(?<![\d.,])(\d{1,3})(?![\d,.])\s*\)?\s*(calendar\s+)?days?\b")
_RE_DIR_POS = re.compile(r"\b(?:after|following|from|of)\b", re.IGNORECASE)
_RE_DIR_NEG = re.compile(r"\b(?:before|prior\s+to)\b", re.IGNORECASE)


def _day_candidates(quote: str) -> list[int]:
    """Signed day offsets the quote supports: a complete day token plus direction."""
    out: list[int] = []
    for m in _RE_DAYS.finditer(quote):
        window = quote[m.end() : m.end() + 60]
        if _RE_DIR_POS.search(window):
            out.append(int(m.group(1)))
        elif _RE_DIR_NEG.search(window):
            out.append(-int(m.group(1)))
    return out


# ------------------------------------------- rev 2.4 declaration grammar (R4-1)

_CONNECTORS = r"(?:each\s+means|each\s+mean|shall\s+mean|shall\s+be|means|mean|is)"
_DATE_FORM = (
    r"\b(?:(?:" + _MONTH_ALT + r")\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:" + _MONTH_ALT + r")\.?,?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r"|\d{4}-\d{2}-\d{2})\b"
)


def _event_declared_isos(quote: str, name: str, seg_text: str, base: int) -> set[str]:
    """Dates declared by `[The] [“]Name[”] CONNECTOR DATE [.; end]` in the quote.

    R5-1: a declaration whose full source sentence (R3-1 boundaries, taken from
    the cited segment, semicolons not ending it) contains a governing word
    binds nothing.
    """
    words = name.split()
    if not words:
        return set()
    name_pat = r"\s+".join(re.escape(w) for w in words)
    pat = re.compile(
        r"(?:the\s+)?[“]?\s*" + name_pat + r"\s*[”]?\s+"
        r"" + _CONNECTORS + r"\s+(" + _DATE_FORM + r")(?=\s*[.;]|$)",
        re.IGNORECASE,
    )
    isos: set[str] = set()
    for m in pat.finditer(quote):
        iso = _iso_of(m.group(1))
        if not iso:
            continue
        s_start, s_end = _sentence_bounds(seg_text, base + m.start())
        if _RE_GOVERNING.search(seg_text[s_start:s_end]):
            continue
        isos.add(iso)
    return isos


# ------------------------------------------- rev 2.5 source-sentence context (R5-1)

_RE_GOVERNING = re.compile(
    r"\b(?:not|no|never|false|unless|if|provided|except|notwithstanding|neither"
    r"|nor|without|subject\s+to)\b",
    re.IGNORECASE,
)
_RE_SENT_END = re.compile(r"([.!?])(\s+)(\S)")
_RE_MONTH_ABBR = re.compile(r"(?i)(?:jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec)\Z")
_RE_CAP_INITIAL = re.compile(r"(?:^|[^A-Za-z])[A-Z]\Z")


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    """The source sentence containing pos (R3-1 boundaries; `;` does not end one)."""
    start, end = 0, len(text)
    for m in _RE_SENT_END.finditer(text):
        if not m.group(3).isupper():
            continue
        if m.group(1) == ".":
            head = text[: m.start(1)]
            if _RE_MONTH_ABBR.search(head) or _RE_CAP_INITIAL.search(head):
                continue
        b = m.start(3)
        if b <= pos:
            start = max(start, b)
        elif b < end:
            end = b
    return start, end


# ------------------------------------------- rev 2.4 declaration grammar (R4-2)

_ROLE_ALT = "landlord|tenant|guarantor|provider|customer|lender|other"
_RE_ROLE_BEFORE = re.compile(r"\b(" + _ROLE_ALT + r")\s+$", re.IGNORECASE)
_RE_A_HEAD = re.compile(r"(?:\bbetween\s+|\bby\s+|\band\s+|,\s*)$", re.IGNORECASE)
_RE_A_TAIL = re.compile(r"\s*(?:and\b|[,.;(])", re.IGNORECASE)
# R5-3: the only descriptor allowed between a name and its role construction.
_ENTITY = (
    r"(?:limited\s+liability\s+company|limited\s+partnership|general\s+partnership"
    r"|real\s+estate\s+investment\s+trust|statutory\s+trust|corporation|partnership"
    r"|company|trust)"
)
_JUR = r"(?:[A-Z][A-Za-z]*\s+){0,4}"
_GAP_B = re.compile(r"\s*(?:,\s*(?:(?:a|an)\s+" + _JUR + _ENTITY + r"\s*,?)?)?\s*")
_RE_CONSTR_B = re.compile(
    r"\bas\s+(?:the\s+)?(" + _ROLE_ALT + r")\b"
    r'|\(\s*(?:the\s+)?[“"]?\s*(' + _ROLE_ALT + r')\s*[”"]?\s*\)',
    re.IGNORECASE,
)
# R5-2: declaration boundaries a claimed (b) name must start at.
_RE_NAME_BOUNDARY = re.compile(
    r"(?:\bbetween|\bby|\band|\bwith|\bfrom|\bto|\bdesignates?|\bappoints?)\s+\Z"
    r"|,\s*\Z"
    r"|\(\s*\Z",
    re.IGNORECASE,
)
_RE_TOKEN = re.compile(r"[^\s,;:()]+|[,;:()]")
_RE_SEP_TOK = re.compile(r"[,;:()]")
_RE_BOUND_TOK = re.compile(r"(?i)between|by|and|with|from|to|designates?|appoints?")


def _wb_occurrences(quote: str, name: str) -> list[tuple[int, int]]:
    """Occurrences of the name with word boundaries on both sides (R4-2)."""
    out: list[tuple[int, int]] = []
    for start, end in _find_all(quote, name, ci=True):
        before = quote[start - 1] if start > 0 else ""
        after = quote[end] if end < len(quote) else ""
        if not (before.isalnum() or after.isalnum()):
            out.append((start, end))
    return out


def _rule_a(quote: str, occ: tuple[int, int]) -> str | None:
    """(a) A role word immediately precedes the name, itself well introduced."""
    start, end = occ
    prefix = quote[:start]
    m = _RE_ROLE_BEFORE.search(prefix)
    if m is None:
        return None
    head = prefix[: m.start()]
    if head.strip() and not _RE_A_HEAD.search(head):
        return None
    rest = quote[end:]
    if rest.strip() and not _RE_A_TAIL.match(rest):
        return None
    return m.group(1).lower()


def _rule_b(quote: str, occ: tuple[int, int], sent: str, rel_start: int) -> str | None:
    """(b) A role construction directly follows the name (R5-2 boundary, R5-3 gap)."""
    prefix = sent[:rel_start]
    if prefix.strip() and not _RE_NAME_BOUNDARY.search(prefix):
        return None
    end = occ[1]
    for m in _RE_CONSTR_B.finditer(quote):
        if m.start() < end:
            continue
        gap = quote[end : m.start()]
        if not _GAP_B.fullmatch(gap):
            return None
        role = m.group(1) or m.group(2)
        return role.lower()
    return None


def _field_extend_start(sent: str, occ_start: int) -> int | None:
    """Start of the longer name field ending at occ_start, or None (R5-2).

    Walks left over whitespace-separated name tokens, stopping at a separator,
    a declaration boundary token, or the start of the sentence.
    """
    field_start = occ_start
    extended = False
    prev_end = occ_start
    toks = [m for m in _RE_TOKEN.finditer(sent) if m.end() <= occ_start]
    for m in reversed(toks):
        if sent[m.end() : prev_end].strip():
            break
        tok = m.group(0)
        if _RE_SEP_TOK.fullmatch(tok) or _RE_BOUND_TOK.fullmatch(tok):
            break
        field_start = m.start()
        extended = True
        prev_end = m.end()
    return field_start if extended else None


def _suffix_veto(sent: str, rel_start: int, rel_end: int) -> bool:
    """True when the claimed name is a strict suffix of a declarable longer field."""
    field_start = _field_extend_start(sent, rel_start)
    if field_start is None:
        return False
    for m in _RE_CONSTR_B.finditer(sent):
        if m.start() < rel_end:
            continue
        return bool(_GAP_B.fullmatch(sent[rel_end : m.start()]))
    return False


def _party_bound_roles(quote: str, name: str, seg_text: str, base: int) -> set[str]:
    """Roles bound at any word-boundary occurrence; disagreeing (a)/(b) bind nothing.

    R5-1: an occurrence whose source sentence contains a governing word binds
    nothing. R5-2: a name that is a word-bounded suffix of a longer declarable
    field binds nothing.
    """
    roles: set[str] = set()
    for occ in _wb_occurrences(quote, name):
        seg_start = occ[0] + base
        s_start, s_end = _sentence_bounds(seg_text, seg_start)
        sent = seg_text[s_start:s_end]
        if _RE_GOVERNING.search(sent):
            continue
        rel_start, rel_end = seg_start - s_start, occ[1] + base - s_start
        if _suffix_veto(sent, rel_start, rel_end):
            continue
        a = _rule_a(quote, occ)
        b = _rule_b(quote, occ, sent, rel_start)
        if a is not None and b is not None:
            if a == b:
                roles.add(a)
        elif a is not None:
            roles.add(a)
        elif b is not None:
            roles.add(b)
    return roles


# ---------------------------------------------------------------- field rules


def _verify_amount(raw: RawItem, quote: str, corrections: list[FieldCorrection]) -> Decimal | None:
    if raw.amount is None:
        return None
    want = Decimal(str(raw.amount))
    if any(cand == want for cand in _money_candidates(quote)):
        return want
    corrections.append(FieldCorrection(raw, "amount", "amount_not_in_quote"))
    return None


def _verify_currency(
    raw: RawItem, amount: Decimal | None, corrections: list[FieldCorrection]
) -> str | None:
    computed = "USD" if amount is not None else None
    if raw.currency is not None and raw.currency != computed:
        reason = "currency_without_amount" if computed is None else "currency_evidence_overridden"
        corrections.append(FieldCorrection(raw, "currency", reason))
    return computed


def _verify_due_date(raw: RawItem, quote: str, corrections: list[FieldCorrection]) -> str | None:
    if raw.due_date is None:
        return None
    model = _model_iso(raw.due_date)
    for iso, start, _end in _find_dates(quote):
        if iso == model and _RE_CUE.search(quote[max(0, start - 40) : start]):
            return iso
    corrections.append(FieldCorrection(raw, "due_date", "due_date_not_in_quote"))
    return None


def _verify_offset_anchor(
    raw: RawItem, quote: str, corrections: list[FieldCorrection]
) -> tuple[int | None, str | None]:
    offset: int | None = None
    if raw.offset_days is not None and raw.offset_days in _day_candidates(quote):
        offset = raw.offset_days
    anchor_in_quote = raw.anchor_event is not None and bool(
        _find_all(quote, raw.anchor_event, ci=True)
    )
    if offset is not None and raw.anchor_event is not None and anchor_in_quote:
        return offset, raw.anchor_event
    if offset is not None:
        if raw.anchor_event is None:
            corrections.append(FieldCorrection(raw, "offset_days", "unpaired_offset"))
        else:
            corrections.append(FieldCorrection(raw, "anchor_event", "anchor_not_in_quote"))
        return None, None
    if raw.offset_days is not None:
        corrections.append(FieldCorrection(raw, "offset_days", "offset_not_in_quote"))
    if raw.anchor_event is not None:
        reason = "anchor_not_in_quote" if not anchor_in_quote else "anchor_without_offset"
        corrections.append(FieldCorrection(raw, "anchor_event", reason))
    return None, None


def _verify_trigger(raw: RawItem, quote: str, corrections: list[FieldCorrection]) -> str | None:
    if raw.trigger is None:
        return None
    hits = _find_all(quote, raw.trigger, ci=False)
    if not hits:
        corrections.append(FieldCorrection(raw, "trigger", "trigger_not_in_quote"))
        return None
    start, end = hits[0]
    return quote[start:end]


def _verify_party_ref(
    doc: TextDoc, raw: RawItem, value: str | None, field: str, corrections: list[FieldCorrection]
) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        corrections.append(FieldCorrection(raw, field, "party_not_in_agreement"))
        return None
    if v.casefold() in ROLES:
        if re.search(rf"\b{re.escape(v)}\b", doc.text, re.IGNORECASE):
            return value
    elif _find_all(doc.text, v, ci=True):
        return value
    corrections.append(FieldCorrection(raw, field, "party_not_in_agreement"))
    return None


def _event_date(
    raw: RawItem,
    quote: str,
    status: str,
    corrections: list[FieldCorrection],
    seg_text: str,
    base: int,
) -> str | None:
    if raw.date is None:
        return None
    model = _model_iso(raw.date)
    declared = _event_declared_isos(quote, raw.name, seg_text, base)
    if status == "blank" or model is None or model not in declared:
        corrections.append(FieldCorrection(raw, "date", "date_not_bound_to_event"))
        return None
    return model


# ---------------------------------------------------------------- verify


def _check_kind_and_fields(raw: RawItem) -> Drop | None:
    if raw.kind not in KINDS:
        return Drop(raw, "bad_enum:kind")
    if raw.kind == "obligation":
        if raw.type is None:
            return Drop(raw, "missing_field:type")
        if raw.type not in OBL_TYPES:
            return Drop(raw, "bad_enum:type")
    elif raw.kind == "event":
        if not raw.name:
            return Drop(raw, "missing_field:name")
    else:
        if not raw.name:
            return Drop(raw, "missing_field:name")
        if raw.role is None:
            return Drop(raw, "missing_field:role")
        if raw.role not in ROLES:
            return Drop(raw, "bad_enum:role")
    return None


def _segment_containing(doc: TextDoc, offset: int) -> Segment | None:
    for seg in doc.segments:
        if seg.char_start <= offset < seg.char_end:
            return seg
    return None


def _status_of(
    raw: RawItem, quote: str, evidence: Evidence, doc: TextDoc, corrections: list[FieldCorrection]
) -> str:
    if is_redacted(quote):
        status = "redacted"
    elif is_blank(quote):
        status = "blank"
    else:
        status = "active"
    seg = doc.segment(evidence.segment_id)
    outside = (
        doc.text[seg.char_start : evidence.char_start] + doc.text[evidence.char_end : seg.char_end]
    )
    if outside and (is_redacted(outside) or is_blank(outside)):
        corrections.append(FieldCorrection(raw, "status", "marker_in_segment_outside_quote"))
    if raw.status != status:
        corrections.append(FieldCorrection(raw, "status", "model_status_overridden"))
    return status


def _verify_obligation(
    raw: RawItem,
    doc: TextDoc,
    evidence: Evidence,
    quote: str,
    obligations: list[VerifiedObligation],
    corrections: list[FieldCorrection],
) -> None:
    status = _status_of(raw, quote, evidence, doc, corrections)
    amount = _verify_amount(raw, quote, corrections)
    currency = _verify_currency(raw, amount, corrections)
    due_date = _verify_due_date(raw, quote, corrections)
    offset, anchor = _verify_offset_anchor(raw, quote, corrections)
    if due_date is not None and offset is not None and anchor is not None:
        corrections.append(FieldCorrection(raw, "offset_days", "deadline_conflict"))
        offset = anchor = None
    trigger = _verify_trigger(raw, quote, corrections)
    owed_by = _verify_party_ref(doc, raw, raw.owed_by, "owed_by", corrections)
    owed_to = _verify_party_ref(doc, raw, raw.owed_to, "owed_to", corrections)
    if raw.description is not None:
        dn, _ = _fold(raw.description, ci=False)
        qn, _ = _fold(quote, ci=False)
        if dn != qn:
            corrections.append(FieldCorrection(raw, "description", "paraphrase_replaced_by_quote"))
    obligations.append(
        VerifiedObligation(
            evidence=evidence,
            type=raw.type,
            status=status,
            owed_by=owed_by,
            owed_to=owed_to,
            description=quote,
            amount=amount,
            currency=currency,
            due_date=due_date,
            anchor_event=anchor,
            offset_days=offset,
            trigger=trigger,
        )
    )


def _dedupe[T](items: list[T]) -> list[T]:
    seen: set[T] = set()
    out: list[T] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def verify(doc: TextDoc, items: Iterable[RawItem]) -> VerifyResult:
    """Turn model-proposed RawItems into Verified values, drops, and corrections."""
    obligations: list[VerifiedObligation] = []
    events: list[VerifiedEvent] = []
    parties: list[VerifiedParty] = []
    drops: list[Drop] = []
    corrections: list[FieldCorrection] = []

    for raw in items:
        bad = _check_kind_and_fields(raw)
        if bad is not None:
            drops.append(bad)
            continue
        try:
            seg = doc.segment(raw.segment_id)
        except KeyError:
            drops.append(Drop(raw, "unknown_segment"))
            continue
        gr = ground(doc, Span(raw.span_text, seg.char_start, seg.char_end, seg.section_id))
        if not gr.grounded or gr.char_start is None or gr.char_end is None:
            drops.append(Drop(raw, gr.reason or "not_grounded"))
            continue
        start, end = gr.char_start, gr.char_end
        seg_start = _segment_containing(doc, start) or seg
        seg_last = _segment_containing(doc, end - 1) or seg_start
        if seg_last.id != seg_start.id:
            drops.append(Drop(raw, "multi_segment_evidence"))
            continue
        section = doc.section_for(start)
        if section is not None and section.heading.strip().lower() == "table of contents":
            drops.append(Drop(raw, "toc_evidence"))
            continue
        if seg_start.id != seg.id:
            corrections.append(FieldCorrection(raw, "segment_id", "relocated"))
        page = doc.page_for(start)
        evidence = Evidence(
            segment_id=seg_start.id,
            section_id=section.id if section is not None else seg_start.section_id,
            section_number=section.number if section is not None else None,
            page=page if page is not None else seg_start.page,
            char_start=start,
            char_end=end,
            span_text=doc.text[start:end],
        )
        quote = evidence.span_text

        if raw.kind == "obligation":
            _verify_obligation(raw, doc, evidence, quote, obligations, corrections)
        elif raw.kind == "event":
            status = _status_of(raw, quote, evidence, doc, corrections)
            if not _find_all(quote, raw.name, ci=True):
                drops.append(Drop(raw, "event_name_not_in_quote"))
                continue
            ev_seg = doc.segment(evidence.segment_id)
            ev_seg_text = doc.text[ev_seg.char_start : ev_seg.char_end]
            ev_base = evidence.char_start - ev_seg.char_start
            events.append(
                VerifiedEvent(
                    evidence,
                    raw.name,
                    _event_date(raw, quote, status, corrections, ev_seg_text, ev_base),
                    status,
                )
            )
        else:
            if not _find_all(quote, raw.name, ci=True):
                drops.append(Drop(raw, "party_name_not_in_quote"))
                continue
            pt_seg = doc.segment(evidence.segment_id)
            pt_seg_text = doc.text[pt_seg.char_start : pt_seg.char_end]
            pt_base = evidence.char_start - pt_seg.char_start
            roles = _party_bound_roles(quote, raw.name, pt_seg_text, pt_base)
            if len(roles) != 1 or next(iter(roles)) != raw.role.lower():
                drops.append(Drop(raw, "role_not_bound_to_name"))
                continue
            parties.append(VerifiedParty(evidence, raw.name, raw.role))

    return VerifyResult(
        obligations=_dedupe(obligations),
        events=_dedupe(events),
        parties=_dedupe(parties),
        drops=drops,
        corrections=corrections,
    )
