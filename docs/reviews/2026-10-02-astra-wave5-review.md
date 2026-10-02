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

## Round 2

Reviewed rev 2 at `4e6a3cd`. Only this review file was changed; all prototype writes and SQLite mutations were outside the repository or in memory. No API calls.

### A) Disposition of round-1 findings

- **W5-1: resolved.** Strict and inclusive relations are distinct; strict bounds retain their dates without becoming due-on dates.
- **W5-2: resolved.** Rev 2 rejects conditional/compound deadlines and requires immediate trigger binding; the real challenge cases pass the refreshed prototype.
- **W5-3: partially resolved.** Containment, agreement/base scope and citation revocation are now explicit, but the specified view dependencies form a cycle. See R2-1 below.
- **W5-4: resolved.** The added BLI pairs, amendment parentheticals and bare `no later than` support the five intended dated bounds. Exact lexicons remain a B5 deliverable.
- **W5-5: resolved.** The weekday-only exception is removed; external-event business-day obligations also stay unresolved.
- **W5-6: resolved.** Unsupported units, cross-references, redacted offsets and recurring schedules receive explicit unresolved reasons rather than being defined as absent timing.
- **W5-7: resolved.** Parsing and cited resolution are separate; conflicts with legacy dates stay unresolved, and scheduled rows require a bound. B5 still needs the concrete types and lifecycle/filter implementation.
- **W5-8: resolved.** Deduplication is agreement-local, dates retain their full declaration evidence, conflicting dates stay dateless, and local ambiguity does not fall back to a base event.
- **W5-9: resolved.** Independent bound/relation/anchor labels and the cross-document challenge set now support a separate derived-bound metric with disclosed denominators.
- **W5-10: resolved.** Timing citations have separate ownership; snapshot cleanup, dependency detection and rollback are explicitly extended.
- **W5-11: resolved.** B5 owns versions, fixtures, output contracts, the read allowlist and intentional changes to frozen assertions before parallel workers start.

Disposition total: **10 resolved, 1 partially resolved, 0 unresolved**, assessed as plan commitments rather than completed production implementations.

### B) Executed rev-2 corpus prototype

Executable: `/tmp/w5_r2.py`. Results: `/tmp/w5-r2-results.json` and `/tmp/w5-r2-run.txt`. It reads the same pinned `real_v4.db` and seven TextDocs as round 1. All 525 original evidence slices and all emitted spans were checked against the original text, with NBSP preserved.

The refresh implements the written relation mapping, immediate defined-name binding, conditional/compound rejection, new unresolved reasons, adjacent same-section BLI pairs, the two specified date-before-name forms, and no business-day exception. No rule dispatches on obligation id. Explicit assertions check the complete set of scheduled ids, their relations/dates, and all five challenge negatives.

The grammar YAML is still deferred to B5, so **aggregate counts are for this documented implementation of the prose, not uniquely implied frozen-test counts**. Necessary choices where rev 2 does not give a closed lexicon:

- Longer constructions precede their suffixes; the first remaining recognized construction is selected. `on` requires an immediately following defined event, preventing incidental uses from becoming deadlines. `upon` without an offset is treated as an event-relative `eq`; `within ... following/of` uses the same inclusive upper-bound rule as `within ... after`.
- Reason precedence is redacted offset, conditional/compound, recurring schedule, unsupported unit, cross-reference, business days, then missing anchor. This gives 239 `conditional_or_compound` rather than `business_days`.
- Recurring detection includes `per month`, monthly installments, first-day-of-each/every-month phrases and immediately following month. Hours/minutes are unsupported units. An otherwise unmatched quote containing a timing cue such as `within`, `promptly`, `once`, `until`, `during` or `throughout` is conservatively unresolved with `anchor_not_found`.
- BLI labels and values must be adjacent segments in the same date-information section. Parentheticals must match the stated `As of DATE (the NAME)` or `expiring DATE (the NAME)` form. The existing closed declaration verifier is also reused. There is no forward search from a cross-reference to an unrelated date.
- Unresolved cases retain the full exact source quote as context in this probe. Other contingent spans can also be broader than their event noun phrase. These are not proposed gold trigger-span labels; B5 and C14 must freeze minimal-span boundaries and retain offsets/units when independently supported.

| Timing kind | Count |
|---|---:|
| scheduled | 5 |
| contingent | 132 |
| unresolved | 148 |
| untimed | 240 |
| **Total** | **525** |

| Unresolved reason | Count |
|---|---:|
| anchor_not_found | 65 |
| recurring_schedule | 39 |
| business_days | 25 |
| anchor_without_date | 6 |
| unsupported_unit | 5 |
| redacted_offset | 4 |
| cross_reference | 2 |
| conditional_or_compound | 2 |
| conflicting_dates | 0 |
| relative_to_other_obligation | 0 |
| **Total** | **148** |

These are classification counts, not measured accuracy. In particular, the random inspection below found an implementation recall miss. No business-day or redacted offset produced a date.

#### All scheduled results, hand checked

| Obligation | Exact timing phrase | Relation | Bound | Cited anchor evidence |
|---|---|---|---|---|
| 62 | `prior to the Commencement Date` | lt | 2011-01-01 | Base p0429/p0430, label plus date at `[44806,44844)`. |
| 65 | `prior to the Commencement Date` | lt | 2011-01-01 | Same BLI pair; the obligation is separately the Card Reader Installation. |
| 236 | `prior to the Target Commencement Date` | lt | 2014-04-01 | Carbonite p0572/p0573 at `[48757,48801)`, including the NBSP label. |
| 514 | `on or before the 1A Expansion Date` | lte | 2012-06-01 | 1A p0027 at `[4057,4101)`: `As of June 1, 2012 (the “1A Expansion Date”)`. |
| 519 | `no later than the 3A Suite 409 Amended Surrender Date` | lte | 2020-06-30 | 3A p0011 at `[2775,2841)`: `expiring June 30, 2020 (the “3A Suite 409 Amended Surrender Date”)`. |

Exactly these five rows are scheduled. The first three are strict bounds, with no subtract-a-day conversion and no due-on claim. The last two are inclusive upper bounds. The commercially reasonable efforts qualifications on 62, 65 and 236 remain in the original obligation evidence. 519 does not bind either the old surrender date, 2018-06-30, or commencement, 2018-07-01.

#### Challenge negatives and additional controls

| ID | Result | Evidence and assessment |
|---|---|---|
| 89 | contingent, no bound | Trigger is exactly `upon demand`; the later historical Effective Date does not bind. |
| 238 | unresolved, conditional_or_compound | `If the Commencement Date Conditions have not occurred prior to the Outside Completion Date` qualifies the termination right, with Force Majeure and further provisos retained. No May 31 deadline. |
| 239 | unresolved, conditional_or_compound | `prior to the earlier to occur of` leaves the unknown completion alternative intact. No selection of just the dated business-day branch. |
| 490 | unresolved, redacted_offset | `within [***] days after the occurrence thereof` never supplies a numeric offset or bound. |
| 504 | unresolved, redacted_offset | `On or prior to the date that is [***] after the date hereof` does not fall back to zero days. |
| 159 | unresolved, business_days | Ten business days after the Effective Date remains quoted and undated. |
| 57 | contingent, lte, offset 30 | `no later than thirty (30) days following receipt of an invoice` now matches. |
| 279 | unresolved, unsupported_unit | The 120-hour cure period is recognized as timing without calendar conversion. |
| 293 | unresolved, cross_reference | `within the time allowed pursuant to Section 16.1.1` supplies no guessed offset. |
| 434 | unresolved, business_days | The interrupted construction, `within three (3) Business Days ... once all outstanding fees have been paid`, stays undated. |

#### Fifteen fresh random hand checks

Selection: `random.Random(20261003).sample(ids_excluding_round_1_sample, 15)`, sorted. No row from the previous random sample was reused. Interpretations below are confined to the actual stored quote.

| ID | Result | Hand check |
|---|---|---|
| 3 | untimed | `[Tenant] shall pay all such Rent`: the extracted quote states no deadline. |
| 16 | untimed | Early termination right refers to Exhibit D. No self-contained performance deadline is quoted; wider cross-reference coverage remains an adjudication/recall concern, not a date to infer. |
| 56 | unresolved, recurring_schedule | Monthly rent for months 61 through 72. Correct recurring-schedule deferral. |
| 75 | untimed | Keep complete books and records of Additional Rent charges; no stated deadline in this quote. |
| 151 | unresolved, unsupported_unit | The 120-hour remedy period is not converted to days; the separate rolling 30-day default condition remains context. |
| 178 | untimed | Auto-liability coverage limits and covered vehicles; no stated deadline. |
| 203 | contingent, lte, offset 3 | Give written Tenant Delay notice within three days of its alleged first occurrence. Correct upper bound relative to an unobserved event. |
| 260 | unresolved, anchor_not_found | Resolve billing disputes `within thirty (30) calendar days`; the quote does not state what starts the period. Correct not to invent a start date. |
| 270 | contingent, lte, offset 30 | Credit/pay the abatement share within thirty days after Landlord actually receives the proceeds. Kind/offset are supported; the probe's broad quote boundary should be narrowed before gold span scoring. |
| 275 | contingent, gt | Notify `promptly after making any changes to the Datacenter`. After is a lower relation, not a computed due-on day; the original quote retains `promptly`. |
| 321 | contingent, lte, offset 10 | Pay insurance costs within ten days after Landlord's demand. Correct. |
| 327 | contingent, eq | Pay Excess Rent `immediately upon Tenant’s receipt thereof`. Immediate receipt-based timing, no known occurrence date. |
| 443 | untimed | **Prototype recall miss:** credit goes to the monthly invoice `in the month that Host receives the Curtailment Program Revenue`. This is event-relative month timing, not absent timing. Add the corpus construction at B5 and retain it as contingent or unresolved unsupported calendar granularity; do not invent a day. |
| 482 | untimed | Commercial-bribery prohibition; no deadline construction. |
| 485 | untimed | Non-solicitation prohibition in the extracted quote; no deadline construction. |

The miss on 443 is not a contradiction between rev 2 and the source: rev 2 already says timing language must not be called absent timing. It is a missing recognizer in this disposable completion of the still-unpublished lexicon. The counts above deliberately include that miss rather than presenting a corrected/adjudicated count as a frozen acceptance result.

### C) New blockers under the stop rule

#### R2-1 [blocker] Literal visible-owner joins create circular SQLite views

**Location:** rev 2 W5-3, especially “The obligation is in `visible_obligation`” and “Derived dates come only from this view”; rev-1 schema-v5 `visible_obligation` derivation, still applicable.

**Problem:** implementing the specified visible-owner membership with a join makes `visible_obligation_timing` read `visible_obligation`, while the final `visible_obligation` reads `visible_obligation_timing` for derived dates. That literal implementation is a cyclic view definition, not a recursive row query that SQLite can evaluate. It blocks the real graph readers before the strengthened evidence predicates can help. Equivalent raw eligibility predicates can satisfy the logical membership requirement without a join to the final view, but the section titled Complete eligibility SQL does not yet specify that crucial dependency split.

**Executed corpus reproduction:** `/tmp/w5_r2_sql.py` backs up `real_v4.db` into memory, preserves the real `visible_obligation` definition, adds a timing-bound subquery to it, and defines the timing view with the literal visible-owner join. The temporary timing table contains all 525 prototype classifications. Both queries fail:

```text
SELECT count(*) FROM visible_obligation
  -> view visible_obligation is circularly defined
SELECT count(*) FROM visible_obligation_timing
  -> view visible_obligation_timing is circularly defined
```

Adding containment and anchor predicates cannot remove this dependency cycle. This is reproducible on the actual corpus graph and prevents the required MCP/UI readers from working, so it meets the stop rule.

**Concrete fix:** split owner evidence eligibility from lifecycle/date derivation. Use an internal nonrecursive helper view or equivalent raw-table predicates that implement the existing grounded-own-citation rule. Have `visible_obligation_timing` depend on that helper plus its trigger-containment and cited same/base-anchor predicates. Have the final `visible_obligation` consume the helper and eligible timing projection. No path from timing eligibility may lead back through final `visible_obligation`. Keep the helper internal to schema SQL; readers still use the public projections.

I executed this acyclic dependency shape on the same in-memory graph: both the obligation and timing queries returned 525 rows. This is a satisfiability proof for the dependency split, not a complete implementation of the final eligibility SQL. B5 should freeze executable view definitions and a real-graph query test, then retain the revoked-ref, swapped-ref and foreign-anchor tests.

**Related integration check, not a second blocker:** do not keep the old `effective_due IS NULL` test as the sole classifier/filter for strict bounds. 62, 65 and 236 intentionally have null `effective_due` under rev 2 but must be included in the deadline window by their bound and relation. Freeze their lifecycle/bucket treatment explicitly so they are neither omitted nor counted twice. The existing v4 lifecycle reports all five prototype dated rows as pending until the new derivation is wired; that is expected old-code behavior, not proof that the new relation policy is wrong.

No other new blocker is established. The remaining lexicon coverage, minimal-span boundaries and typed-field retention are B5 implementation/labeling work. No model call or holiday-calendar expansion is needed to fix the reproduced issue.

### D) Verdict

proceed-after-fixes

## Round 3

### A) R2-1 disposition and executed proof

**R2-1: resolved.** Reviewed rev 2.1 at `025643f`. Implemented the prescribed dependency order in an in-memory backup of `tests/fixtures/graph/real_v4.db`:

```text
grounded_obligation -> visible_obligation_timing -> visible_obligation
```

The timing projection reads the internal grounded-owner helper, raw trigger/extraction refs for containment, and `visible_event_binding` for cited same-agreement/base anchors. It never reads the final obligation view or `visible_obligation_clause`, which itself depends on that final view. The final view derives lifecycle and deadline fields from eligible timing. Timing refs have separate ownership; the original extraction citations remain unchanged.

Executable: `/tmp/w5_r3_sql.py`. Output: `/tmp/w5-r3-run.txt`. The probe loaded all 525 round-2 classifications, created the grounded date-declaration events needed by the five schedules, and applied the new month-granularity rule to 443. All mutations stayed in memory. The fixture database hash remained unchanged, and `PRAGMA foreign_key_check` returned no violations.

| Baseline view | Rows |
|---|---:|
| grounded_obligation | 525 |
| visible_obligation_timing | 525 |
| visible_obligation | 525 |
| visible_obligation_clause, original extraction evidence | 525 |

Exactly five rows have lifecycle `scheduled`:

| ID | Lifecycle | Deadline relation | Deadline date | effective_due |
|---|---|---|---|---|
| 62 | scheduled | lt | 2011-01-01 | null |
| 65 | scheduled | lt | 2011-01-01 | null |
| 236 | scheduled | lt | 2014-04-01 | null |
| 514 | scheduled | lte | 2012-06-01 | 2012-06-01 |
| 519 | scheduled | lte | 2020-06-30 | 2020-06-30 |

These exact ids, relations, dates and effective-due values were asserted programmatically. Existing supersession precedence remains ahead of scheduled/pending lifecycle derivation.

**Citation negatives:** each mutation ran independently under a savepoint and was rolled back before the next case. All baseline counts returned to 525 after each rollback.

| Mutation | Timing-view rows | Obligation-view rows | Asserted outcome |
|---|---:|---:|---|
| Revoke 62's timing trigger ref | 524 | 525 | 62 becomes pending with no deadline, effective due, deadline ref or timing anchor; 65 remains scheduled. |
| Revoke the shared Commencement Date declaration ref | 523 | 525 | Both 62 and 65 lose timing eligibility and all derived date/binding fields. |
| Revoke 62's original extraction ref | 524 | 524 | 62 disappears from both public views. |
| Give 62 real ref 123, the quote belonging to 65 | 524 | 525 | Rejected by containment despite the same agreement and grounded ref; 65 remains scheduled. The timing ownership link was also updated, so this tests containment rather than merely missing link membership. |
| Give 62 foreign Carbonite event 5 | 524 | 525 | Rejected by agreement/base scope despite a grounded event. The stored candidate bound was also changed to 2014-02-01 to match event 5, ensuring rejection is not merely an arithmetic mismatch. |

**Ninety-day window:** selecting scheduled rows by `deadline_date BETWEEN '2010-12-15' AND date('2010-12-15', '+90 days')` returns exactly:

```text
62  lt  2011-01-01
65  lt  2011-01-01
```

Their null `effective_due` no longer excludes them. Each appears once, retains `lt`, and is excluded from pending by its scheduled lifecycle.

**Month-granularity case:** the new construction recognizer matches only 443 among these quotes and retains the exact slice `in the month that Host receives the Curtailment Program Revenue`. Its visible timing is `unresolved`, reason `month_granularity`, with null relation and bound; its lifecycle is pending. No calendar day or receipt date is invented. With that correction, the loaded prototype has 5 scheduled, 132 contingent, 149 unresolved and 239 untimed rows. As rev 2.1 specifies, these aggregate counts are descriptive, not acceptance targets.

### B) Blockers and known limitations

**New blockers: none.** The reproduced circular dependency is removed, and the real-graph eligibility, lifecycle, strict-window and month-granularity checks above pass.

**Known limitations:** this is an executable proof on the current corpus classifications, not a production schema or a full pipeline test. The current corpus has no legacy explicit due dates or legacy anchor/offset pairs, so their compatibility/conflict paths still need the already-planned B5 tests. The closed grammar, minimal trigger spans and independently adjudicated labels remain B5/C14 work; the prototype's aggregate counts do not substitute for those acceptance checks. No further synthetic cases are raised as blockers in this final round.

### C) Verdict

agree-to-proceed
