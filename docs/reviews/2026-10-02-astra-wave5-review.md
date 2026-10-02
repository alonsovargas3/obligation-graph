# Wave 5 advisor review, round 1

Reviewed main `50476f3`, the wave-5 rev-1 plan, the sizing notes, CLAUDE.md, ADR-005/008/010, and the current verifier, writer, schema, readers and scorer. No API calls or source/test changes. Findings: **4 blockers, 7 should-fixes, 0 nits**.

## Executed corpus prototype

I opened `tests/fixtures/graph/real_v4.db` read-only and classified all 525 visible obligation quotes, one citation per obligation. Every quote was checked against its agreement's TextDoc slice. The fixture DB SHA256 is `32a6ab83724da574392905da2db5399acc540ef860eba9380fc520da0e4baa91`. Temporary executable: `/tmp/w5_proto.py`; detailed results: `/tmp/w5-results.json`; console results: `/tmp/w5-run.txt`. The SQL visibility probe used an in-memory backup, never the fixture DB.

**The plan does not yet specify a unique executable classifier.** Its trigger lexicons, rule precedence, trigger boundaries and new declaration grammar are deferred to B5. These are therefore results for the following explicit completion of its written construction list, not claimed acceptance counts for an unspecified future grammar:

- Recognize exactly the six construction families printed under `timing_grammar_v1.yaml`, allowing whitespace/NBSP and digit or common spelled-number forms, including parenthesized digits and business/calendar units. Use the first matching construction. An unmatched quote becomes `untimed`.
- Use the literal trigger-kind words, completion/expiration/termination variants, and quoted event names, with `other_event` as the fallback. A dated defined term must occur immediately after the construction, optionally after `the`; merely mentioning a dated event elsewhere in the quote does not bind it.
- Parse the three printed BLI row forms across whitespace, including adjacent segments, plus the existing verifier's closed event-declaration grammar. Restrict lookup to the same agreement or its recorded base. The existing declaration grammar does not recognize date-before-name parentheticals.
- Apply the plan's business-day veto when a recognized quote contains a numeric business-day offset. Use its zero-offset interpretation for a recognized date-bound construction without a number. Every emitted trigger is an exact original-text slice inside the original obligation quote. Trigger spans in this probe can be longer than a minimal event noun phrase; B5 must define their boundaries.

| Run | Scheduled | Contingent | Unresolved | Untimed | Total |
|---|---:|---:|---:|---:|---:|
| Written construction list, assumptions above | 2 | 107 | 25 | 391 | 525 |
| Sensitivity: also recognize bare `no later than`, the base Commencement BLI row, and the two amendments' date-before-name declarations | 6 | 111 | 24 | 384 | 525 |

The second run is explicitly an extension, not the written grammar. Neither run is a correctness score. In particular, both wrongly schedule 238 without the missing conditional-duty rule. An initial overly broad date lookup also scheduled 89 on 2011-01-01; I corrected that prototype defect by requiring immediate trigger-to-name binding before the counts above. This is concrete evidence for freezing the binding rule, not an allegation that the plan explicitly requires that defective implementation.

### Every scheduled result and all eight sizing candidates

The literal run schedules only 236 and 238. The sensitivity run adds 62, 65, 514 and 519; the table therefore hand-checks every scheduled result in either run.

| ID | Written-list result | Sensitivity result | Hand check of quote and date |
|---|---|---|---|
| 62 | unresolved | scheduled 2011-01-01 | `completed prior to the Commencement Date`: correct anchor, but strict **before** 2011-01-01, not due on that date. Preserve the commercially reasonable efforts qualification. |
| 65 | unresolved | scheduled 2011-01-01 | Same distinction for the Card Reader Installation. |
| 159 | unresolved | unresolved | `within ten (10) business days after the Effective Date`: anchor 2011-01-01 is supportable; no calendar-day due date. |
| 236 | scheduled 2014-04-01 | same | `satisfy the Commencement Date Conditions prior to the Target Commencement Date`: correct anchor, strict **before** 2014-04-01, qualified by commercially reasonable efforts. |
| 238 | scheduled 2014-05-31 | same | **Wrong scheduled result.** Failure of conditions by an extendable date creates a termination right. It is not a duty to terminate or perform by May 31. |
| 239 | unresolved | unresolved | Correct to withhold a date. The quote requires notice before the **earlier** of completion and ten business days after the Outside Completion Date. Business-day arithmetic alone would not resolve the unknown completion alternative. |
| 514 | unresolved | scheduled 2012-06-01 | Correct inclusive upper bound: complete the Suite 418A installations `on or before the 1A Expansion Date`. |
| 519 | untimed | scheduled 2020-06-30 | Correct inclusive upper bound: surrender `no later than the 3A Suite 409 Amended Surrender Date`. The defining sentence also contains commencement on 2018-07-01 and a former surrender date of 2018-06-30; neither is this anchor. |

Thus the eight sizing candidates do not mean eight computable deadlines. Five support dated performance bounds after adding the missing declaration forms: 62, 65, 236, 514 and 519. Three bounds are strict. 159 and 239 stay unresolved; 238 must not enter the scheduled list.

### Fifteen reproducibly random hand checks

Sample: `random.Random(20261002).sample(range(1, 526), 15)`, sorted below. Checks concern the stored quote, not a trigger inferred from neighboring prose.

| ID | Prototype kind | Manual assessment |
|---|---|---|
| 14 | contingent | Correct: pay rent `within fifteen (15) days after the receipt of a correct, itemized invoice`. |
| 96 | untimed | Correct for the quote: reasonably cooperate with Tenant's audit; no deadline construction. |
| 145 | contingent | Correct: `upon notice from Tenant` defend the proceeding. The minimal trigger should end before the duty text. |
| 165 | unresolved | Correct under the plan's business-day policy: deliver statements within ten business days after Landlord's written request. |
| 214 | untimed | Matches the explicit recurring-rent deferral: `$[***] per month for months 85-96`. It does contain temporal information, so the label needs the qualification in W5-6. |
| 274 | untimed | Correct for the quote: comply with Datacenter Rules and Regulations. |
| 279 | untimed | Miss: the quote contains a 120-hour cure period after receipt of an ECT Default Notice. Hours are outside the grammar, not absent timing. |
| 293 | untimed | Miss: cure `within the time allowed pursuant to Section 16.1.1`. This needs unresolved cross-reference timing, not an invented offset or a no-timing claim. |
| 325 | untimed | Correct for the quote: re-submit a Transfer Notice for consent, no stated deadline. |
| 362 | untimed | Correct for the extracted insurance-limits fragment, no stated deadline. |
| 380 | untimed | No performance deadline in the quote. `once the layout is determined` qualifies the allocation of later change costs; do not fabricate an installation date. |
| 416 | untimed | No performance deadline; a termination right has `immediate effect`. Calling this no *supported deadline* is defensible; calling it no *timing language* is not. |
| 461 | untimed | Correct for the quote: responsibility for replacement-parts costs, no stated deadline. |
| 489 | contingent | Kind is reasonable, but both Springing Events and demand qualify performance. Selecting only `demand` as the trigger kind must not erase the first condition. |
| 511 | untimed | No performance deadline; assignment requires consent. Do not turn a prerequisite into a dated duty. |

## Findings

### W5-1 [blocker] Strict and inclusive bounds collapse into the same asserted due date

**Location:** plan Review Focus 4, `Timing.direction`, schema v5 `effective_due`, Task 42; `src/og/query.py:upcoming_deadlines`.

**Problem and real counterexample:** 62 and 65 say `completed prior to the Commencement Date`, whose BLI date is 2011-01-01. The plan explicitly expects `due 2011-01-01`. 236 similarly says `prior to the Target Commencement Date`, dated 2014-04-01. Performing on the stated date does not satisfy a strict before bound. In contrast, 514 says `on or before` and 519 says `no later than`, both inclusive. A single `before` direction plus offset zero loses this distinction. Likewise, `within N days after` is an upper bound, while bare `after` can be a lower bound, not an exact day.

**Fix:** freeze a relation/inclusivity contract, for example `lt`, `lte`, `eq`, `gte`, `gt`, independent of signed offset. Expose a cited deadline bound with that relation in MCP/UI and eval. Either keep strict bounds out of the existing exact `effective_due` field, or explicitly redefine it as a boundary date accompanied by a mandatory relation and adapt filtering/presentation. Do not silently convert strict before to due-on or subtract a day without an explicit date-granularity policy. An offsetless `prior to` is useful timing information, but it does not state an exact performance date.

### W5-2 [blocker] Matching a date construction does not establish what is due relative to it

**Location:** Task 40 grammar and precedence; sizing-doc candidate list; Task 41 scheduled eligibility.

**Problem and real counterexample:** 238 says `If the Commencement Date Conditions have not occurred prior to the Outside Completion Date, subject to extension by virtue of Force Majeure, Tenant shall have the right to terminate this Lease, provided that:`. The literal prototype schedules it for 2014-05-31. That date qualifies a condition creating a right; it is not a termination deadline. 239 then requires notice `prior to the earlier to occur of: (1) completion ...; or (2) ten (10) business days after the Outside Completion Date`. Taking just the dated branch is wrong even with a holiday calendar. Separately, 89 requires indemnification/defense `upon demand` for hazardous materials present `as of the Effective Date`; the historical qualifier must never become its due date. All of these spans can be perfectly grounded while the inferred relationship is false.

**Fix:** freeze immediate construction-to-trigger binding, duty/condition qualification, and compound-alternative rejection before scheduling. Preserve the relevant conditional text in the citation. Explicitly reject scheduled results for 238 and 239, and bind 89 only to demand. Add a reason such as `conditional_or_compound` rather than forcing every unmatched relationship into a false date or `untimed`. Do not discard all conditional obligations: a condition may remain quoted while a separately stated duty has a valid contingent deadline.

### W5-3 [blocker] The proposed visibility predicates are weaker than the global invariant

**Location:** schema-v5 `visible_obligation_timing` and `effective_due`; Tasks 41/42; ADR-010 projection boundary.

**Problem and executed counterexample:** the projection description requires only a grounded trigger in the obligation's agreement. In an in-memory copy, I assigned obligation 62 the real citation for obligation 65, ClauseRef 123 at `[60160,60300)`. The described predicate retained it, although 62's quote is `[59002,59142)`. Same agreement does not establish containment or ownership. Pairing that timing row with real Carbonite event 5, whose cited date is 2014-02-01, also produces a foreign date if the new derivation merely joins the event and adds days. This is a probe of the abbreviated predicates, not existing v4 behavior: v4 correctly contains an agreement/base guard, which v5 must preserve explicitly.

**Fix:** freeze complete nonrecursive eligibility SQL: visible original obligation evidence, trigger containment in one of its own grounded citations, trigger agreement equality, and an anchor joined by id to grounded event evidence in exactly the obligation's agreement or its recorded base. Revoking either citation must remove the derived date and binding everywhere, including lifecycle and query output. Null triggers for truly untimed rows need a deliberate branch, not an inner join that drops them. Readers must use the new projection under the static allowlist. Test the real 62/65 mismatch, foreign event 5, revoked refs, and a valid base-agreement anchor.

### W5-4 [should-fix] Freeze the missing corpus constructions and the definition's evidence boundary

**Location:** `timing_grammar_v1.yaml`, `defined_dates`, Task 40, B5.

**Problem and real counterexamples:** the listed BLI forms omit `(b) Commencement Date`, needed for 62/65. The actual base label and date occupy adjacent segments p0429/p0430; Effective Date similarly occupies p0427/p0428. Carbonite uses NBSP in its labels. 514's anchor is declared as `As of June 1, 2012 (the “1A Expansion Date”)` in 1A p0027, outside the existing name-before-date verifier grammar. 519 needs bare `no later than`, absent from the construction list, and the `expiring June 30, 2020 (the “3A Suite 409 Amended Surrender Date”)` declaration in 3A p0011. 57 has `no later than thirty (30) days following receipt of an invoice`, whereas the list allows that prefix only with `after`. These omissions materially change the executed counts.

**Fix:** publish the exact lexicons, number-token rules, precedence and positive/negative corpus examples in B5 before dispatch. Define `DefinedDate` including its ISO value and exact evidence. Permit an explicitly paired label/value BLI span within the right section; do not scan forward from an arbitrary occurrence or cross-reference to the next date. Bound the amendment parentheticals to the correct date and term, including the two distractor dates in 3A p0011. Prefer the well-formed 1A p0027 declaration over the malformed parenthesis in p0014. Include negative TOC/cross-reference cases and ambiguous/conflicting definitions. Preserve original NBSP offsets instead of storing normalized text.

### W5-5 [should-fix] Remove or fully specify the weekday-only exception

**Location:** Global Constraints Business days, schema-v5 calendar-only derivation, Task 44.

**Problem and corpus evidence:** the only explicit Business Day definition found in the seven TextDocs is Mawson p0023: `“Business Day” means a day (other than Saturday, Sunday or public holiday) on which banking institutions in the State where the Data Center Facility is located are open generally for business.` Its p0037 also distinguishes calendar days from Business Days. I found no weekends-only definition supporting the exception, including in the CC/Carbonite leases. 159 and 239 therefore cannot acquire dates through that exception. Mawson 434 says `within three (3) Business Days ... once all outstanding fees have been paid in cleared funds`, which also lacks an observed trigger date. The exception requires a definition citation and a different arithmetic engine, neither represented by the proposed calendar-only SQL or Timing output.

**Fix:** cut the unused exception for this wave and keep business-day offsets quoted but unresolved, with their trigger still visible. If retaining it, add the definition evidence and explicit arithmetic policy to storage/read contracts and test them; do not silently execute calendar addition for `offset_unit=business`. Freeze whether an external-event business-day obligation is always `unresolved` or can be `contingent` with an uncomputable offset. The present global rule says unresolved; tests must not independently label 434 contingent just because the sizing heuristic did.

### W5-6 [should-fix] An unrecognized construction is not evidence of absent timing

**Location:** timing-kind meanings, fallback rules, Task 40 corpus tests, Task 42 copy.

**Problem and real counterexamples:** the literal run labels 279's `within one hundred twenty (120) hours after its receipt of an ECT Default Notice` untimed, and similarly 293's `within the time allowed pursuant to Section 16.1.1` and 434's interrupted `within three (3) Business Days ... once ... paid` construction. Applied Digital 490 contains `within [***] days after the occurrence thereof`; its offset is hidden, not absent. 504 says `On or prior to the date that is [***] after the date hereof`, which must not become a zero-day deadline. The explicit recurring-rent deferral, such as 214, also contradicts the table's definition of untimed as no timing language.

**Fix:** distinguish no supported timing from genuinely untimed, either with an unresolved/deferred reason or accurate category wording. Add conservative detection for unsupported units, cross-references, redacted offsets and recurring schedules without computing dates. Freeze `relative_to_other_obligation` and additional reasons on actual examples. Redaction must dominate any zero-offset fallback. A quote may justify an event but not an offset; preserve that distinction. Do not borrow the missing event from neighboring prose merely to improve recall.

### W5-7 [should-fix] Choose one authority for resolution and derived dates before implementing two anchor paths

**Location:** `classify`/`Timing` contracts, schema-v5 CHECKs, old `visible_obligation` anchored CTE, `og.query._hydrate`.

**Problem and real counterexamples:** `classify(doc, evidence)` has no base-document context, yet must decide scheduled versus unresolved using same-agreement or base dates. `Timing` contains only an event name, not its resolved identity/evidence. The table description requires a scheduled row to have a due date or an anchor, but lists no due-date column; a SQLite CHECK cannot query another table for that value. All 525 real rows currently have null legacy `due_date`, `anchor_event_id` and `offset_days`, so this corpus cannot exercise conflicts between the two derivations. Those conflicts remain possible under CLAUDE.md and ADR-008. For real 514, choosing a new dated event versus the existing undated event 15 is already an immediate resolution decision. The current query hydrator also suppresses base-agreement anchor bindings even though the old SQL permits them.

**Fix:** freeze a two-stage contract: pure quote parsing followed by explicitly supplied, cited same/base anchor resolution, or pass the required immutable context into classify. Let one function own final kind, relation and due derivation. Specify precedence/conflict behavior for legacy absolute dates and offset/anchor pairs; never fall back to a disputed date. Make the CHECK executable and require a genuinely dated eligible anchor for derived schedules. Use the same relation and agreement policy in SQL, MCP/UI and eval, including base-anchor citations. Synthetic compatibility tests are appropriate for the legacy cases absent from the corpus.

### W5-8 [should-fix] Name deduplication needs agreement, date and citation rules

**Location:** plan Events from defined-date rows, `writer._write_events`, `_resolve_anchor`.

**Problem and real counterexamples:** Carbonite event 7 already names `Effective Date` with a null date, while the BLI parser finds 2013-12-31. Events 15 and 16 are the undated amendment anchors needed by 514/519. Mawson already has two `Effective Date` events, 11 and 13. CC and Carbonite also both use `Effective Date` for different dates. “Distinct ... deduplicated by name” leaves it unclear whether the new date loses to the null model value, duplicates make lookup ambiguous, or a merge keeps a citation that does not substantiate the merged date.

**Fix:** deduplicate within agreement and a defined name normalization only. A retained dated event must cite the full accepted date declaration; never attach a new date to the old name-only evidence. Specify how equal dated candidates collapse and how conflicting dates cause unresolved resolution. An ambiguous local definition must not silently fall back to a similarly named base event. Keep agreement-local evidence and provenance when combining deterministic and model candidates.

### W5-9 [blocker] The planned labels cannot support scheduled-date accuracy

**Location:** Task 43, C14, `src/og/eval/gold.py`, `src/og/eval/score.py`.

**Problem and executed evidence:** all 50 existing reference obligations have `due_date: null`. C14 adds only `timing_kind` and `trigger_span_text`, yet Task 43 promises scheduled-date accuracy. The reference includes both 62 and 65, so their newly computed bounds would either be scored against null, receive no denominator, or be judged against dates produced by the classifier itself. None measures correctness. Existing `pred_from_db` reads `due_date`, not `effective_due`. In addition, gold and prediction quotes can differ in scope: the reference's rent clause includes first-month exceptions, while real 68 is just the recurring monthly-installment sentence. Timing cannot be inferred from a portion of the gold quote missing from the prediction.

**Fix:** freeze independent timing labels containing expected date/boundary, relation, anchor identity/evidence, offset/unit, trigger offsets and unresolved reason where applicable. Keep explicit and derived-date metrics separate so old extraction gold remains meaningful. Score only within the established matched-obligation unit, report matched/labeled denominators and missing predictions, and specify trigger span matching rather than leaving “trigger match” undefined. Add a small independently adjudicated cross-document challenge set for all eight sizing candidates and negative 89/238/239/490/504 cases. The 50-item base-only reference cannot validate the amendment declaration forms or Carbonite's conditional dates. Label all results as model-drafted/adjudicated/spot-checked, with sampled coverage.

### W5-10 [should-fix] Timing citations and base dependencies need explicit snapshot ownership

**Location:** Task 41, `_check_preconditions`, `_delete_snapshot`, `delete_change_runs`, `visible_obligation_clause`, `pred_from_db`.

**Problem and real counterexample:** 128 begins `Prior to occupying the Tenant Space, and prior to the expiration of each such policy, Tenant shall submit ...`. If a new short trigger ClauseRef is attached through `clause_ref.obligation_id`, it becomes a second extraction quote. `pred_from_db` selects the first citation ordered by start then end, so a shorter same-start trigger can replace the original obligation evidence and reduce its IoU with gold. Executed in an in-memory copy: the 35-character `Prior to occupying the Tenant Space` citation becomes the first citation instead of the 223-character original, with only 0.157 IoU against that original. New timing rows also reference obligations, refs and events that the existing snapshot deletion removes; the current dependent check only searches legacy `obligation.anchor_event_id`, not the new timing anchors. Omitting these dependencies creates either FK failures or incomplete cleanup/rebuild behavior.

**Fix:** give timing evidence a distinct ownership path, leaving `visible_obligation_clause` as the original extraction evidence. Validate new spans before any snapshot mutation. Delete timing children before their refs/obligations/events, and extend base dependency detection and the full-chain rebuild policy to timing anchors. Keep all of this inside the existing snapshot transaction; a classifier/resolution exception must roll back rather than silently omit a timing row or mark it untimed. Freeze re-extraction, rollback and unchanged extraction-IoU tests using real 128 and a cited base-anchor case.

### W5-11 [should-fix] B5 must own compatibility edits that the worker file lists omit

**Location:** B5, Tasks 41/42/43 and execution topology.

**Problem and concrete repository evidence:** `src/og/store/db.py` still sets `SCHEMA_VERSION = 4`, and `tests/test_schema_v2.py` explicitly asserts version 4. Existing reader fixtures are `real_v4.db`; fresh schema-v5 readers cannot simply open them under the current version contract. The static reader allowlist also lacks `visible_obligation_timing`. Task 43 starts in parallel with Task 40, before Task 42 can change `og.query`; an eval reader naming the new projection needs the allowlist and SQL column contract at B5. The statement that wave-4 tests remain unchanged is not literally compatible with a schema bump and the new scheduled results for 62/65/236/514/519.

**Fix:** enumerate coordinator-owned B5 changes to schema/version constants, public output types, read allowlist, frozen compatibility assertions and the new or rebuilt corpus fixture. Freeze the final view columns before Tasks 40/43 run. Preserve the historical v4 artifact if useful, but make each test's expected version explicit. Record intentional test changes, including revised deadline totals, then regenerate the freeze manifest. Specify that contingent is a paged subset of pending, with consistent filters/totals and no double-counted UI rows. Keep the strict offline fresh-clone replay and README semantic comparison as acceptance checks.

## Deterministic scope and budget

A deterministic worker, including a `/bin/zsh`-launched worker implementing Python, is sufficient for the five supportable dated bounds above once the rules and evidence contracts are explicit. Shell choice supplies no semantic guarantee; the frozen corpus tests and independent labels do. No new model call is needed to decide these eight candidates, parse their quoted dates, or retain the conservative business-day policy.

The current grammar does not yet justify a claim of broad contingent-deadline recall: the 15-item sample and real 57/434/490 already expose missing constructions. Fix and measure that first. Do not pre-spend or require a model pass for Phase 1. If independent evaluation later shows unusable coverage, a separately approved model pass could propose source spans, still subject to these same deterministic grounding and relation rules. It must not supply guessed trigger occurrence dates or holiday arithmetic.

## Verdict

proceed-after-fixes
