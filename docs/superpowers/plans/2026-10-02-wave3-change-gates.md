# Wave 3: Change-Order Diff and Decision Gates Implementation Plan (rev 1)

> **For agentic workers:** you are a supervised Orca worker. Do only your Task. Tests under `tests/` are frozen (pinned by `tests/FROZEN.sha256`), and so are the coordinator-authored contract files listed under "Contract files". You write implementation code only. Use `ask` for any ambiguity. Send `worker_done` once. You never hold or read an API key, and nothing in your Task calls the network.

**Goal:** CLAUDE.md build steps 7 and 8, plus the change-order half of step 11. An amendment is diffed against its agreement chain into a cited `ChangeReport`. Six bounded gate questions decide which focused checks run. Every change order is run twice (ungated, gated), and gate recall is measured against both the ungated run and a reference set.

**Architecture:**

```
chain = base agreement + earlier amendments in the corpus (filing order) + the change order
change order ──RulesGate (deterministic)──▶ hit? ─yes──────────────────────────────┐
                    └─no──▶ HaikuGate (x3 samples) ──unanimous confident "no"?──no─┤ (fail open)
                                                         └─yes──▶ skip check       ▼
                                          focused full check per category (Sonnet, chain in cached prompt)
                                          RawFinding[] ──verify (deterministic)──▶ Finding[] + ChangeDrop[]
                                          ──writer (one transaction per change order + mode)──▶ graph.db
graph.db + eval/gold/change/<co>.yaml ──score──▶ eval/results/<date>-change.json
```

- The model proposes findings. Deterministic `verify` decides what is kept, using the same copied-slice rule as extraction.
- New obligations come from the extraction graph (the amendment's visible obligations), not from a model call.
- A gate can only skip a check. It never removes a finding.

**Tech Stack:** Python 3.12, uv, `anthropic` (locked), sqlite3, pyyaml, pytest, ruff. No new dependencies.

**Spec:** `CLAUDE.md` (Change-order diff, Decision gates, Evaluation, Definition of done), ADR-003 (fail-open gates), ADR-005 (span selection), ADR-008 (extraction contract), the wave 2 plan and report.

## Global Constraints

- **The invariant:** every finding carries a ClauseRef in the change order whose `span_text == text[char_start:char_end]`. Any old-side reference is a ClauseRef in a chain document, with the same property. Old or new values (dates, amounts) are kept only if their tokens occur in the cited quote. The writer is the only code that sets `grounded = 1`.
- **Fail open:**
  - A check is skipped only when the rules tier found no hit and the classifier returned a unanimous, error-free "no" (all samples).
  - Errors, timeouts, refusals, unparseable output, a missing backend, or any disagreement mean the check runs.
  - A run in which any check that should run fails (refused, truncated, invalid, error, budget stop) is incomplete. Nothing is written for that mode, and the previous snapshot stays.
- **Gate recall is the headline metric:**
  - Every change order runs ungated (all six checks) and then gated.
  - Gate recall is reported against the ungated run (category positive = the ungated check for it kept at least one finding) and against the reference labels.
  - The skip rule is pre-registered (unanimous 3/3 "no"), not tuned on the test set. A Clopper-Pearson 95% upper bound on the miss rate is reported, however wide.
- **Graph edges come from ungated runs only:**
  - `supersedes` edges and the derived `superseded` lifecycle are written only by ungated runs.
  - Gated runs write their findings and gate decisions for the cost and recall comparison.
- **Derived data is rebuilt, not migrated:**
  - Schema v3 sets `PRAGMA user_version = 3`. A v2 file raises `SchemaOutdated` with "delete data/graph.db and run make extract".
  - Re-extraction is free from the cache.
  - Re-extracting any chain document deletes the change runs that depend on it, inside the extraction transaction.
- **API (coordinator-only at runtime):**
  - **Full check:** `OG_EXTRACT_MODEL` (default `claude-sonnet-5-5`), with `OG_CHANGE_EFFORT` (default `high`) and `max_tokens` 8192. The request shape is identical to extraction: `client.beta.messages.create`, `output_config.format` json_schema, server-side fallback beta, and no `temperature`, `thinking`, `tools`, or `tool_choice`.
  - **Check prompt caching:** the system block, then the chain rendering, then the change order, with an ephemeral cache breakpoint after each. The category instruction goes last and is uncached.
  - **Gate:** `OG_GATE_MODEL` (default `claude-haiku-4-5-20251001`) via `client.messages.create`, with `max_tokens` 64. Structured output is `{"answer": "yes"|"no"}`, if probe C0 confirms Haiku accepts it. `temperature` is not set, so the samples can differ. The gate makes `OG_GATE_SAMPLES` (default 3) calls, each with timeout `OG_GATE_TIMEOUT_S` (default 30).
  - **Response handling:** check `stop_reason` before parsing.
- **Cost:**
  - Priced from recorded usage with `og.pricing.PRICES_2026_10` (Sonnet 5.5 and Haiku 4.5).
  - Each run records `cost_usd` (all recorded usage, including cache replays) and `incremental_cost_usd` (real calls only).
  - The gated run reuses the ungated run's check responses from the cache (same fingerprint), so its check cost is the recorded cost of the checks it ran.
  - `OG_BUDGET_USD`, if set, stops new API calls in one CLI invocation once its incremental spend reaches the limit. The run becomes incomplete.
- **Secrets:** unchanged from wave 2. Credentials come only from the environment, logs are written through allowlists, and a sentinel-key test covers every file written.
- **Tests:** offline only, using `FakeClient` (labeled synthetic) or coordinator-recorded real responses. Never `ruff check --fix`. No em dashes in user-facing copy.

## Review Focus

1. **Out-of-corpus target:**
   - 3A §1.C reads "Section 2.C of 2A is hereby deleted". 2A is not in the corpus.
   - The kept finding has `old = None` and a `target_label` copied from the quote.
   - A finding that cites a base-lease clause for it passes verify only if its quote grounds; eval scores it as a mismatch.
2. **Old value stated only in the amendment:**
   - 3A §1.A: "scheduled to be surrendered to Landlord on June 30, 2018" … "expiring June 30, 2020".
   - This is a `shifted_date` with `old_doc = "self"`, both dates verified in their quotes, and delta 731 days.
3. **A derived number the quote never states:** a `price_change` with `new_value` "$427,161.60" (an annualized figure) is dropped (`new_value_not_in_quote`).
4. **Gate backend failure:** Haiku times out on one of 3 samples. The check runs, and the decision is logged with the error and `run_check = true`.
5. **Re-extract a base after a change run:** `make extract --doc constantcontact-2011-ex1041` succeeds (no FK error), and both change runs for 1A and 3A disappear from the visible views until `make change` reruns.
6. **Gated is a subset:** for each category that ran in both modes, the gated findings equal the ungated findings (same cached response), and a skipped category has none.

---

## Contract files (coordinator-authored in B3, frozen)

- **`src/og/pricing.py`:** `PRICES_2026_10` (Sonnet 5.5: 2.00 / 10.00 / 0.20 / 2.50; Haiku 4.5: 1.00 / 5.00 / 0.10 / 1.25 per Mtok for input / output / cache read / cache write) and `PRICE_BASIS`. Also `price(attempts: Iterable[Attempt]) -> tuple[float | None, str]`, which returns `(None, "unknown_model")` if any attempt's model is unpriced. Extraction keeps its own copy; it is not refactored in this wave.
- **`src/og/change/types.py`:** the change types below.
- **`src/og/gates/types.py`:** the gate types below.
- **`prompts/change_v1.md` + `prompts/change_v1.schema.json`:** the check system prompt and output schema. The schema is flat: `required` lists all fields, `additionalProperties: false`, and nullable enums use `anyOf`, as in wave 2.
- **`prompts/gate_v1.md`, `prompts/gate_v1.schema.json`, `prompts/gate_questions_v1.yaml`:** the gate system prompt, the answer schema, and the six questions. Each question has an `id`, a `category`, a `definition` (from CLAUDE.md), `lexicon` (rules-tier terms), and `section_types` (obligation types that make a referenced base section a hit).
- **`src/og/store/schema.sql` (v3) + `src/og/store/db.py`:** the schema changes below.

**Change types** (`og.change.types`):

```python
CATEGORIES = ("price", "dates", "termination", "guarantee", "sla", "parties_or_sites")
FINDING_KINDS = ("supersedes", "shifted_date", "price_change", "conflict")
CHECK_STATUS = ("ok", "refused", "truncated", "invalid", "error", "budget_stop")

@dataclass(frozen=True)
class ChainDoc:
    agreement_id: str; doc: TextDoc; role: Literal["base", "prior_amendment", "change_order"]

@dataclass(frozen=True)
class RawFinding:          # exactly the schema's item fields
    kind: str; new_segment_id: str; new_quote: str
    old_doc: str | None    # a chain agreement_id, "self" (the change order restates the old term), or None (target not in corpus)
    old_segment_id: str | None; old_quote: str | None
    old_value: str | None; new_value: str | None
    target_label: str | None   # e.g. "Section 2.C of 2A"; must be copied from new_quote

@dataclass(frozen=True)
class CitedSpan:
    agreement_id: str; evidence: Evidence      # og.extract.types.Evidence

@dataclass(frozen=True)
class Finding:
    kind: str; category: str
    new: CitedSpan; old: CitedSpan | None; target_label: str | None
    old_value: str | None; new_value: str | None   # ISO date, or a decimal string for money
    delta: str | None                              # whole days for dates; a decimal string for money
    currency: str | None

@dataclass(frozen=True)
class ChangeDrop:
    reason: str; category: str; kind: str; new_segment_id: str; new_quote: str

@dataclass(frozen=True)
class ChangeVerifyResult:
    findings: list[Finding]; drops: list[ChangeDrop]

@dataclass(frozen=True)
class CheckOutcome:
    category: str; status: str; items: list[RawFinding]; attempts: list[Attempt]
    cache_hit: bool; latency_ms: int
```

**Gate types** (`og.gates.types`):

```python
@dataclass(frozen=True)
class Question:          # one entry of prompts/gate_questions_v1.yaml; load_questions(path) -> list[Question]
    id: str; category: str; definition: str
    lexicon: tuple[str, ...]; section_types: frozenset[str]

@dataclass(frozen=True)
class GateEvidence:
    rule: str            # "lexicon:<term>" or "section_ref:<base section>-><obligation type>"
    segment_id: str; char_start: int; char_end: int; text: str   # text == change_order.text[char_start:char_end]

@dataclass(frozen=True)
class GateContext:
    base_section_types: Mapping[str, frozenset[str]]   # base section number -> visible obligation types in it

@dataclass(frozen=True)
class GateDecision:
    question: str; backend: str; tier: Literal["rules", "classifier", "none"]
    answer: bool | None                     # None = no usable answer
    confidence: float | None                # classifier: majority share, with failed samples counted as dissent
    samples: tuple[bool | None, ...]
    evidence: tuple[GateEvidence, ...]
    latency_ms: int; input_tokens: int; output_tokens: int
    cost_usd: float | None; error: str | None
    run_check: bool

class DecisionGate(Protocol):
    name: str
    def decide(self, question: Question, change_order: TextDoc, context: GateContext) -> GateDecision: ...
```

**Schema v3 additions** (other tables unchanged; `user_version = 3`):

- `change_run(id, run_id UNIQUE, change_order_id → agreement, mode CHECK IN ('ungated','gated'), prompt_version, model, started_at, completed_at, cost_usd, incremental_cost_usd, UNIQUE(change_order_id, mode))`
- `change_run_chain(change_run_id, agreement_id, extraction_run_id, PRIMARY KEY(change_run_id, agreement_id))`: the extraction snapshots the diff was computed against.
- `change_finding(id, change_run_id, kind, category, new_clause_ref_id NOT NULL, old_clause_ref_id NULL, target_label, old_value, new_value, delta, currency)` with CHECKs on `kind` and `category`.
- `supersedes` gains `change_run_id NOT NULL`.
- `gate_decision` gains `change_run_id`, `tier`, `samples_json`, `evidence_json`, and `run_check`.
- **`visible_change_finding`:** the new ref is grounded and in the change order. The old ref is null, or grounded and in a chain agreement. Every `change_run_chain` row matches that agreement's current `extraction_run.id` (a stale diff is invisible).
- **`visible_supersedes`:** additionally requires `change_run.mode = 'ungated'` and a non-stale run.
- **`visible_obligation.lifecycle`:** `superseded` when `status = 'superseded'` or a `visible_supersedes`-equivalent edge targets the obligation. The view inlines the edge condition and does not reference `visible_supersedes`.

---

## Tasks (workers)

Every task's frozen tests are listed with it. Red is verified before dispatch.

### Task 14: RulesGate (deterministic tier). TDD.

**Files:** `src/og/gates/rules.py`. Tests: `tests/test_gates_rules.py`.

- **`RulesGate(questions)`** implements `DecisionGate`, with `name = "rules"`.
- **Lexicon hits:** whole-word, case-insensitive matches of each question's lexicon terms over the change order's segments, excluding the signature block. A trailing `*` in a term is a prefix wildcard.
- **Section references:**
  - The pattern is `Section(s)? <num>( and <num>)* of the (Original )?Lease` and `Article <num> of the (Original )?Lease`.
  - A reference resolves to a base section number in `GateContext`. It is a hit when that section's obligation types intersect the question's `section_types`.
  - A reference to another document (`Section 2.C of 2A`) is not a base reference.
- **Answer:**
  - Any hit gives `answer = True`, `confidence = 1.0`, `run_check = True`, with every hit as `GateEvidence` (exact slice).
  - No hit gives `answer = False`, `confidence = None`, and `run_check = True`. The rules tier never decides a skip.
- **Tests:**
  - 3A gives no `sla` or `guarantee` hit and a `price` hit on "Base Rent".
  - 1A §2.C gives a `section_ref:8.3.1->…` hit.
  - `Section 2.C of 2A` is not a base reference.
  - A whole-word guard: "electronic" does not hit `electric*`.
  - Evidence slices are exact.

### Task 15: HaikuGate, JevGate, and the fail-open cascade. TDD.

**Files:** `src/og/gates/haiku.py`, `src/og/gates/jev.py`, `src/og/gates/cascade.py`. Tests: `tests/test_gates_haiku.py`, `tests/test_gates_cascade.py`.

- **`HaikuGate(client, model, samples=3, timeout_s=30)`** with `name = "haiku"`. It renders `gate_v1.md` plus the question definition plus the change order's segments, makes `samples` calls, and parses `{"answer"}`.
  - A sample is `None` on a refusal, `max_tokens`, invalid JSON, or an exception.
  - `answer` is the majority of the non-None samples (None if there are none). `confidence` = majority count / `samples`.
  - Tokens and cost are summed, and `error` holds the first error class name (never the repr).
- **`JevGate`** with `name = "jev"`. With `OG_JEV_ENABLED != "true"`, or with no `OG_JEV_URL`, every decision returns `answer None`, `error "unavailable"`, `run_check True`. No network code exists in this wave. It is documented as "protocol slot, not evaluated".
- **`run_cascade(questions, change_order, context, rules, classifier) -> list[GateDecision]`:**
  - A rules hit returns the rules decision. Otherwise it returns the classifier decision, with `run_check = not (answer is False and confidence == 1.0 and error is None and all samples are False)`.
  - A `classifier` of `None` gives `tier "none"`, `run_check True`.
- **Tests:** these cover the Review Focus 4 timeout, 2/3 "no" meaning the check runs, 3/3 "no" meaning a skip, refusal, an unavailable Jev, a sentinel key absent from decision fields, and a cascade that never calls the classifier on a rules hit.

### Task 16: Change check client (render, request, parse, cache)

**Files:** `src/og/change/client.py`. Tests: `tests/test_change_request.py`, `tests/test_change_parse.py`.

- **`Checker(client, model, effort, cache_dir="data/cache/change")`** exposes `check(chain: list[ChainDoc], category: str) -> CheckOutcome`.
- **Rendering:**
  - Each chain document gets a header `## <agreement_id> (<role>)`, then one line per segment, `[<agreement_id> <segment_id>] <text>`.
  - The system block, the chain block (base and prior amendments), and the change-order block each end with a `cache_control` breakpoint. The final user text names the category and pastes its question definition.
- **Request shape:** as in Global Constraints. It reuses the wave 2 schema-validation helpers' approach, field by field.
- **Cache:** the key is the sha256 of (prompt version, schema, model, effort, category, every chain TextDoc sha256). Only allowlisted fields are cached.
- **Tests:** these cover the request shape (breakpoint order, no forbidden parameters), status mapping for refusal, `max_tokens`, and invalid output, cache hits making no client call, and the sentinel key.

### Task 17: Change verify (deterministic). TDD heavy.

**Files:** `src/og/change/verify.py`. Tests: `tests/test_change_verify.py`, `tests/test_change_regressions.py`.

`verify_findings(chain, category, items) -> ChangeVerifyResult` applies these rules in order. Every drop reason is listed.

1. **The new side grounds:** `new_segment_id` is in the change order, and `new_quote` is an exact (whitespace-normalized) slice of that segment. Located like extraction evidence. Drop reasons: `unknown_segment`, `not_found_in_section`.
2. **The old side:**
   - `old_doc` must be None, `"self"`, or a chain agreement other than the change order (`old_doc_not_in_chain`).
   - If it is not None, `old_quote` must ground in `old_segment_id` of that document.
   - If it is None, `old_segment_id`, `old_quote`, and `old_value` must be null, and `target_label` is required.
   - A `target_label`, when present, must be a substring of `new_quote` (`target_label_not_in_quote`).
3. **Kind rules:**
   - **`supersedes`:** `new_quote` contains a supersession cue (closed list, whole word, case-insensitive): `replaced`, `deleted`, `amended and restated`, `supersede`, `supersedes`, `superseded`, `in lieu of`, `no further force or effect`, `deemed to refer to`, `deemed to be references to`, `deemed to mean and refer to`, `notwithstanding anything in the lease to the contrary`. Otherwise drop `no_supersession_cue`. Values must be null.
   - **`shifted_date`:** both values are ISO dates and differ. `new_value` is a date token (wave 2 `_find_dates`) in `new_quote`. `old_value` is a date token in `old_quote`; when `old_doc == "self"` it may come from `new_quote` instead. `old_doc` is required. `delta` is the whole number of days. Drops: `new_value_not_in_quote`, `old_value_not_in_quote`, `dates_equal`, `old_side_required`.
   - **`price_change`:** `new_value` is a money token (wave 2 `_money_candidates`) in `new_quote`. `old_value` is null (a price added) or a money token in `old_quote`. Currency is `USD` only when the quote has `$`. `delta` = new − old when both are present. Drops: `new_value_not_in_quote`, `old_value_not_in_quote`.
   - **`conflict`:** `old_doc` must be a chain agreement (not `"self"`, not None) with a grounded quote, and values must be null.
4. **Deduplicate** on (kind, new span, old span).

- **Tests:**
  - `test_change_regressions.py` uses the exact real 1A and 3A segment texts, for Review Focus 1 to 3.
  - `test_change_verify.py` has one test per rule and drop reason.
- **Stop rule (pre-registered):** the cue list stays closed. A phrasing that occurs in none of the 3 chain documents is a documented limitation, not a blocker.

### Task 18: Change writer and extraction invalidation

**Files:** `src/og/change/writer.py`, `src/og/store/writer.py` (modify `_delete_snapshot`). Tests: `tests/test_change_writer.py`, `tests/test_change_invalidation.py`.

- **`write_change_run(con, *, run, chain_runs, mode, findings, decisions) -> None`:** one transaction. It replaces any previous run with the same (change_order_id, mode).
  - It inserts ClauseRefs (grounded = 1 only for verify-produced spans), findings, and gate decisions.
  - For `ungated` only, it writes `supersedes` edges. An edge is written when a `supersedes` finding's new span overlaps exactly one visible obligation of the change order, and its old span overlaps exactly one visible obligation of the same type in the old document. The edge's clause ref is the finding's new ref. Zero or several candidates give no edge.
- **`_delete_snapshot`:** before deleting an agreement's clause refs, it deletes every change run whose change order or chain includes that agreement, with its findings, edges, decisions, and refs.
- **Tests:**
  - Review Focus 5.
  - A stale chain run is invisible.
  - A gated run writes no edges.
  - Base obligation lifecycle becomes `superseded` from an ungated edge.
  - An ambiguous overlap writes no edge.
  - Replacing a run is idempotent.

### Task 19: `python -m og.change` and `make change`. Runs after 14 to 18 merge.

**Files:** `src/og/change/__main__.py`, `src/og/change/report.py`, `Makefile`. Tests: `tests/test_change_cli.py`.

- **CLI:** `python -m og.change [--doc ID] [--mode ungated|gated|both] [--no-cache] [--log logs/change_runs.jsonl]`.
  - Each `amends` entry in sources.yaml is a change order. Its chain is the base, then the corpus amendments of the same base with an earlier `filing_date`.
  - Each chain document must have a current extraction run. If not, exit 2 with "run make extract first".
  - `both` runs ungated, then gated.
- **Each run:**
  - **Gates:** gated mode runs the cascade (rules + Haiku). Ungated mode records only the rules tier (which costs nothing) and runs all 6 checks.
  - **Checks and verify:** it runs the needed checks and verifies every outcome.
  - **Write or keep:** if every needed check came back ok, it writes the run. Otherwise it keeps the previous snapshot and exits 3.
  - **Log:** it appends an allowlisted run record to the JSONL log. The record holds the decisions, outcomes, drops, `cost_usd`, `incremental_cost_usd`, and `latency_ms`.
  - **Budget:** `OG_BUDGET_USD` is honored.
- **`report.load_change_report(con, change_order_id, mode) -> dict`:** a `ChangeReport` read only from the visible views. It holds the supersessions, shifted dates, price changes, and conflicts, each with ClauseRefs. `new_obligations` lists the change order's visible obligations that are not on the new side of a visible `supersedes` edge. Gate log summary. The MCP and UI in wave 4 call this.
- **Tests:**
  - A full fake run over a synthetic chain.
  - The gated run's checks come from the cache with no client calls (Review Focus 6).
  - A refused check means no write and exit 3.
  - A budget stop.
  - A missing extraction.
  - The sentinel key.
  - The report is built from the visible views only.

### Task 20: Change reference set loader and scorer

**Files:** `src/og/eval/change_gold.py`, `src/og/eval/change_score.py`, and an `og.eval` subcommand `change`. Tests: `tests/test_eval_change.py`.

- **Gold file** `eval/gold/change/<co>.yaml`:
  - Top-level fields: `change_order_id`, `chain`, `textdoc_sha256` per document, `provenance`, and `scope: full_agreement`.
  - `gates`: one entry per category, each `{answer: bool, segment_ids: [...]}`.
  - `findings`: each entry has kind, new_segment_id, new_span_text (exact), old_doc, old_segment_id, old_span_text, old_value, new_value, and target_label.
  - The loader validates every span exactly against the TextDoc.
- **Matching:**
  - A prediction matches a reference finding when the kind is the same, the new spans overlap, and the old sides agree: both None, both `"self"` with overlapping spans, or the same doc with overlapping spans.
  - Maximum-cardinality matching reuses the wave 2 matcher.
  - Value accuracy is reported separately.
- **Output** `eval/results/<date>-change.json`:
  - **Findings:** finding recall and precision per kind and overall, per mode.
  - **Gates, per backend:** recall, precision, and skipped-check rate for rules-only (no hit counts as "no"), haiku (majority), and cascade. Each is measured against the reference labels and against the ungated run, with the Clopper-Pearson 95% upper bound on the miss rate.
  - **Cost and latency:** cost (both bases) and latency, gated vs ungated.
  - **Skip safety:** `skips_confirmed_safe`, meaning a skipped category whose ungated check kept zero findings.
- **Tests:** these use synthetic gold, synthetic DBs, and run logs.

### Task 21: ADR-009 and the ADR-003 update

**Files:** `docs/decisions/ADR-009-change-order-diff.md`, `docs/decisions/ADR-003-fail-open-gates.md`.

- **ADR-009** covers:
  - Clause-level findings.
  - Old-side evidence from the chain, or `self`.
  - Out-of-corpus targets.
  - The pre-registered stop rule.
  - New obligations derived from extraction.
  - Graph edges from ungated runs only.
  - Gated reuse of cached checks.
  - Known limitations: 2A is missing, cue-list closure, a single sample per check.
- **ADR-003** gains a pre-registered skip rule section: unanimous 3/3, not tuned on the test set.

---

## Execution topology

Same as waves 1 and 2:
- Opus coordinates.
- Astra (gpt-6-astra) reviews the plan. **Pre-registered stop rule:** at most 3 rounds. From round 2 on, only issues reproducible on the 3 chain documents or a CLAUDE.md requirement count as blockers.
- Workers are Pi `zai/glm-5.3` on devbox worktrees under Orca, with Grok-4.7 as the fallback.
- Tests are frozen and red-verified. Review happens in an isolated checkout, then PRs are merged.

The tasks run in this order:
- **Wave 3A (parallel from B3):** Tasks 14, 15, 16, 17, 18, 20, 21.
- **Wave 3B:** Task 19, after 14 to 18 merge.

## Coordinator steps

- **C0 (needs key, before B3; about $0.01):**
  - Schema-acceptance probes with tiny inputs: `change_v1.schema.json` on Sonnet 5.5, and `gate_v1.schema.json` on Haiku 4.5.
  - If Haiku rejects structured output, the gate contract switches to a strict `yes`/`no` text parse before freezing. Unparseable output counts as a failed sample and fails open.
  - Record the result in `docs/reviews/test-changes.md`.
- **B3:** contract files, all wave 3 tests, `.env.example` (`OG_CHANGE_EFFORT`, `OG_GATE_SAMPLES`, `OG_GATE_TIMEOUT_S`, `OG_BUDGET_USD`, `OG_JEV_URL`), and the `make change` stub. Red is verified, and `tests/FROZEN.sha256` is regenerated.
- **C6 (reference set, parallel from B3):**
  - Astra drafts the 1A and 3A gold blind (the gate answers plus the expected findings).
  - The coordinator adjudicates and logs every change with a reason.
  - The user spot-checks the 12 gate answers in the labeler artifact (yes/no, about 2 minutes).
  - The labels are frozen before the first scored run.
- **C7 (needs key):**
  - Delete the v2 `graph.db`, then run `make extract` (cache, $0) and `make change` on the integration checkout.
  - Record real check and gate responses as fixtures under `tests/fixtures/api/change_v1/` and `gate_v1/`, with frozen replay tests.
- **C8:**
  - `python -m og.eval change` writes `eval/results/<date>-change.json`.
  - Write `docs/reviews/wave3-report.md`.
  - Check the demo criteria: at least one supersession, one shifted date or price change, and one gate skip that the ungated run confirms was safe. A criterion that is not met is reported as such and is not forced.

## Budget (API)

Spent through wave 2: about $3.38 of $5.00. The wave 3 cap is **$1.10** (cumulative stop at $4.50), set as `OG_BUDGET_USD=1.10` across C0 and C7.

| Step | Calls | Estimate |
|------|-------|---------:|
| C0 probes | 2 | $0.01 |
| Ungated checks: 2 change orders × 6 categories, chain about 50k tokens cached | 12 Sonnet | $0.45 |
| Gated checks | cache replay | $0.00 |
| Haiku gates: 2 × 6 questions × 3 samples, about 4k tokens each | 36 Haiku | $0.15 |
| **Total** | | **about $0.61** |

If the spend crosses $1.10, the run stops incomplete, and the coordinator reports to the user before anything else runs.

## Out of scope for wave 3

- **`guarantees` and `triggers` edges.** The corpus has no counterpart agreements: the Applied Digital guaranty's lease, the TeraWulf recognition agreement's lease, and 2A are not filed in it. These edges would be empty or invented. Revisit in wave 4 if a counterpart is added to the corpus.
- **Section-level gate units** (more gate labels per amendment). Revisit only if the budget allows.
- **The MCP server, the UI, aggregate `make eval`, and the README.** These are wave 4.
