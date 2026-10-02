"""Decision-gate contract (wave 3; coordinator-authored, frozen). ADR-003."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from og.textdoc import TextDoc

QUESTIONS_PATH = Path(__file__).resolve().parents[3] / "prompts" / "gate_questions_v1.yaml"
TIERS = ("rules", "classifier", "none")
# Pre-registered skip policy (rev 2 R5): exactly three literal False samples, no error.
GATE_POLICY = {"samples": 3, "skip": "unanimous_false"}
ERROR_CODES = (
    "timeout",
    "refused",
    "truncated",
    "invalid",
    "unavailable",
    "budget_stop",
    "exception",
)


@dataclass(frozen=True)
class Question:
    id: str  # "touches_<category>"
    category: str
    definition: str
    lexicon: tuple[str, ...]
    section_types: frozenset[str]


@dataclass(frozen=True)
class GateEvidence:
    rule: str  # "lexicon:<term>" or "section_ref:<base section>-><obligation type>"
    segment_id: str
    char_start: int
    char_end: int
    text: str  # == change_order.text[char_start:char_end]


@dataclass(frozen=True)
class GateContext:
    # base section number -> visible obligation types in it
    base_section_types: Mapping[str, frozenset[str]]


@dataclass(frozen=True)
class GateDecision:
    question: str
    backend: str
    tier: str  # one of TIERS
    answer: bool | None
    confidence: float | None
    samples: tuple[bool | None, ...]
    evidence: tuple[GateEvidence, ...]
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    error: str | None  # one of ERROR_CODES or an exception class name
    run_check: bool


class DecisionGate(Protocol):
    name: str

    def decide(
        self, question: Question, change_order: TextDoc, context: GateContext
    ) -> GateDecision: ...


def load_questions(path: str | Path = QUESTIONS_PATH) -> list[Question]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [
        Question(
            id=q["id"],
            category=q["category"],
            definition=q["definition"].strip(),
            lexicon=tuple(q["lexicon"]),
            section_types=frozenset(q["section_types"]),
        )
        for q in raw["questions"]
    ]
