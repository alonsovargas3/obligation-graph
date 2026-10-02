"""Deterministic timing classification (wave 5; contract coordinator-authored and frozen).

Two stages (plan rev 2 W5-7):
  parse(doc, evidence)  -> ParsedTiming   pure: reads only the obligation's own quote
  resolve(parsed, anchors, legacy_due) -> Timing   owns the final kind, relation, bound
defined_dates(doc) finds cited calendar dates for defined terms (BLI rows and the closed
declaration forms in prompts/timing_grammar_v1.yaml). No model is involved. A trigger
span is always an exact slice inside the obligation quote; an anchor date always comes
from a cited declaration in the obligation's agreement or its recorded base. Bodies are
Task 40; the signatures, types and constants below are frozen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

from og.extract.types import Evidence
from og.textdoc import TextDoc

GRAMMAR_PATH = Path(__file__).resolve().parents[2] / "prompts" / "timing_grammar_v1.yaml"

TIMING_KINDS = ("scheduled", "contingent", "unresolved", "untimed")
TRIGGER_KINDS = (
    "invoice",
    "notice",
    "demand",
    "default",
    "completion",
    "term_end",
    "defined_event",
    "other_event",
)
RELATIONS = ("lt", "lte", "eq", "gte", "gt")
OFFSET_UNITS = ("calendar", "business", "hours", "months")
UNRESOLVED_REASONS = (
    "business_days",
    "anchor_without_date",
    "anchor_not_found",
    "relative_to_other_obligation",
    "conditional_or_compound",
    "unsupported_unit",
    "cross_reference",
    "redacted_offset",
    "recurring_schedule",
    "month_granularity",
    "conflicting_dates",
)


@dataclass(frozen=True)
class TimingSpan:
    char_start: int
    char_end: int
    span_text: str  # == doc.text[char_start:char_end], inside the obligation quote


@dataclass(frozen=True)
class ParsedTiming:
    """What the obligation's own quote says, before any anchor is resolved."""

    construction: str | None  # a construction id from the grammar, or None
    relation: str | None  # one of RELATIONS
    offset_days: int | None  # signed: "N days prior to X" is -N
    offset_unit: str | None  # one of OFFSET_UNITS
    trigger: TimingSpan | None  # minimal construction + event phrase
    trigger_kind: str | None  # one of TRIGGER_KINDS
    anchor_name: str | None  # defined term immediately after the construction, if any
    reason: str | None  # an UNRESOLVED_REASONS value decided from the quote alone


@dataclass(frozen=True)
class DefinedDate:
    agreement_id: str
    name: str  # the defined term, as written (e.g. "Commencement Date")
    date: str  # ISO
    evidence: TimingSpan  # the full accepted declaration (label + value, or parenthetical)
    form: str  # "bli_row" | "declaration"


@dataclass(frozen=True)
class CitedAnchor:
    event_id: int
    agreement_id: str
    name: str
    date: str | None  # ISO, from the event's own cited declaration
    clause_ref_id: int


@dataclass(frozen=True)
class Timing:
    kind: str  # one of TIMING_KINDS
    trigger_kind: str | None
    trigger: TimingSpan | None
    relation: str | None
    offset_days: int | None
    offset_unit: str | None
    anchor_event_id: int | None
    bound_date: str | None  # ISO; set only when kind == "scheduled"
    reason: str | None  # set iff kind == "unresolved"


# --------------------------------------------------------------------------------------
# Grammar engine. Every lexicon (number forms, units, connectors, trigger-kind phrases,
# unresolved reason patterns, timing cues, BLI labels, declaration forms) is read from
# GRAMMAR_PATH at first use; no list from the yaml is duplicated in this module.
# --------------------------------------------------------------------------------------

_W = r"\s+"  # whitespace; unicode \s also covers NBSP (U+00A0)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_DATE_SRC = (
    r"(?P<dmonth>"
    + "|".join(_MONTHS)
    + r")"
    + _W
    + r"(?P<dday>\d{1,2}),?"
    + _W
    + r"(?P<dyear>\d{4})"
)
_DATE_FLAT_SRC = (
    r"(?i:(?P<fmonth>"
    + "|".join(_MONTHS)
    + r"))"
    + _W
    + r"(?P<fday>\d{1,2}),?"
    + _W
    + r"(?P<fyear>\d{4})"
)
# A defined-event name: capitalized or digit tokens (1A, 3A, 409 allowed), ending in the
# token "Date" (grammar rule `defined_name`); matching is case sensitive.
_NAME_SRC = r"[A-Z0-9][A-Za-z0-9]*(?:" + _W + r"[A-Z0-9][A-Za-z0-9]*)*?" + _W + r"Date\b"
_ENUM_RX_SRC = r"\s*(?:\d+(?:\.\d+)*\.?|\([A-Za-z0-9]+\)|[A-Z]\.)(?=" + _W + r")"
_DELIMS = ",;."
_PHRASE_BOUND = r"(?<!\w){}(?!\w)"


def _norm(s: str) -> str:
    """Whitespace normalization shared with the frozen tests: NBSP counts as a space."""
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip().lower()


def _words_src(phrase: str) -> str:
    return _W.join(re.escape(tok) for tok in phrase.split())


def _spelled(n: int) -> str:
    ones = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
    teens = (
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
    )
    tens = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
    if n < 10:
        return ones[n - 1]
    if n < 20:
        return teens[n - 10]
    if n < 100:
        t, r = divmod(n, 10)
        return tens[t - 2] + ("-" + ones[r - 1] if r else "")
    h, r = divmod(n, 100)
    head = "one hundred" if h == 1 else ones[h - 1] + " hundred"
    return head + (" " + _spelled(r) if r else "")


@lru_cache(maxsize=1)
def _grammar() -> dict:
    return yaml.safe_load(GRAMMAR_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _spelled_numbers() -> dict[str, int]:
    top = int(_grammar()["numbers"]["spelled_max"])
    return {_spelled(n): n for n in range(1, top + 1)}


@dataclass(frozen=True)
class _ConstrSpec:
    id: str
    rx: re.Pattern
    relation: str
    offset_sign: int | None  # absent: an offsetless construction
    has_count: bool
    has_unit: bool


@dataclass(frozen=True)
class _CMatch:
    spec: _ConstrSpec
    start: int
    keywords_end: int
    trigger_end: int
    offset_days: int | None
    redacted: bool
    unit: str | None


def _split_pattern(pattern: str) -> list[tuple[str, str]]:
    """Split a construction pattern into ('lit'|'ph'|'opt'|'alt', text) parts."""
    out: list[tuple[str, str]] = []
    buf = ""
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "{":
            j = pattern.index("}", i)
            if buf.strip():
                out.append(("lit", buf))
            buf = ""
            out.append(("ph", pattern[i + 1 : j]))
            i = j + 1
        elif ch == "(":
            j = pattern.index(")", i)
            if buf.strip():
                out.append(("lit", buf))
            buf = ""
            inner = pattern[i + 1 : j]
            optional = pattern[j + 1 : j + 2] == "?"
            out.append(("opt" if optional else "alt", inner))
            i = j + (2 if optional else 1)
        else:
            buf += ch
            i += 1
    if buf.strip():
        out.append(("lit", buf))
    return out


class _Engine:
    """The compiled grammar; built once per process from GRAMMAR_PATH."""

    def __init__(self) -> None:
        g = _grammar()
        self.redacted = tuple(g["numbers"]["redacted_tokens"])

        spelled_alt = "|".join(
            re.escape(w) for w in sorted(_spelled_numbers(), key=len, reverse=True)
        )
        redacted_alt = "|".join(re.escape(t) for t in self.redacted)
        self._count_src = (
            rf"(?:(?P<r>{redacted_alt}))"
            rf"|(?:(?P<sp>{spelled_alt})(?:\s*\(\s*(?P<pd>\d+)\s*\))?)"
            r"|(?:(?P<d>\d+))"
        )
        unit_pairs = [(phrase, kind) for kind, phrases in g["units"].items() for phrase in phrases]
        unit_pairs.sort(key=lambda pk: -len(pk[0]))
        self._unit_src = "(?P<unit>" + "|".join(f"(?:{_words_src(p)})" for p, _ in unit_pairs) + ")"
        self._unit_kind = {_norm_key(p): k for p, k in unit_pairs}
        business_alt = "|".join(
            f"(?:{_words_src(p)})" for p in sorted(g["units"]["business"], key=len, reverse=True)
        )

        self.specs: list[_ConstrSpec] = []
        for entry in g["constructions"]:
            cid = entry["id"]
            pattern = entry["pattern"]
            if cid == "within_business_days":
                # Pattern 'within {count} business day(s) (with or without a following
                # event)': the parenthetical is a note, not a keyword list; the unit
                # lexicon supplies the phrase, with or without a following event.
                src = rf"\bwithin{_W}(?:{self._count_src}){_W}(?P<unit>{business_alt})\b"
                has_unit = True
            else:
                pieces = []
                for kind, val in _split_pattern(pattern):
                    if kind == "ph":
                        if val == "count":
                            pieces.append(("ph", f"(?:{self._count_src})"))
                        elif val == "unit":
                            pieces.append(("ph", self._unit_src))
                        else:  # {trigger} / {defined_event}: spanned apart, see below
                            break
                    elif kind == "opt":
                        # an optional prefix carries its own trailing separator, so it
                        # glues to what follows whether or not it matched
                        pieces.append(("opt", rf"(?:{_words_src(val)}{_W})?"))
                    elif kind == "alt":
                        pieces.append(
                            ("alt", "(?:" + "|".join(_words_src(a) for a in val.split("|")) + ")")
                        )
                    else:
                        pieces.append(("lit", f"(?:{_words_src(val)})"))
                src = r"\b"
                for j, (_kind2, piece) in enumerate(pieces):
                    if j > 0 and pieces[j - 1][0] != "opt":
                        src += _W
                    src += piece
                src += r"\b"
                has_unit = "{unit}" in pattern
            self.specs.append(
                _ConstrSpec(
                    id=cid,
                    rx=re.compile(src, re.IGNORECASE),
                    relation=entry["relation"],
                    offset_sign=entry.get("offset_sign"),
                    has_count="{count}" in pattern,
                    has_unit=has_unit,
                )
            )

        self.name_rx = re.compile(_NAME_SRC)
        self._skip_the_rx = re.compile(rf"\s*(?:the{_W})?")
        self._next_word_rx = re.compile(r"\s*([A-Za-z0-9]+)")
        self.enum_rx = re.compile(_ENUM_RX_SRC)

        self.kind_specs: list[tuple[str, list[re.Pattern]]] = [
            (
                kind,
                [re.compile(_PHRASE_BOUND.format(re.escape(phrase.lower()))) for phrase in phrases],
            )
            for kind, phrases in g["trigger_kinds"].items()
        ]

        unresolved = g["unresolved"]
        self.reason_order = list(unresolved)
        cond_patterns = unresolved["conditional_or_compound"]["patterns"]
        self.compound_rx = re.compile(cond_patterns[1], re.IGNORECASE)
        leading_alts = re.search(r"\(([^()]*)\)", cond_patterns[0])
        self.leading_if_rx = re.compile(
            r"\s*(?:" + "|".join(_words_src(a) for a in leading_alts.group(1).split("|")) + r")\b",
            re.IGNORECASE,
        )
        self.recurring_rxs = [
            re.compile(p, re.IGNORECASE) for p in unresolved["recurring_schedule"]["patterns"]
        ]
        month_patterns = unresolved["month_granularity"]["patterns"]
        self.month_rxs = [re.compile(p, re.IGNORECASE) for p in month_patterns]
        # For span extraction the pattern runs against the raw quote, so every literal
        # space becomes the full whitespace class and original offsets survive.
        self.month_span_rx = re.compile(month_patterns[0].replace(" ", _W), re.IGNORECASE)
        self.cross_rxs = [
            re.compile(p, re.IGNORECASE) for p in unresolved["cross_reference"]["patterns"]
        ]
        self.cue_rxs = [
            re.compile(_PHRASE_BOUND.format(re.escape(cue.lower())))
            for cue in unresolved["anchor_not_found"]["timing_cues"]
        ]

        dd = g["defined_dates"]
        self.labels = sorted(dd["bli_labels"], key=len, reverse=True)
        label_alt = "(?:" + "|".join(f"(?:{_words_src(lbl)})" for lbl in self.labels) + ")"
        self.form_a_rx = re.compile(
            rf"^\([A-Za-z]\){_W}(?P<lbl>{label_alt})\s*:\s*(?:{_DATE_SRC})",
            re.IGNORECASE,
        )
        self.form_b_rx = re.compile(
            rf"^\([A-Za-z]\){_W}(?P<lbl>{label_alt})\s*:?\s*$", re.IGNORECASE
        )
        self.date_start_rx = re.compile(rf"^(?:{_DATE_SRC})", re.IGNORECASE)
        # Rev 2.3 `trigger_span` / `calendar_date_not_event`: a comma followed by a
        # four-digit year inside a calendar date ('June 30, 2020') does not end a
        # trigger span, and an event phrase that starts with such a date is never
        # an event.
        _month_alt = "|".join(_MONTHS)
        self._month_day_end_rx = re.compile(rf"(?i:(?:{_month_alt})){_W}\d{{1,2}}\Z", re.IGNORECASE)
        self._year_comma_rx = re.compile(rf",{_W}?\d{{4}}(?!\d)")
        self.date_event_rx = re.compile(
            rf"(?i:(?:{_month_alt})){_W}\d{{1,2}}(?:,{_W}\d{{4}})?(?!\d)", re.IGNORECASE
        )
        self.decl_rxs = [re.compile(self._decl_src(t)) for t in dd["declarations"]]

    @staticmethod
    def _decl_src(template: str) -> str:
        parts = re.split(r"(\{date\}|\{name\})", template)
        src = ""
        last = len(parts) - 1
        for i, part in enumerate(parts):
            if part in ("{date}", "{name}"):
                src += _DATE_FLAT_SRC if part == "{date}" else f"(?P<dname>{_NAME_SRC})"
                continue
            if not part.strip():
                if 0 < i < last:
                    src += _W
                continue
            lead = _W if i > 0 and part[:1].isspace() else ""
            trail = _W if i < last and part[-1:].isspace() else ""
            core = "(?i:" + _W.join(re.escape(w) for w in part.strip().split()) + ")"
            src += lead + core + trail
        return src

    # -- construction matching -----------------------------------------------------------

    def phrase_end(self, quote: str, pos: int) -> int:
        """A trigger span ends before the first comma, semicolon or period; a comma
        followed by a four-digit year inside a calendar date does not (rev 2.3)."""
        i = pos
        while i < len(quote):
            if quote[i] not in _DELIMS:
                i += 1
                continue
            year = self._year_comma_rx.match(quote, i) if quote[i] == "," else None
            if year is not None and self._month_day_end_rx.search(quote, max(0, i - 40), i):
                i = year.end()
                continue
            return i
        return i

    def _count_value(self, m: re.Match) -> tuple[int | None, bool]:
        if m.group("r") is not None:
            return None, True
        if m.group("d") is not None:
            return int(m.group("d")), False
        value = _spelled_numbers().get(_norm(m.group("sp") or ""))
        if value is None:
            return None, False
        if m.group("pd") is not None:
            value = int(m.group("pd"))
        return value, False

    def find_construction(self, quote: str) -> _CMatch | None:
        """The first construction in grammar order; within it, the leftmost occurrence
        whose event phrase is non-empty (and, for `on`, binds a defined name)."""
        for spec in self.specs:
            for m in spec.rx.finditer(quote):
                tend = self.phrase_end(quote, m.end())
                if not quote[m.end() : tend].strip():
                    continue
                if spec.id == "on_defined" and self.bind_name(quote, m.end()) is None:
                    continue
                count, redacted = self._count_value(m) if spec.has_count else (None, False)
                unit = (
                    self._unit_kind.get(_norm_key(m.group("unit") or "")) if spec.has_unit else None
                )
                offset = (
                    spec.offset_sign * count
                    if spec.offset_sign is not None and count is not None
                    else None
                )
                return _CMatch(spec, m.start(), m.end(), tend, offset, redacted, unit)
        return None

    def bind_name(self, text: str, pos: int) -> str | None:
        """A defined-event name immediately after the construction, optionally after
        'the'; a following capitalized or digit token means the name does not bind."""
        skip = self._skip_the_rx.match(text, pos)
        if skip is None:
            return None
        nm = self.name_rx.match(text, skip.end())
        if nm is None:
            return None
        nxt = self._next_word_rx.match(text, nm.end())
        if nxt is not None and (nxt.group(1)[:1].isupper() or nxt.group(1)[:1].isdigit()):
            return None
        return nm.group(0)

    def starts_with_calendar_date(self, quote: str, pos: int) -> bool:
        """Grammar `calendar_date_not_event`: the event phrase (after an optional
        'the') opens with a calendar date, Month Day[, Year]."""
        at = pos
        skip = self._skip_the_rx.match(quote, pos)
        if skip is not None:
            at = skip.end()
        return self.date_event_rx.match(quote, at) is not None

    def trigger_kind(self, quote: str, start: int, end: int, anchor_name: str | None) -> str | None:
        if anchor_name is not None:
            return "defined_event"
        ext = len(quote)
        for i in range(end, len(quote)):
            if quote[i] in ";.":
                ext = i
                break
        window = _norm(quote[start:ext]).lower()
        for kind, rxs in self.kind_specs:
            for rx in rxs:
                if rx.search(window):
                    return kind
        return "other_event"

    # -- unresolved reasons, in grammar order --------------------------------------------

    def in_leading_condition(self, quote: str, cstart: int) -> bool:
        """The construction sits inside a leading If / In-the-event clause, which runs
        to the clause's first comma; a leading enumeration is stripped first."""
        pos = 0
        em = self.enum_rx.match(quote)
        if em is not None:
            pos = em.end()
        im = self.leading_if_rx.match(quote, pos)
        if im is None:
            return False
        comma = quote.find(",", im.end())
        return cstart < (comma if comma != -1 else len(quote))

    def reason_fires(self, reason: str, quote: str, n: str, cm: _CMatch | None) -> bool:
        """One unresolved reason's quote test; the caller tries them in grammar order."""
        if reason == "redacted_offset":
            return cm is not None and any(
                tok in quote[cm.start : cm.trigger_end] for tok in self.redacted
            )
        if reason == "conditional_or_compound":
            return self.compound_rx.search(n) is not None or (
                cm is not None and self.in_leading_condition(quote, cm.start)
            )
        if reason == "recurring_schedule":
            return any(rx.search(n) for rx in self.recurring_rxs)
        if reason == "unsupported_unit":
            return cm is not None and cm.unit in ("hours", "months")
        if reason == "month_granularity":
            return any(rx.search(n) for rx in self.month_rxs)
        if reason == "cross_reference":
            return any(rx.search(n) for rx in self.cross_rxs)
        if reason == "business_days":
            return cm is not None and cm.unit == "business"
        if reason == "anchor_not_found":
            return cm is None and any(rx.search(n) for rx in self.cue_rxs)
        return False

    def decide_reason(self, quote: str, cm: _CMatch | None) -> str | None:
        n = _norm(quote).lower()
        for reason in self.reason_order:
            if self.reason_fires(reason, quote, n, cm):
                return reason
        return None

    # -- defined dates -------------------------------------------------------------------

    def bli_label(self, m: re.Match) -> str:
        got = _norm(m.group("lbl"))
        for label in self.labels:
            if _norm(label) == got:
                return label
        return got

    @staticmethod
    def iso_of(m: re.Match) -> str:
        month = m.group("dmonth").capitalize()
        return (
            f"{int(m.group('dyear')):04d}-{_MONTHS.index(month) + 1:02d}-{int(m.group('dday')):02d}"
        )

    @staticmethod
    def iso_flat(m: re.Match) -> str:
        month = m.group("fmonth").capitalize()
        return (
            f"{int(m.group('fyear')):04d}-{_MONTHS.index(month) + 1:02d}-{int(m.group('fday')):02d}"
        )


@lru_cache(maxsize=1)
def _engine() -> _Engine:
    return _Engine()


def _span(doc: TextDoc, evidence: Evidence, a: int, b: int) -> TimingSpan:
    start = evidence.char_start + a
    end = evidence.char_start + b
    return TimingSpan(start, end, doc.text[start:end])


def parse(doc: TextDoc, evidence: Evidence) -> ParsedTiming:
    eng = _engine()
    quote = doc.text[evidence.char_start : evidence.char_end]
    cm = eng.find_construction(quote)
    reason = eng.decide_reason(quote, cm)
    if cm is None:
        trigger = kind = None
        if reason == "month_granularity":
            mm = eng.month_span_rx.search(quote)
            if mm is not None:
                tend = eng.phrase_end(quote, mm.end())
                trigger = _span(doc, evidence, mm.start(), tend)
                kind = eng.trigger_kind(quote, mm.start(), tend, None)
        return ParsedTiming(None, None, None, None, trigger, kind, None, reason)
    anchor_name = eng.bind_name(quote, cm.keywords_end)
    trigger = _span(doc, evidence, cm.start, cm.trigger_end)
    kind = eng.trigger_kind(quote, cm.start, cm.trigger_end, anchor_name)
    if anchor_name is None and eng.starts_with_calendar_date(quote, cm.keywords_end):
        # Grammar `calendar_date_not_event` (rev 2.3): a calendar date is never an
        # event; absolute dates belong to the extraction's due_date, never timing.
        kind = None
        if reason is None:
            reason = "anchor_not_found"
    return ParsedTiming(
        cm.spec.id, cm.spec.relation, cm.offset_days, cm.unit, trigger, kind, anchor_name, reason
    )


def resolve(
    parsed: ParsedTiming, anchors: list[CitedAnchor], legacy_due: str | None = None
) -> Timing:
    """Final kind and bound. `anchors` are the cited events of the obligation's own
    agreement and its recorded base only. A legacy explicit due date that disagrees with
    the derived bound yields unresolved/conflicting_dates; an ambiguous anchor name
    (several dated candidates with different dates) yields unresolved/conflicting_dates."""

    def unresolved(why: str) -> Timing:
        return Timing(
            "unresolved",
            parsed.trigger_kind,
            parsed.trigger,
            parsed.relation,
            parsed.offset_days,
            parsed.offset_unit,
            None,
            None,
            why,
        )

    def contingent() -> Timing:
        return Timing(
            "contingent",
            parsed.trigger_kind,
            parsed.trigger,
            parsed.relation,
            parsed.offset_days,
            parsed.offset_unit,
            None,
            None,
            None,
        )

    if parsed.construction is None and parsed.reason is None:
        return Timing("untimed", None, None, None, None, None, None, None, None)
    if parsed.reason is not None:
        return unresolved(parsed.reason)
    if parsed.offset_unit == "business":
        return unresolved("business_days")
    if parsed.offset_unit in ("hours", "months"):
        return unresolved("unsupported_unit")
    if parsed.relation in ("gt", "gte"):
        return contingent()
    if parsed.anchor_name is not None:
        want = _norm(parsed.anchor_name)
        dated = [a for a in anchors if _norm(a.name) == want and a.date]
        if len({a.date for a in dated}) > 1:
            return unresolved("conflicting_dates")
        if not dated:
            return unresolved("anchor_without_date")
        try:
            bound = (
                date.fromisoformat(dated[0].date) + timedelta(days=parsed.offset_days or 0)
            ).isoformat()
        except ValueError:
            return unresolved("anchor_without_date")
        if legacy_due is not None and legacy_due != bound:
            return unresolved("conflicting_dates")
        return Timing(
            "scheduled",
            parsed.trigger_kind,
            parsed.trigger,
            parsed.relation,
            parsed.offset_days,
            parsed.offset_unit,
            dated[0].event_id,
            bound,
            None,
        )
    return contingent()


def defined_dates(doc: TextDoc) -> list[DefinedDate]:
    eng = _engine()
    out: list[DefinedDate] = []
    segs = sorted(doc.segments, key=lambda s: (s.char_start, s.char_end))
    for i, seg in enumerate(segs):
        text = doc.text[seg.char_start : seg.char_end]
        # BLI rows: '({letter}) {label}: {date}' in one segment, or the label alone with
        # the date opening the next adjacent segment of the same section. No forward
        # search past that pair, so TOC rows and cross-references never bind.
        ma = eng.form_a_rx.match(text)
        if ma is not None:
            start = seg.char_start + ma.start()
            end = seg.char_start + ma.end()
            out.append(
                DefinedDate(
                    doc.doc_id,
                    eng.bli_label(ma),
                    eng.iso_of(ma),
                    TimingSpan(start, end, doc.text[start:end]),
                    "bli_row",
                )
            )
            continue
        mb = eng.form_b_rx.match(text)
        if mb is not None and i + 1 < len(segs):
            nxt = segs[i + 1]
            if nxt.section_id == seg.section_id:
                md = eng.date_start_rx.match(doc.text[nxt.char_start : nxt.char_end])
                if md is not None:
                    end = nxt.char_start + md.end()
                    out.append(
                        DefinedDate(
                            doc.doc_id,
                            eng.bli_label(mb),
                            eng.iso_of(md),
                            TimingSpan(seg.char_start, end, doc.text[seg.char_start : end]),
                            "bli_row",
                        )
                    )
    for seg in segs:
        text = doc.text[seg.char_start : seg.char_end]
        for rx in eng.decl_rxs:
            for m in rx.finditer(text):
                dm = re.search(_DATE_FLAT_SRC, m.group(0))
                if dm is None:  # pragma: no cover - the template requires a date
                    continue
                start = seg.char_start + m.start()
                end = seg.char_start + m.end()
                out.append(
                    DefinedDate(
                        doc.doc_id,
                        _norm(m.group("dname")),
                        eng.iso_flat(dm),
                        TimingSpan(start, end, doc.text[start:end]),
                        "declaration",
                    )
                )
    out.sort(key=lambda d: (d.evidence.char_start, d.name))
    return out
