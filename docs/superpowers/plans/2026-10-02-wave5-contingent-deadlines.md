# Wave 5: Contingent and Scheduled Deadlines Implementation Plan (rev 1)

> **For agentic workers:** you are a supervised Orca worker. Do only your Task. Tests under `tests/` are frozen (pinned by `tests/FROZEN.sha256`), and so are the coordinator-authored contract files listed under "Contract files". You write implementation code only. Use `ask` for any ambiguity. Send `worker_done` once. You never hold or read an API key, and nothing in your Task calls the network.

**Goal:** Issue #26 Phase 1 (reshaped) plus its eval (Phase 3). Each visible obligation gets a cited timing classification, and the dates the contracts state become computable deadlines:

| Timing | Meaning |
|---|---|
| `scheduled` | A computable due date. |
| `contingent` | Due relative to a named outside event, which is quoted. |
| `unresolved` | A deadline construction whose anchor has no bindable date. |
| `untimed` | No timing language. |

As a result, "what do we owe the landlord in the next 90 days" answers with scheduled rows plus contingent rows that name their trigger.

**Architecture:**

```
TextDoc + verified obligations ──og.timing (deterministic, no model)──▶ Timing per obligation
   ├── trigger span: an exact slice of the obligation's own grounded quote
   ├── offset (days) + unit (calendar | business)
   └── anchor: a defined event with a cited date (Basic Lease Information rows, declaration grammar)
writer ──▶ obligation_timing rows (schema v5) ──▶ visible_obligation_timing projection ──▶ og.query / MCP / UI / eval
```

- **No new model calls.** Timing is derived deterministically from the already-grounded obligation quotes and the TextDoc. Re-extraction replays from `eval/recorded/` at $0. Expected API spend: $0. The cap stays at $1.30, and is spent only if B5 or C17 shows the deterministic recall is unusable; that would be a user decision.
- **No inferred dates.** A due date exists only when the trigger is a defined event whose date is quoted from the contract and the offset is quoted in the obligation. Otherwise there is no due date.
- **Lifecycle values stay** `scheduled | pending | superseded`. `timing.kind` subdivides `pending` into `contingent`, `unresolved`, and `untimed`, so the wave 4 contracts and tests keep their meaning.

**Spec:** issue #26 and its Phase 0 sizing (`docs/research/2026-10-02-due-date-sizing.md`), CLAUDE.md (Data model: anchor events, derived lifecycle), and ADR-005, ADR-008, ADR-010.

## Global Constraints

- **The invariant:**
  - Every `trigger` and `anchor` in a Timing carries a ClauseRef whose `span_text == text[char_start:char_end]`.
  - The trigger span lies inside the obligation's own grounded quote.
  - The anchor date comes from a grounded event declaration in the same agreement or its chain base, which is the existing `visible_obligation` anchoring rule.
- **Business days:**
  - An offset counted in business days is `unresolved` with reason `business_days`. A holiday calendar would be an inferred term.
  - Exception: if the agreement defines "Business Day" in a cited sentence that excludes only weekends, weekends-only arithmetic is allowed. Otherwise the obligation stays unresolved.
- **Closed grammars, pre-registered stop rule:**
  - The trigger grammar and the defined-date row grammar are closed lists, frozen in B5 from the real corpus sentences.
  - Phrasings that occur in none of the 7 filings are documented limitations.
  - Astra review is limited to 3 rounds. From round 2 on, only corpus-reproducible issues or missed requirements count as blockers.
- **Rebuild, not migrate:** schema v5, with `user_version = 5`. The graph is rebuilt by replay at $0.
- **Unchanged from wave 4:** tests, secrets, and tooling. No em dashes in user-facing copy.

## Review Focus

1. **Recurring rent stays untimed.** "$51,123.99 per month for months 61 to 72 of the Term" names no trigger. It stays `untimed`; recurring schedules are deferred Phase 2.
2. **The invoice trigger.**
   - Quote: "within thirty (30) days after Tenant's receipt of an invoice therefor".
   - Expected: `contingent`, `trigger_kind=invoice`, offset 30 calendar days, with the trigger span quoted.
   - No due date.
3. **A business-day deadline.**
   - Obligation 159: "within ten (10) business days after the Effective Date". The Effective Date is January 1, 2011, from a Basic Lease Information row.
   - Expected: `unresolved`, reason `business_days`, unless the lease defines Business Day as weekdays.
4. **A defined date bound, with no offset.**
   - Obligation 62/65: "prior to the Commencement Date". The Commencement Date is January 1, 2011, cited from the Basic Lease Information row.
   - Expected: `scheduled`, due 2011-01-01, with the anchor cited.
5. **An event-driven anchor.**
   - Carbonite "Commencement Date shall mean the earlier of ..." has no date.
   - Expected for its obligations: `unresolved` (reason `anchor_without_date`), never scheduled.

---

## Contract files (coordinator-authored in B5, frozen)

### `src/og/timing.py` (signatures only; bodies are Task 40)

```python
TIMING_KINDS = ("scheduled", "contingent", "unresolved", "untimed")
TRIGGER_KINDS = ("invoice", "notice", "demand", "default", "completion", "term_end",
                 "defined_event", "other_event")
UNRESOLVED_REASONS = ("business_days", "anchor_without_date", "anchor_not_found",
                      "relative_to_other_obligation")

@dataclass(frozen=True)
class TimingSpan:
    char_start: int; char_end: int; span_text: str      # exact TextDoc slice inside the obligation quote

@dataclass(frozen=True)
class Timing:
    kind: str; trigger_kind: str | None; trigger: TimingSpan | None
    offset_days: int | None; offset_unit: str | None   # "calendar" | "business"
    direction: str | None                               # "after" | "before" | "on"
    anchor_event: str | None                            # defined term name when the trigger is a defined event
    reason: str | None                                  # UNRESOLVED_REASONS for unresolved

def classify(doc: TextDoc, evidence: Evidence) -> Timing                  # pure, deterministic
def defined_dates(doc: TextDoc) -> list[DefinedDate]                     # BLI rows + declaration grammar
```

### `prompts/timing_grammar_v1.yaml`

The frozen lexicons for:
- trigger phrases per kind;
- offset constructions (`within N days after/following/of`, `no later than N days after`, `N days prior to`, `prior to`, `on or before`, `upon`);
- the Basic Lease Information row forms, quoted from the corpus:
  - `(a) Effective Date: January 1, 2011`
  - `(b) Target Commencement Date: April 1, 2014.`
  - `(e) Outside Completion Date: May 31, 2014.`

### Schema v5

- **`obligation_timing` table:** `(obligation_id PK, kind, trigger_kind, trigger_clause_ref_id NULL, offset_days, offset_unit, direction, anchor_event_id NULL, reason)`. CHECKs:
  - `kind` is one of `TIMING_KINDS`;
  - `contingent` requires a trigger ref;
  - `scheduled` requires a due date or an anchor event;
  - `unresolved` requires a reason.
- **`visible_obligation_timing` projection:** the timing row with its trigger ClauseRef, which must be grounded and in the same agreement as the obligation. Rows with an ungrounded trigger are invisible.
- **`visible_obligation`:** `effective_due` also derives from `obligation_timing` for scheduled rows. The date is the anchor event's cited date plus the signed offset, in calendar days only.
- **Events from defined-date rows:** the writer creates `event` rows from `og.timing.defined_dates`, each with its own grounded ClauseRef. These rows are distinct from the model-extracted events, and the two are deduplicated by name.

### `og.query` additions

`ObligationOut.timing`:
```
{kind, trigger_kind, trigger: ClauseRefOut | None, offset_days, offset_unit, direction,
 anchor: {name, date, clause} | None, reason}
```

`upcoming_deadlines` gains:
- `contingent` (paged), where each row names its cited trigger;
- `contingent_total`;
- `unresolved_total`;
- `untimed_total`.

`PENDING_NOTE` is extended to explain the three pending kinds.

---

## Tasks (workers)

### Task 40: `og.timing` (deterministic classifier). TDD heavy.

**Files:** `src/og/timing.py` (bodies).

**Tests:** `tests/test_timing.py` (synthetic, one test per grammar rule and reason) and `tests/test_timing_corpus.py`.

The corpus test pins the real sentences, using the Review Focus cases, obligation ids 62, 65, 159, 236, 238, 239, 514, and 519, and the sizing doc's spot-checked contingent examples.

### Task 41: Writer, schema v5, defined-date events

**Files:**
- `src/og/store/writer.py`: timing rows and defined-date events, inside the snapshot transaction.
- `src/og/extract/__main__.py`, if wiring is needed.

**Tests:** `tests/test_timing_writer.py` and `tests/test_schema_v5.py`. They cover:
- visibility;
- re-extraction replacement;
- an ungrounded trigger that is invisible;
- a scheduled row's `effective_due`.

### Task 42: Query, MCP and UI surfaces

**Files:**
- `src/og/query.py`: bodies for the new fields.
- `src/og/mcp/server.py`: tool descriptions mention timing kinds.
- `ui/index.html`: a timing column and chip, the trigger quote in the clause panel, and contingent rows in the pending note.

**Tests:** `tests/test_query_timing.py`, plus page static checks for the new element ids. The coordinator runs a C-step Chrome check.

### Task 43: Eval for timing

**Files:**
- `src/og/eval/gold.py`: optional `timing_kind` and `trigger_span_text` fields.
- `src/og/eval/score.py`: timing-kind accuracy, trigger match, and scheduled-date accuracy, each with coverage.
- `src/og/eval/all.py` and `src/og/eval/readme.py`: a timing table.

**Tests:** `tests/test_eval_timing.py`.

### Task 44: ADR-011

**File:** `docs/decisions/ADR-011-contingent-deadlines.md`. It covers:
- deterministic timing over cited quotes;
- why business days stay unresolved;
- `untimed` vs `contingent` vs `unresolved`;
- the deferred recurring schedules.

## Coordinator steps

- **B5:** contract files, schema v5, the grammar yaml, frozen tests (red verified), and freeze regeneration.
- **C14, reference labels:**
  - Astra drafts `timing_kind` and `trigger_span_text` blind, for the 50 reference obligations on the CC 2011 lease.
  - The coordinator adjudicates.
  - The user spot-checks 10.
  - The labels are frozen before the first scored run.
- **C15:** rebuild the graph by replay ($0). Run `make eval`. Regenerate the README tables, then update the known-limitations and demo text.
- **C16:** Chrome check of the UI timing column, plus re-running the fresh-clone check (C10).
- **C17:** a Claude Desktop re-check of "What do we owe the landlord at 55 Middlesex Turnpike?" (user step).

## Execution topology

- Same roles as before.
- **Wave 5A**, in parallel from B5: Tasks 40, 43, and 44.
- **Wave 5B:** Task 41 after Task 40, then Task 42 after Task 41.

## Budget

Expected $0, since everything is replayed. Cap $1.30, used only on a user decision. Current spend is about $4.23 of $11.78.

## Out of scope

- Recurring schedules (Phase 2).
- Holiday calendars.
- Recording episodes (the "Where this goes" direction).

---

## Rev 2 (Astra wave-5 round 1: 4 blockers, 7 should-fixes, all accepted)

Rev 2 overrides rev 1 wherever they conflict. Review: `docs/reviews/2026-10-02-astra-wave5-review.md`.

The executed prototype found that 5 obligations support a real dated bound: 62, 65, 236, 514, and 519. Of the other sizing candidates, 159 and 239 stay unresolved, and 238 must never be scheduled.

### W5-1. Relation, not just a date

`Timing` carries `relation`, one of `lt | lte | eq | gte | gt`, plus a cited `bound_date`. The phrase mappings are:

| Phrase | Relation |
|---|---|
| `prior to`, `before` | `lt` |
| `on or before`, `no later than`, `within N days after` | `lte` (bound = anchor + N) |
| `on` | `eq` |
| `after`, `following` with no "within" | `gt` |

- **`effective_due` keeps its exact meaning.** It is the `lte` or `eq` bound only.
- **A strict `lt` bound** is exposed as `deadline: {relation: "lt", date, clause}` and is never shown as a due-on date. `upcoming_deadlines` includes `lt` rows in the window, with their relation shown.
- **Arithmetic:** there is no subtract-a-day conversion. Dates are calendar dates with day granularity, and the relation is stated with them.

### W5-2. Duty versus condition, and compound alternatives

A construction binds a deadline only when it governs the duty clause:
- **Conditions do not bind.** A `prior to` inside an `If ... have not occurred prior to ...` condition does not bind; it gets reason `conditional_or_compound` (238).
- **Compound alternatives do not bind.** `the earlier/later to occur of` gets reason `conditional_or_compound` (239).
- **The trigger is the immediate one.** It is the phrase directly after the construction (89 binds to `upon demand`, never to the historical `as of the Effective Date`).

Conditions stay quoted. A conditional obligation can still have a valid contingent deadline on its stated duty.

### W5-3. Complete eligibility SQL

`visible_obligation_timing` requires all of the following:
1. The obligation is in `visible_obligation`.
2. The trigger ref is grounded, in the same agreement, and **contained within one of the obligation's own grounded extraction citations** (char range containment).
3. The anchor event, if any, is joined by id to `visible_event_binding`, in exactly the obligation's agreement or its recorded base.

Rows with no trigger use an explicit LEFT branch. Derived dates come only from this view. Revoking either citation removes the date everywhere.

**Frozen tests:**
- the real 62/65 swapped citation (ref 123), which must be rejected;
- the foreign Carbonite event 5, which must be rejected;
- revoked refs;
- a valid base-agreement anchor.

### W5-4. The grammar, published in B5

`timing_grammar_v1.yaml` freezes:
- exact lexicons, number tokens (digits, spelled numbers, parenthesized digits), precedence, and NBSP handling;
- the BLI label and value pairs across adjacent segments within the Basic Lease Information section: `(a) Effective Date` / `(b) Commencement Date` (p0427/p0428, p0429/p0430) and the Carbonite NBSP forms;
- date-before-name parentheticals: 1A p0027 `As of June 1, 2012 (the “1A Expansion Date”)`, preferred over the malformed p0014, and 3A p0011 `expiring June 30, 2020 (the “3A Suite 409 Amended Surrender Date”)`, bound to its own date and not the distractors;
- `no later than` without "after", and `following`.

The freeze also includes negative TOC and cross-reference cases. Original offsets are preserved.

### W5-5. No business-day exception

The weekday-only exception is cut. The only definition in the corpus (Mawson p0023) excludes public holidays.

A business-day offset is `unresolved` (`business_days`), with its trigger still quoted and visible. An external-event business-day obligation is also `unresolved` (434), never `contingent`.

### W5-6. "Untimed" means no timing language at all

These reasons are added for `unresolved`:

| Reason | Example |
|---|---|
| `unsupported_unit` | hours, as in 279 |
| `cross_reference` | `within the time allowed pursuant to Section 16.1.1`, as in 293 |
| `redacted_offset` | `within [***] days`, as in 490 and 504. A redaction always wins over a zero-offset fallback. |
| `recurring_schedule` | `per month for months 85 to 96`, as in 214 |

Wave 5 keeps `untimed` only for quotes with no timing construction. Copy in the UI, MCP, and README says "no stated deadline".

### W5-7. One authority

The contract has two stages:
1. **`parse(doc, evidence) -> ParsedTiming`:** pure quote parsing, with relation, offset, unit, trigger span, reason, and anchor name.
2. **`resolve(parsed, anchors: list[CitedAnchor]) -> Timing`:** given the cited dated anchors of the obligation's own agreement and its base. It owns the final kind, relation, and bound.

Rules for the result:
- **Legacy fields win.** Where a legacy explicit `due_date` or anchor/offset exists, it wins. A conflict gives `unresolved` (`conflicting_dates`). No disputed date is ever used.
- **CHECK constraints** require `bound_date IS NOT NULL` for `scheduled`, and a reason for `unresolved`.
- **Same rules everywhere.** SQL, MCP/UI, and eval share the relation and agreement policy, including base-anchor citations.

### W5-8. Event deduplication

Events are deduplicated within one agreement, by normalized name, and a retained dated event cites its full accepted declaration. Specifically:
- A dated deterministic candidate replaces an undated model event of the same name. Carbonite event 7 then gets 2013-12-31 with the BLI citation; the old name-only evidence is never reused for the new date.
- Equal dates collapse into one event.
- Conflicting dates leave the event dateless, with reason `conflicting_dates`.
- There is no fallback to a base event when the local name is ambiguous.

### W5-9. Independent timing labels and a challenge set

**C14 labels**, for each of the 50 reference obligations plus a cross-document challenge set:
- `timing_kind`, `relation`, `bound_date`, and the anchor name and evidence;
- `offset_days`, `offset_unit`, the trigger span, and `reason`.

**The challenge set:** 62, 65, 159, 236, 238, 239, 514, and 519, plus the negatives 89, 490, and 504, plus 57, 279, 293, and 434.

**Scoring:**
- Scoring happens only within matched obligations, and reports matched and labeled denominators.
- A trigger span matches with IoU of at least 0.5 against the labeled span inside the same quote.
- Bound-date accuracy is scored separately from the legacy `due_date`.
- **Labels are model-drafted** (Astra, blind), **coordinator-adjudicated**, and **user spot-checked** (10). Coverage is sampled.

### W5-10. Timing evidence ownership

Timing ClauseRefs are owned by `obligation_timing`, through a new `timing_clause_ref` link. They are not attached through `clause_ref.obligation_id`, so `visible_obligation_clause` and `pred_from_db` keep the original extraction evidence. The real 128 IoU must be unchanged.

In `_delete_snapshot`, timing rows and refs are deleted first, and dependency detection includes timing anchors.

Writes happen inside the snapshot transaction. A classifier exception rolls back the write and never omits or downgrades the row.

### W5-11. B5 owns compatibility

**B5 changes:**
- `SCHEMA_VERSION = 5`;
- the version assertions;
- `READ_ALLOWLIST` gains `visible_obligation_timing`;
- `ObligationOut.timing` and the `DeadlinesOut` fields;
- a rebuilt `tests/fixtures/graph/real_v5.db`, keeping `real_v4.db` for historical tests;
- the revised deadline totals, recorded in `test-changes.md`.

**Query and UI rules:**
- `contingent` is a paged subset of pending, with consistent filters and totals and no double counting.
- Final view columns are frozen before Tasks 40 and 43 run.

### Budget

The budget is unchanged: $0 expected. A model pass, if ever, is a separate user decision, and it would still be subject to these deterministic rules.

## Rev 2.1 (Astra wave-5 round 2: 1 blocker, accepted)

### R2-1. Acyclic views

Executed on the real graph, the literal rev 2 shape (timing view joins `visible_obligation`, and `visible_obligation` reads timing) fails with "view ... is circularly defined". B5 freezes this dependency order:

1. **`grounded_obligation`** (internal helper, not on the reader allowlist): obligations that have at least one grounded ClauseRef in their own agreement. This is the existing visibility predicate, factored out.
2. **`visible_obligation_timing`:** reads `grounded_obligation`, `obligation_timing`, the timing trigger refs (contained in one of the owner's grounded extraction citations, same agreement), and `visible_event_binding`, which allows the same agreement or its recorded base. It never reads `visible_obligation`.
3. **`visible_obligation`:** reads `grounded_obligation` and `visible_obligation_timing`.

A frozen real-graph test asserts that both views are queryable and return 525 rows. The revoked-ref, swapped-ref (62/65, ref 123), and foreign-anchor (Carbonite event 5) tests remain.

### Strict bounds in lifecycle and windows

**Lifecycle:** `lifecycle = 'scheduled'` whenever timing is `scheduled`, for any relation.

**Dates:**
- `effective_due` is set only for `lte` and `eq` bounds.
- Every scheduled row also exposes `deadline: {relation, date, clause}`.

**Windows:** `upcoming_deadlines` selects scheduled rows by `deadline.date` in `[as_of, as_of + days]`, whatever the relation. It shows the relation, so strict bounds (62, 65, 236) are neither omitted nor double counted.

**Pending:** `pending` now means not scheduled and not superseded. `contingent` is a paged subset of it.

### Month-granularity timing (round 2 recall miss, 443)

Event-relative month constructions, such as "in the month that Host receives ...", are `unresolved` with reason `month_granularity`. The trigger stays quoted, and no day is invented. B5 adds this case to the grammar and to the corpus tests.

### Classification counts are not acceptance

The round 2 counts (scheduled 5, contingent 132, unresolved 148, untimed 240) come from a disposable prototype. Acceptance is the frozen corpus tests on the 5 scheduled rows and the challenge set, plus the C14 independent labels.
