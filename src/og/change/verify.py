"""Task 17: deterministic verification of model-proposed change findings.

The model proposes RawFindings; verify_findings() decides what may be kept.
Every stored span is a copied slice of a chain document (located like
extraction evidence, via og.ground), every date or money value is a token of
its cited quote, and every explicit target reference is resolved against the
frozen alias table (prompts/change_aliases_v1.yaml) under the rev 2 R1-R3,
rev 2.1 R2-1/R2-2, rev 2.2, and rev 2.3 R3-1/R3-2 rules (a price value may be
written with its units; a stray price target label is discarded and recorded
as a ChangeCorrection, never stored). Raw output is diagnostics only.

Pre-registered stop rule: the supersession-cue list and the target grammar are
closed. A phrasing that occurs in none of the chain documents is a documented
limitation, not a blocker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date as _date
from decimal import Decimal
from pathlib import Path

import yaml

from og.change.types import (
    FINDING_KINDS,
    ChainDoc,
    ChangeCorrection,
    ChangeDrop,
    ChangeVerifyResult,
    CitedSpan,
    Finding,
    RawFinding,
)
from og.eval.gold import textdoc_sha256
from og.extract.types import Evidence
from og.extract.verify import _find_dates, _money_candidates
from og.ground import Span, ground, normalize_ws
from og.textdoc import Segment, TextDoc

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALIASES_PATH = ROOT / "prompts" / "change_aliases_v1.yaml"

# Rev 2 R1: the closed supersession-cue list (whole word, case-insensitive).
_RE_CUE = re.compile(
    r"\b(?:replaced|deleted|amended\s+and\s+restated|superseded|supersedes|supersede"
    r"|in\s+lieu\s+of|no\s+further\s+force\s+or\s+effect|deemed\s+to\s+refer\s+to"
    r"|deemed\s+to\s+be\s+references\s+to|deemed\s+to\s+mean\s+and\s+refer\s+to"
    r"|notwithstanding\s+anything\s+in\s+the\s+lease\s+to\s+the\s+contrary)\b",
    re.IGNORECASE,
)

# Rev 2 R3 / rev 2.1 R2-2 date-role classes. A starred term is a prefix that
# runs to the word's end; the others are whole words.
_ROLE_CLASS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (cls, re.compile(pat, re.IGNORECASE))
    for cls, pat in (
        (
            "END",
            r"\b(?:surrender\w*|expir\w*|terminat\w*|ending|end|through|until"
            r"|no\s+later\s+than)\b",
        ),
        ("START", r"\b(?:commenc\w*|begin\w*|start\w*)\b"),
        ("DELIVERY", r"\b(?:deliver\w*|complet\w*|install\w*)\b"),
        ("PAYMENT", r"\b(?:pay\w*|due)\b"),
    )
)

# Rev 2 R3: prior-state cues for a `self` old side of a shifted date.
_RE_PRIOR_STATE = re.compile(
    r"\b(?:currently|scheduled|heretofore|previously|presently|existing|original"
    r"|originally|prior)\b",
    re.IGNORECASE,
)

# Rev 2 R1 / rev 2.1 R2-1: the closed explicit-target grammar.
_TGT_ID = r"[0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*"
_TGT_QUOTE = r"[“”\"']?"
_TGT_KIND = r"Section|Article|Item|Exhibit|Table"


@dataclass(frozen=True)
class _TargetEntry:
    doc: str
    textdoc_sha256: str
    kind: str
    id: str
    qualifier: str | None = None
    parent: tuple[str, str] | None = None  # (kind, id), e.g. ("Exhibit", "F")
    first: str = ""
    last: str = ""


@dataclass(frozen=True)
class _AliasConfig:
    """One chain's frozen alias table (rev 2 R1, rev 2.1 R2-1)."""

    base: str
    alias_to_doc: dict[str, str]
    unresolved: frozenset[str]
    targets: tuple[_TargetEntry, ...]
    qualifier_re: re.Pattern[str] | None = None
    generic_re: re.Pattern[str] | None = None


@dataclass(frozen=True)
class _Ref:
    """One recognized explicit target reference, copied from the new quote."""

    kind: str  # Section | Article | Item | Exhibit | Table
    id: str
    alias: str | None  # None only for the Basic Lease Information production
    qualifier: str | None
    parent: tuple[str, str] | None
    label: str  # the matched text, copied


def _load_alias_config(path: str | Path, base_id: str) -> _AliasConfig:
    """Load the chain's aliases; a missing or unmatched file resolves nothing.

    With no entry every alias counts as unresolved, so an old side named for
    one is dropped (target_not_in_corpus) rather than guessed at.
    """
    cfg = _AliasConfig(base_id, {}, frozenset(), ())
    alias_to_doc: dict[str, str] = {}
    unresolved = frozenset()
    p = Path(path)
    if not p.is_file():
        return cfg
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for chain in data.get("chains") or []:
        if chain.get("base") != base_id:
            continue
        alias_to_doc = {}
        for doc_id, words in (chain.get("aliases") or {}).items():
            for word in words or []:
                alias_to_doc[word] = doc_id
        unresolved = frozenset(chain.get("unresolved") or [])
        targets = tuple(
            _TargetEntry(
                doc=t["doc"],
                textdoc_sha256=t["textdoc_sha256"],
                kind=t["kind"],
                id=str(t["id"]),
                qualifier=t.get("qualifier"),
                parent=((t["parent"]["kind"], str(t["parent"]["id"])) if t.get("parent") else None),
                first=t.get("first", ""),
                last=t.get("last", ""),
            )
            for t in chain.get("targets") or []
        )
        cfg = _AliasConfig(base_id, alias_to_doc, unresolved, targets)
        break
    words = sorted(set(alias_to_doc) | set(unresolved), key=len, reverse=True)
    if not words:
        return cfg
    alias_alt = "|".join(re.escape(w) for w in words)
    qualifier_re = re.compile(
        r"Item\s+(" + _TGT_ID + r")\s+of\s+the\s+Basic\s+Lease\s+Information"
        r"(?:\s+to\s+the\s+(" + alias_alt + r"))?\b"
    )
    generic_re = re.compile(
        r"\b(?P<kind>"
        + _TGT_KIND
        + r")\s+"
        + _TGT_QUOTE
        + r"(?P<id>"
        + _TGT_ID
        + r")"
        + _TGT_QUOTE
        + r"\s+(?:of|to)\s+(?:Exhibit\s+"
        + _TGT_QUOTE
        + r"(?P<pid>"
        + _TGT_ID
        + r")"
        + _TGT_QUOTE
        + r"\s+(?:of|to)\s+)?(?:the\s+)?(?P<alias>"
        + alias_alt
        + r")\b"
    )
    return _AliasConfig(
        cfg.base, cfg.alias_to_doc, cfg.unresolved, cfg.targets, qualifier_re, generic_re
    )


def _recognize(text: str, cfg: _AliasConfig) -> _Ref | None:
    """The leftmost explicit target reference in the new quote, or None."""
    if cfg.qualifier_re is None or cfg.generic_re is None:
        return None
    hits = [m for m in (cfg.qualifier_re.search(text), cfg.generic_re.search(text)) if m]
    if not hits:
        return None
    m = min(hits, key=lambda h: (h.start(), -len(h.group(0))))
    if m.re is cfg.qualifier_re:
        return _Ref(
            kind="Item",
            id=m.group(1),
            alias=m.group(2),
            qualifier="Basic Lease Information",
            parent=None,
            label=m.group(0),
        )
    pid = m.group("pid")
    return _Ref(
        kind=m.group("kind"),
        id=m.group("id"),
        alias=m.group("alias"),
        qualifier=None,
        parent=("Exhibit", pid) if pid else None,
        label=m.group(0),
    )


# ---------------------------------------------------------------- location


def _segment_containing(doc: TextDoc, offset: int) -> Segment | None:
    for seg in doc.segments:
        if seg.char_start <= offset < seg.char_end:
            return seg
    return None


def _locate(
    doc: TextDoc, segment_id: str | None, quote: str | None
) -> tuple[Evidence | None, str | None]:
    """Ground a quote in its cited segment, located like extraction evidence."""
    if not segment_id:
        return None, "unknown_segment"
    try:
        seg = doc.segment(segment_id)
    except KeyError:
        return None, "unknown_segment"
    gr = ground(doc, Span(quote or "", seg.char_start, seg.char_end, seg.section_id))
    if not gr.grounded or gr.char_start is None or gr.char_end is None:
        return None, "not_found_in_section"
    start, end = gr.char_start, gr.char_end
    seg_start = _segment_containing(doc, start) or seg
    section = doc.section_for(start)
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
    return evidence, None


# ---------------------------------------------------------------- values


def _iso(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return _date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _parse_money(value: str | None) -> Decimal | None:
    if not isinstance(value, str) or not value.strip():
        return None
    t = value.strip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    t = t.replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    return Decimal(t)


def _claim_amount(value: str | None) -> Decimal | None:
    """The claimed price amount (rev 2.3 R3-1).

    The schema asks for the value "exactly as written in new_quote", so a
    claim is accepted when it is a plain decimal, as before, or when it
    carries exactly one money token of the wave 2 grammar (e.g.
    "$41,496.00/month"). Two or more money tokens are ambiguous; the amount
    must still equal a money token of the cited quote, and the stored value
    stays the plain decimal string.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    tokens = _money_candidates(value)
    if len(tokens) == 1:
        return tokens[0]
    if tokens:
        return None
    return _parse_money(value)


# ---------------------------------------------------------------- date roles


def _role_word(seg_text: str, date_start: int) -> tuple[str, int, int] | None:
    """(class, start, end) of the nearest role word before the date (R2-2).

    The word must be the nearest one that precedes the date in the segment with
    no other date token in between.
    """
    bound = 0
    for _iso_v, s, e in _find_dates(seg_text):
        if e <= date_start and s < date_start:
            bound = max(bound, e)
    best: tuple[int, int, str] | None = None
    for cls, pat in _ROLE_CLASS_PATTERNS:
        for m in pat.finditer(seg_text):
            if (
                m.end() <= date_start
                and m.start() >= bound
                and (best is None or m.start() > best[0])
            ):
                best = (m.start(), m.end(), cls)
    if best is None:
        return None
    return best[2], best[0], best[1]


def _quote_role(doc: TextDoc, evidence: Evidence, iso: str) -> tuple[str, int, int] | None:
    """The role of the quote's date, with the word's span in segment offsets.

    The role is computed on the containing source segment, never on the quote;
    the caller checks the word lies inside the cited quote.
    """
    seg = doc.segment(evidence.segment_id)
    seg_text = doc.text[seg.char_start : seg.char_end]
    for value, s, e in _find_dates(seg_text):
        if value != iso:
            continue
        if seg.char_start + s >= evidence.char_start and seg.char_start + e <= evidence.char_end:
            return _role_word(seg_text, s)
    return None


# ---------------------------------------------------------------- targets


def _alias_doc(ref: _Ref, cfg: _AliasConfig, doc_ids: frozenset[str]) -> str | None:
    """The chain agreement an explicit reference points at, or None."""
    if ref.alias is None:  # the Basic Lease Information production, no alias
        return cfg.base if cfg.base in doc_ids else None
    if ref.alias in cfg.unresolved:
        return None
    doc = cfg.alias_to_doc.get(ref.alias)
    if doc is None or doc not in doc_ids:
        return None
    return doc


def _find_entry(
    ref: _Ref, doc_id: str, cfg: _AliasConfig, docs: dict[str, ChainDoc]
) -> tuple[_TargetEntry, Segment, Segment] | None:
    """The sha-pinned range entry for a reference, with its boundary segments."""
    for entry in cfg.targets:
        if (
            entry.doc == doc_id
            and entry.kind == ref.kind
            and entry.id == ref.id
            and (entry.qualifier or None) == (ref.qualifier or None)
            and (entry.parent or None) == ref.parent
            and entry.first
            and entry.last
        ):
            member = docs.get(entry.doc)
            if member is None or textdoc_sha256(member.doc) != entry.textdoc_sha256:
                continue
            try:
                first = member.doc.segment(entry.first)
                last = member.doc.segment(entry.last)
            except KeyError:
                continue
            return entry, first, last
    return None


def _target_stage(
    raw: RawFinding,
    new_span_text: str,
    old_present: bool,
    old_doc_id: str | None,
    old_evidence: Evidence | None,
    cfg: _AliasConfig,
    docs: dict[str, ChainDoc],
) -> tuple[str | None, str | None, str | None]:
    """Validate the target label and resolve the explicit reference.

    Returns (target_label, target_resolution, drop_reason). The rev 2 R1 /
    rev 2.1 R2-1 rules apply only to supersedes and potential_conflict
    (rev 2.2); the copied-label rule applies to every kind.
    """
    if raw.target_label is not None and normalize_ws(raw.target_label) not in normalize_ws(
        new_span_text
    ):
        return None, None, "target_label_not_in_quote"
    if raw.kind not in ("supersedes", "potential_conflict"):
        return raw.target_label, None, None
    ref = _recognize(new_span_text, cfg)
    if ref is None:
        if raw.kind == "supersedes" and not old_present and raw.target_label is None:
            return None, None, "target_label_required"
        return raw.target_label, None, None
    label = ref.label  # copied from the quote (rev 2.2 fills a null label)
    doc_id = _alias_doc(ref, cfg, frozenset(docs))
    if doc_id is None:
        if old_present:
            return None, None, "target_not_in_corpus"
        return label, "unresolved", None
    if ref.kind in ("Section", "Article"):
        if old_present:
            assert old_doc_id is not None and old_evidence is not None
            section = docs[old_doc_id].doc.section_for(old_evidence.char_start)
            number = section.number if section is not None else None
            if number is None or not (number == ref.id or number.startswith(ref.id + ".")):
                return None, None, "target_section_mismatch"
        return label, "section", None
    found = _find_entry(ref, doc_id, cfg, docs)
    if found is None:
        if old_present:
            return None, None, "target_clause_unresolved"
        return label, "document", None
    _entry, first, last = found
    if old_present:
        assert old_doc_id is not None and old_evidence is not None
        if old_doc_id != found[0].doc:
            return None, None, "target_range_mismatch"
        if not (
            first.char_start <= old_evidence.char_start and old_evidence.char_end <= last.char_end
        ):
            return None, None, "target_range_mismatch"
    return label, "range", None


# ---------------------------------------------------------------- verify


def _dedupe_key(finding: Finding) -> tuple:
    old = (
        (
            finding.old.agreement_id,
            finding.old.evidence.char_start,
            finding.old.evidence.char_end,
        )
        if finding.old
        else None
    )
    return (
        finding.kind,
        finding.new.agreement_id,
        finding.new.evidence.char_start,
        finding.new.evidence.char_end,
        old,
    )


def _verify_one(
    raw: RawFinding,
    co: ChainDoc,
    docs: dict[str, ChainDoc],
    cfg: _AliasConfig,
    category: str,
) -> tuple[Finding | ChangeDrop, ChangeCorrection | None]:
    """One raw finding: the kept Finding or the drop, plus a field correction."""

    def drop(reason: str) -> ChangeDrop:
        return ChangeDrop(raw=raw, category=category, reason=reason)

    if raw.kind not in FINDING_KINDS:
        return drop("unknown_kind"), None

    # 1. The new side grounds in the change order.
    new_evidence, reason = _locate(co.doc, raw.new_segment_id, raw.new_quote)
    if new_evidence is None:
        assert reason is not None
        return drop(reason), None
    new_span = CitedSpan(co.agreement_id, new_evidence)
    new_text = new_evidence.span_text

    # 2. The old side: a chain agreement other than the change order, or "self".
    if (
        raw.old_doc is not None
        and raw.old_doc != "self"
        and (raw.old_doc not in docs or docs[raw.old_doc].role == "change_order")
    ):
        return drop("old_doc_not_in_chain"), None
    old_present = raw.old_doc is not None
    if old_present:
        if raw.old_quote is None or raw.old_segment_id is None:
            return drop("old_side_incomplete"), None
    elif raw.old_quote is not None or raw.old_segment_id is not None or raw.old_value is not None:
        return drop("old_side_incomplete"), None
    old_evidence: Evidence | None = None
    old_span: CitedSpan | None = None
    old_doc_id: str | None = None
    old_origin = "unresolved"
    if old_present:
        assert raw.old_doc is not None
        old_doc_id = co.agreement_id if raw.old_doc == "self" else raw.old_doc
        old_evidence, reason = _locate(docs[old_doc_id].doc, raw.old_segment_id, raw.old_quote)
        if old_evidence is None:
            assert reason is not None
            return drop(reason), None
        old_span = CitedSpan(old_doc_id, old_evidence)
        old_origin = "self" if raw.old_doc == "self" else "chain"

    # 3. Target label and explicit-reference resolution. Rev 2.3 R3-2: a
    #    price finding never stores a target label (rev 2.2); a stray one is
    #    discarded and recorded as a ChangeCorrection, never a drop. For
    #    supersedes and potential_conflict the label is the target, so the
    #    strict drop stays.
    correction: ChangeCorrection | None = None
    stage_raw = raw
    if raw.kind == "price_change" and raw.target_label is not None:
        if normalize_ws(raw.target_label) not in normalize_ws(new_text):
            correction = ChangeCorrection(
                raw=raw,
                category=category,
                field="target_label",
                reason="target_label_not_in_quote",
            )
        stage_raw = replace(raw, target_label=None)
    label, resolution, reason = _target_stage(
        stage_raw, new_text, old_present, old_doc_id, old_evidence, cfg, docs
    )
    if reason is not None:
        return drop(reason), None

    # 4. Kind rules.
    old_text = old_evidence.span_text if old_evidence is not None else ""

    if raw.kind == "supersedes":
        if not _RE_CUE.search(new_text):
            return drop("no_supersession_cue"), None
        if raw.old_value is not None or raw.new_value is not None:
            return drop("values_forbidden"), None
        return Finding(
            kind=raw.kind,
            category=category,
            new=new_span,
            old=old_span,
            old_origin=old_origin,
            target_label=label,
            target_resolution=resolution,
            old_value=None,
            new_value=None,
            delta=None,
            currency=None,
            context=None,
        ), correction

    if raw.kind == "shifted_date":
        if not old_present:
            return drop("old_side_required"), None
        assert old_doc_id is not None and old_evidence is not None
        new_dates = _find_dates(new_text)
        old_dates = _find_dates(old_text)
        if len(new_dates) != 1 or len(old_dates) != 1:
            return drop("date_token_count"), None
        if _iso(raw.new_value) != new_dates[0][0]:
            return drop("new_value_not_in_quote"), None
        if _iso(raw.old_value) != old_dates[0][0]:
            return drop("old_value_not_in_quote"), None
        new_iso, old_iso = new_dates[0][0], old_dates[0][0]
        if new_iso == old_iso:
            return drop("dates_equal"), None
        new_role = _quote_role(co.doc, new_evidence, new_iso)
        old_role = _quote_role(docs[old_doc_id].doc, old_evidence, old_iso)

        def role_inside(
            doc: TextDoc, evidence: Evidence, role: tuple[str, int, int] | None
        ) -> bool:
            if role is None:
                return False
            _cls, w_start, w_end = role
            seg = doc.segment(evidence.segment_id)
            rel_start = seg.char_start + w_start
            rel_end = seg.char_start + w_end
            return evidence.char_start <= rel_start and rel_end <= evidence.char_end

        if not role_inside(co.doc, new_evidence, new_role) or not role_inside(
            docs[old_doc_id].doc, old_evidence, old_role
        ):
            return drop("date_role_outside_quote"), None
        assert new_role is not None and old_role is not None
        if new_role[0] != old_role[0]:
            return drop("date_role_mismatch"), None
        if raw.old_doc == "self" and not _RE_PRIOR_STATE.search(old_text):
            return drop("old_state_cue_missing"), None
        delta = (_date.fromisoformat(new_iso) - _date.fromisoformat(old_iso)).days
        return Finding(
            kind=raw.kind,
            category=category,
            new=new_span,
            old=old_span,
            old_origin=old_origin,
            target_label=label,
            target_resolution=resolution,
            old_value=old_iso,
            new_value=new_iso,
            delta=str(delta),
            currency=None,
            context=None,
        ), correction

    if raw.kind == "price_change":
        candidates = _money_candidates(new_text)
        claimed = _claim_amount(raw.new_value)
        if claimed is None or not any(c == claimed for c in candidates):
            return drop("new_value_not_in_quote"), None
        if raw.old_value is not None:
            return drop("old_value_forbidden"), None
        if old_present:
            return drop("old_side_forbidden"), None
        context: CitedSpan | None = None
        if raw.context_quote is not None or raw.context_segment_id is not None:
            if raw.context_quote is None or raw.context_segment_id is None:
                return drop("context_not_found"), None
            context_evidence, ctx_reason = _locate(
                co.doc, raw.context_segment_id, raw.context_quote
            )
            if context_evidence is None or ctx_reason is not None:
                return drop("context_not_found"), None
            context = CitedSpan(co.agreement_id, context_evidence)
        stored = next(c for c in candidates if c == claimed)
        return Finding(
            kind=raw.kind,
            category=category,
            new=new_span,
            old=None,
            old_origin="unresolved",
            target_label=None,
            target_resolution=None,
            old_value=None,
            new_value=str(stored),
            delta=None,
            currency="USD" if "$" in new_text else None,
            context=context,
        ), correction

    # potential_conflict
    if not old_present:
        return drop("old_side_required"), None
    if raw.old_doc == "self":
        return drop("old_side_forbidden"), None
    if raw.old_value is not None or raw.new_value is not None:
        return drop("values_forbidden"), None
    return Finding(
        kind=raw.kind,
        category=category,
        new=new_span,
        old=old_span,
        old_origin="chain",
        target_label=label,
        target_resolution=resolution,
        old_value=None,
        new_value=None,
        delta=None,
        currency=None,
        context=None,
    ), correction


def verify_findings(
    chain: list[ChainDoc],
    category: str,
    items: list[RawFinding],
    aliases_path: str | Path | None = None,
) -> ChangeVerifyResult:
    """Turn model-proposed RawFindings into Findings plus drops, deterministically.

    `chain` is the ordered chain (base, prior amendments, change order last).
    `aliases_path` defaults to the frozen prompts/change_aliases_v1.yaml.
    """
    docs = {member.agreement_id: member for member in chain}
    co = next(
        (member for member in reversed(chain) if member.role == "change_order"),
        chain[-1],
    )
    base_id = next((member.agreement_id for member in chain if member.role == "base"), "")
    cfg = _load_alias_config(aliases_path or DEFAULT_ALIASES_PATH, base_id)

    findings: list[Finding] = []
    drops: list[ChangeDrop] = []
    corrections: list[ChangeCorrection] = []
    seen: set[tuple] = set()
    for raw in items:
        result, correction = _verify_one(raw, co, docs, cfg, category)
        if isinstance(result, ChangeDrop):
            drops.append(result)
            continue
        key = _dedupe_key(result)
        if key in seen:
            drops.append(ChangeDrop(raw=raw, category=category, reason="duplicate"))
        else:
            seen.add(key)
            findings.append(result)
            if correction is not None:  # a correction applies only to a kept finding
                corrections.append(correction)
    return ChangeVerifyResult(findings=findings, drops=drops, corrections=corrections)
