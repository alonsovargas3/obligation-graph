"""Change-order contract (wave 3; coordinator-authored, frozen).

The model proposes RawFindings. verify_findings() turns them into Findings whose
every stored span is a copied slice of a chain document and whose every value is
a token of its cited quote, bound by the rev 2/2.1 rules. Raw output is
diagnostics only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from og.extract.types import Attempt, Evidence
from og.textdoc import TextDoc

CATEGORIES = ("price", "dates", "termination", "guarantee", "sla", "parties_or_sites")
FINDING_KINDS = ("supersedes", "shifted_date", "price_change", "potential_conflict")
OLD_ORIGINS = ("chain", "self", "unresolved")
TARGET_RESOLUTIONS = ("section", "range", "document", "unresolved")
CHECK_STATUSES = ("ok", "refused", "truncated", "invalid", "error", "budget_stop")
MODES = ("ungated", "gated")
ROLES = ("base", "prior_amendment", "change_order")

# Every field of one finding in prompts/change_v1.schema.json, in schema order.
RAW_FINDING_FIELDS = (
    "new_quote",
    "new_segment_id",
    "kind",
    "old_doc",
    "old_quote",
    "old_segment_id",
    "old_value",
    "new_value",
    "target_label",
    "context_quote",
    "context_segment_id",
)

DROP_REASONS = (
    "unknown_kind",
    "unknown_segment",
    "not_found_in_section",
    "old_doc_not_in_chain",
    "old_side_incomplete",
    "old_side_required",
    "old_side_forbidden",
    "target_label_not_in_quote",
    "target_label_required",
    "target_not_in_corpus",
    "target_section_mismatch",
    "target_range_mismatch",
    "target_clause_unresolved",
    "no_supersession_cue",
    "values_forbidden",
    "new_value_not_in_quote",
    "old_value_not_in_quote",
    "old_value_forbidden",
    "dates_equal",
    "date_token_count",
    "date_role_outside_quote",
    "date_role_mismatch",
    "old_state_cue_missing",
    "context_not_found",
    "duplicate",
)


@dataclass(frozen=True)
class ChainDoc:
    agreement_id: str
    doc: TextDoc
    role: str  # one of ROLES


@dataclass(frozen=True)
class ChainMember:
    agreement_id: str
    role: str  # one of ROLES
    source_sha256: str
    textdoc_sha256: str  # og.eval.gold.textdoc_sha256 of the loaded TextDoc
    extraction_run_id: str  # extraction_run.run_id of the current snapshot


@dataclass(frozen=True)
class ChainSnapshot:
    """Ordered: base first, then corpus amendments by filing date, change order last."""

    members: tuple[ChainMember, ...]

    @property
    def change_order_id(self) -> str:
        return self.members[-1].agreement_id

    def vector(self) -> tuple[tuple[str, str, str], ...]:
        return tuple((m.agreement_id, m.textdoc_sha256, m.extraction_run_id) for m in self.members)


@dataclass(frozen=True)
class RawFinding:
    new_quote: str
    new_segment_id: str
    kind: str
    old_doc: str | None  # chain agreement_id, "self", or None (target not provided)
    old_quote: str | None
    old_segment_id: str | None
    old_value: str | None
    new_value: str | None
    target_label: str | None
    context_quote: str | None
    context_segment_id: str | None


@dataclass(frozen=True)
class CitedSpan:
    agreement_id: str
    evidence: Evidence


@dataclass(frozen=True)
class Finding:
    kind: str
    category: str
    new: CitedSpan
    old: CitedSpan | None
    old_origin: str  # one of OLD_ORIGINS; "unresolved" iff old is None
    target_label: str | None
    target_resolution: str | None  # one of TARGET_RESOLUTIONS, or None when no explicit target
    old_value: str | None  # ISO date (shifted_date) or None
    new_value: str | None  # ISO date, or a plain decimal string for money (e.g. "35596.80")
    delta: str | None  # whole days for shifted_date; None otherwise in rev 2
    currency: str | None  # "USD" only when the new quote has "$"
    context: CitedSpan | None  # price_change row period or heading, same document as new


@dataclass(frozen=True)
class ChangeDrop:
    raw: RawFinding
    category: str
    reason: str  # one of DROP_REASONS


@dataclass(frozen=True)
class ChangeVerifyResult:
    findings: list[Finding]
    drops: list[ChangeDrop]


@dataclass(frozen=True)
class CheckOutcome:
    category: str
    status: str  # one of CHECK_STATUSES
    items: list[RawFinding]
    attempts: list[Attempt]
    cache_hit: bool
    latency_ms: int | None
    request_fingerprint: str
    error: str | None  # short code, never a repr


@dataclass(frozen=True)
class ChangeRunInfo:
    run_id: str
    pair_id: str
    mode: str  # one of MODES
    prompt_version: str  # "change_v1@<sha8 of prompt+schema>"
    question_set_sha256: str
    model: str
    fingerprints: dict[str, str]  # category -> request fingerprint (checks that ran)
    baseline_run_id: str | None  # gated: the paired ungated run_id
    cost_usd: float | None
    incremental_cost_usd: float | None
    latency_ms: int | None


class SnapshotChanged(Exception):
    """The chain snapshot no longer matches the DB or TextDocs; args[0] is a short code."""


class ReportFinding(TypedDict):
    kind: str
    categories: list[str]
    new: dict  # ClauseRef dict: agreement_id, section, page, char_start, char_end, span_text
    old: dict | None
    old_origin: str
    target_label: str | None
    target_resolution: str | None
    old_value: str | None
    new_value: str | None
    delta: str | None
    currency: str | None
    context: dict | None


class ChangeReport(TypedDict):
    change_order_id: str
    mode: str
    run_id: str
    pair_id: str
    chain: list[dict]  # [{agreement_id, role, extraction_run_id}]
    unresolved_documents: list[str]  # aliases named by the change order but absent from the corpus
    supersessions: list[ReportFinding]
    shifted_dates: list[ReportFinding]
    price_changes: list[ReportFinding]
    potential_conflicts: list[ReportFinding]
    # visible change-order obligations without a resolved supersession edge
    new_obligations: list[dict]
    # one per category: question, tier, backend, answer, confidence, run_check, error
    gates: list[dict]
    cost_usd: float | None
    incremental_cost_usd: float | None


ROLE_LITERAL = Literal["base", "prior_amendment", "change_order"]
