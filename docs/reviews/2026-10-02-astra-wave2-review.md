# Wave 2 advisor review, round 1

Reviewed main at `3366e71` after `git pull -q`: `CLAUDE.md`, ADR-001 through ADR-007, the wave-1 report, merged `src/og/**`, and `docs/superpowers/plans/2026-10-02-wave2-extract-store-eval.md`. Below, **plan** denotes that wave-2 plan. The coordinator's supplied Sonnet 5.5 request constraints are accepted; this review does not propose forced tools, sampling parameters, or disabling thinking.

Evidence: executed read-only imports with bytecode writing disabled, in-memory SQLite probes against the merged schema, and throwaway checks of the proposed number regex, JSON Schema nullability, duplicate keys, grounding fallback, and IoU matcher. Findings marked **executed** have that evidence. Wave-2 implementations and frozen tests do not yet exist, so these are design probes, not a claimed passing implementation suite.

**Counts: 5 blockers, 12 should-fixes, 0 nits.**

1. **blocker: VerifiedItem does not define a safe, complete payload for the writer.**

   **Location:** plan, Tasks 7 to 9, RawItem, VerifiedItem, verify rules, and writer preconditions; Task 11 agreement metadata; ADR-005.

   **Problem:** Only obligation `amount`, `due_date`, and `offset_days` receive field checks. Event `date` is never checked, so a model can quote `Commencement Date means [●]`, supply a valid ISO date, and create a grounded event from which the view computes deadlines. `currency`, names, role assertions, `trigger`, and free-form `description` remain raw. Nulling a guessed amount does not remove that guess from a description such as `Pay $45,000 each month`. VerifiedItem wraps the original RawItem and lacks a sanitized anchor/name/date/currency payload; rule 6 says to null `anchor_event` without providing a verified field for it. The writer's slice-equality test cannot distinguish these unsupported values. C0 also introduces agreement effective dates without recording their source evidence or distinguishing filing date from effective date.

   **Concrete fix:** Freeze a fully specified verified payload with kind-specific fields; raw output is diagnostics only and must never supply a stored field by fallback. Apply the same date verifier to event dates, retain null for unknown/form dates, validate currency evidence, and carry an explicit sanitized anchor reference. For the weekend baseline, use the copied quote as the displayed description and keep unsupported trigger text null instead of attempting deterministic semantic verification of arbitrary prose. Preserve model classification as an extraction result measured by eval, not a claim that quote matching proves entailment. Record evidence for manually entered effective dates in C0 or leave them null. Test a fabricated event date, a nulled amount still mentioned in description, and a raw field differing from its verified counterpart.

2. **blocker: Numeric occurrence is being mistaken for the field's meaning, unit, and direction.**

   **Location:** plan, Task 8 rules 4 to 6, `amount_in_text`, date matching, and offset verification; `visible_obligation` date arithmetic.

   **Problem:** **Executed:** the proposed number extraction accepts amount `30` from `Tenant shall pay within 30 days`, positive `5` from `Rent adjustment is -$5`, `54000.004` from `$54,000.00` under the tolerance, and `1` from `$1e6`. The offset rule accepts `30` in `30 months`; it does not distinguish before from after, calendar from business days, or a section number from a deadline. A date appearing in the quote can be the execution date rather than the due date. These are grounded characters but unsupported typed terms, and the resulting calendar deadline can be wrong while every span check passes.

   **Concrete fix:** Require a small field-evidence subspan for each retained value and conservatively recognize the supported units and relation around it. Use exact Decimal normalization with explicit sign and token boundaries; do not preserve extra precision merely because it lies within 0.005. Only map explicit calendar-day relations into `offset_days`, with before/after sign, and leave business-day/month/year arithmetic unresolved. Require the date evidence to identify its intended event/deadline relation. Unknown or ambiguous forms become null plus a diagnostic. Cut the proposed universal 1-to-365 number-word speller to a small tested grammar or digit-containing forms until gold evidence justifies more coverage. This is safer and smaller than a general contract-number parser.

3. **blocker: Party and anchor resolution can manufacture an uncited relationship.**

   **Location:** plan, Task 9 steps 4, 7, and 8; Task 8 kind checks; merged `party`, `agreement_party`, and `event` tables; ADR-007.

   **Problem:** Checking that party `name` and `role` are present in JSON does not check that the cited text names that party or establishes that role. `agreement_party` has no citation column, so the extracted role association loses its evidence. Removing LLC/Inc. distinctions can merge different legal entities. Role lookup can yield multiple landlords, and normalized event names can yield multiple candidates across base/amendment or prompt versions; no uniqueness, precedence, or ambiguity rule is given. Choosing the first row can redirect who owes an obligation or which event determines its deadline. The obligation quote also need not mention the chosen anchor at all.

   **Concrete fix:** Preserve a grounded citation for each agreement-party association and validate name/alias plus role evidence. Use conservative exact/case/spacing normalization and explicit cited aliases, not automatic equivalence between different entity suffixes. Resolve within the selected agreement/run context only, require exactly one supported candidate, and otherwise keep NULL with a warning. Apply the same unique-candidate rule to event names, with explicit same/base precedence and evidence that the obligation references that anchor. Keep base events outside the selected lineage ineligible. Add ambiguous-role, distinct-entity, conflicting-base-event, and invented-alias tests. Deferring uncertain resolution is an acceptable weekend outcome.

4. **blocker: Delete-and-replace cannot meet the promised multi-run isolation with the existing keys and references.**

   **Location:** plan, Task 9 transaction and migration; merged `schema.sql` uniqueness constraints, FK relationships, and visible views; C4 repeated runs.

   **Problem:** **Executed after adding only the proposed ownership columns:** inserting the same defined term for a second run fails `UNIQUE(agreement_id, term)`, and the same party-role association fails the existing composite primary key. One `extraction_run_id` cannot express shared ownership without stealing a row from another run. Deleting a base run's event fails when an amendment obligation from another run references it. Associated ClauseRefs and future edges add further deletion dependencies, and the plan gives no cleanup order or orphan-reference ownership. Conversely, keeping every prompt version's obligations makes them all visible because `visible_obligation` has no selected-run predicate, so ordinary readers and eval can mix duplicate or contradictory versions. Upserting a source pin or agreement metadata can also reattribute older retained runs unless source identity is immutable.

   **Concrete fix:** Choose one coherent model before tests freeze. A small solution is immutable extraction snapshots with one explicitly selected complete snapshot per source, evidence/provenance tables that can retain each run's references, and views/read adapters selecting that snapshot. Another small solution is one production snapshot plus separate experiment databases, with the plan explicitly withdrawing the promise to keep multiple prompt versions live in the same DB. In either case, define shared party/term ownership, stable or deliberately remapped event IDs, and dependent-reference handling. Do not use cascading deletion to silently erase another source's evidence. Pin source/document identity, reject unsupported source repinning, and test two prompt versions, a base/amendment rerun, rollback after an insertion failure, and orphan-reference cleanup. Use `ON CONFLICT ... DO UPDATE` deliberately rather than destructive `INSERT OR REPLACE` on referenced parents.

5. **blocker: A refused or incomplete extraction can replace a valid document with an empty or partial result.**

   **Location:** plan, Task 7 `parse_response`/Extractor, Task 9 transaction, Task 11 CLI, and C1/C3.

   **Problem:** Refusal becomes `items=[]`, indistinguishable at the item boundary from a successful empty chunk. The aggregate has call metadata but no required completeness state or writer precondition. If one chunk refuses, a literal CLI can verify the remaining chunks and replace the previous full run with a partial graph; an all-refused document can erase it entirely. Truncation/BadResponse handling, retries, and cache treatment are unspecified. Server-side fallback does not guarantee a successful final answer.

   **Concrete fix:** Return explicit per-chunk outcomes and a document completeness result. Permit replacement only after every expected chunk has a validated terminal success, including legitimate successful empty output; preserve the previous committed run on refusal, truncation, API error, invalid response, or missing chunk. Log failure metadata and costs even when no write occurs. Define a bounded retry/coordinator-retry policy and do not let cached failures masquerade as successful empty extractions. Check stop reasons before parsing. Anthropic documents that refusals and token-limit responses can violate the output schema, so JSON validity alone cannot establish completion. [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

6. **should-fix: Marker handling contradicts the field-specific preservation rule and can miss omitted markers.**

   **Location:** plan, Task 8 rule 3 to 4; Review Focus 3; ADR-005.

   **Problem:** Any marker anywhere in the selected slice unconditionally nulls the amount. `Rent is $1,000; delivery date is [●]` therefore loses a supported amount, contrary to ADR-005's rule to null only fields hidden by markers. Conversely, the model can quote a fragment ending before a redaction and cause status `active`; absence of a marker in a selected fragment is not proof that all proposed fields are known. A single obligation status cannot describe which of several fields is hidden. The new schema also excludes `superseded` although CLAUDE.md retains that document status; wave-3 deferral needs to be explicit rather than accidentally mapping such assertions to active.

   **Concrete fix:** Use field-local evidence and marker diagnostics, preserving independently supported fields. Define the status aggregation and mixed blank/redacted precedence, and inspect the surrounding cited segment when determining whether a proposed value fills a placeholder. Keep document lifecycle/supersession interpretation out of this override rule. Add mixed known/hidden amount/date cases and quote-fragment cases. State whether superseded extraction is explicitly deferred; do not infer active legal effect merely from no marker.

7. **should-fix: The schema migration is not specified as an executable, idempotent upgrade.**

   **Location:** plan, Task 9 ownership and migration sentence; merged `src/og/store/db.py` and `schema.sql`; coordinator bootstrap.

   **Problem:** Current `connect()` reruns `CREATE TABLE IF NOT EXISTS` statements and recreates views. Editing those table declarations will not add columns to a wave-1 DB; unconditional `ALTER TABLE ADD COLUMN` will fail on the next connect. Changing row keys/provenance for finding 4 requires more than three columns. Call histories, served models, and run selection also have no storage contract. Task 9 owns only writer.py, so a worker cannot safely invent the migration runner it needs.

   **Concrete fix:** Make the coordinator-owned schema/version migration a named prerequisite before writer tests freeze. Specify fresh-DB creation, a one-time transactional upgrade path, migration version detection, and ownership of any db.py change. Preserve rows, FKs, views, and triggers; test upgrading a populated wave-1 DB twice and reopening it. Run migration outside the writer's transaction because `executescript` has transaction behavior that must not split the advertised atomic replacement. Reconcile ADR-001 if migration application changes.

8. **should-fix: Shared interfaces and dependency gates do not support the proposed parallel wave.**

   **Location:** plan, Execution topology, Tasks 7 to 11, C0/C1, frozen-test ownership.

   **Problem:** Task 8 consumes RawItem from Task 7 but starts in parallel with it; RawItem's defining module is not named. Task 9 depends on CallMeta/RunInfo plus the migration, yet is gated only on Task 8. Task 10's PredItem, GoldItem, Score, database adapter, and party normalization contract are undefined. C1 replay tests call verify but are scheduled after only Task 7 merges. Task 7 calls an existing `extract/__init__.py` a new file, and the new effort/chunk/cache environment settings have no `.env.example` owner. Import-time stubs and shared file ownership matter for weaker models.

   **Concrete fix:** Before dispatch, have the coordinator freeze a small shared types module and exact import paths, including sanitized fields and errors. Give workers disjoint module ownership. Gate writer work on the types and migrated schema; gate C1 replay acceptance on both client and verifier; give C0/config changes an explicit owner and merged baseline. Reuse the wave-1 accepted-base SHA, test-manifest, salvage, and review procedures with a new wave-2 red baseline. Coordinator-authored replay additions must update the freeze evidence through the recorded process.

9. **should-fix: The purported exact-duplicate key collapses distinct facts.**

   **Location:** plan, Task 8 rule 8.

   **Problem:** `(kind, type, char span)` omits the asserted fact. Two party items quoting the same preamble have `kind=party`, `type=null`, and the same span, but different names/roles. **Executed:** that key collapses them from two entries to one. The same applies to two named events in one clause or multiple payment obligations sharing a paragraph but differing in amount, timing, or counterparties. Choosing an arbitrary survivor changes later resolution and measured recall.

   **Concrete fix:** Collapse only identical canonical verified payloads with identical evidence, using kind-specific identity fields. Keep distinct facts sharing a quote, and record conflicts rather than silently selecting a winner. Decide whether overlapping but nonidentical quote slices for the same fact stay separate until a later explicit reconciliation step. Add same-span/two-parties, same-span/two-events, and same-type/two-payments cases.

10. **should-fix: The JSON schema and parser contract leave required/null/type combinations ambiguous.**

    **Location:** plan, Task 7 schema rules, RawItem, and parse_response.

    **Problem:** The instruction that all fields allow null through `["string","null"]` conflicts with numeric amount/integer offset types and with mandatory kind/status identifiers. Nullable enums need `null` in the enum itself. **Executed:** `type=["string","null"], enum=["payment","notice"]` rejects null, which party/event items need for obligation type. A dataclass constructor is not JSON Schema validation; missing fields, non-list items, booleans as numbers, nonfinite values, invalid dates, unknown enum values, and unused non-null fields need a policy. `parse_response(message)` cannot derive requested model or measured latency from the response alone.

    **Concrete fix:** Freeze the actual schema with each field's type, nullability, enum including null when appropriate, required list, and `additionalProperties:false` on each object. Use a flat schema plus local kind-specific validation if that is simpler than unions. Validate calendar dates and finite numeric types locally. Separate parsing from the request/timing metadata supplied by Extractor; define no-text and unexpected-block errors. Keep this client non-streaming, ignore thinking/fallback marker blocks when selecting the structured text, and test SDK-shaped messages as well as SimpleNamespace fixtures. The API supports null and scalar enums, but has a documented supported-schema subset; validate the exact schema in C1 rather than assuming a synthetic fake proves API acceptance. [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

11. **should-fix: Chunk limits, header citations, and section fallback need one explicit contract.**

    **Location:** plan, Decisions, Task 7 chunk_doc/prompt, Task 8 grounding, Task 11 header construction; merged TextDoc and ground.py.

    **Problem:** A segment can exceed the 12,000-character cap, and header/ID-rendering overhead is not assigned to that cap. An absent preamble, a preamble occupied by TOC text, or parties beyond its first 1,500 characters leaves an incomplete header. Unnumbered copied header facts cannot satisfy the prompt's requirement to quote one numbered line in later chunks. **Executed:** ground() legitimately relocates a quote from the claimed segment to another segment in the same section; after Task 6, that section could be a large preamble. VerifiedItem retains the original RawItem segment_id, so storing/exporting it without correction gives inconsistent citation metadata.

    **Concrete fix:** Specify whether the cap is soft, how one oversize segment is handled, and what counts toward it. Keep a deterministic header with explicit source segment IDs and distinguish context-only repeats from extractable chunk segments. Define fallback permission and log relocation; derive the final actual segment ID when the match is wholly inside one segment, or reject/represent multi-segment evidence explicitly. Do not silently require strict segment matching while tests expect ADR-002 same-section fallback. Verify chunk completeness and metadata against the final Task 6 TextDoc before API recording.

12. **should-fix: TOC suppression lacks a stable classification rule and does not suppress extraction from TOC text.**

    **Location:** plan, Task 6 Rule and acceptance; Task 7 prompt; merged ingest/sections.py; C1/C2/C3.

    **Problem:** The rule depends on a later occurrence being non-TOC, but does not specify evaluation direction or scope for repeated numbers. The merged scanner has four patterns, including single-level and table-cell clauses, not just dotted clauses. Identical numbers may legitimately recur in exhibits or article contexts, so a corpus-wide no-duplicates acceptance can encourage deleting real headings. Suppressed heading lines still remain segments in a larger enclosing section and are sent to the model; `No obligations from the table of contents` is only a prompt instruction. The exact 293-section issue is not named in the wave-1 report's Known limits, so the plan needs its own recorded specimen rather than an assertion about report evidence.

    **Concrete fix:** Freeze realistic TOC/body line fixtures from the corpus and use a defined reverse classification pass with scope and candidate-pattern rules. Report the specific TOC duplicates removed, not a universal ban on repeated numbers. If TOC items must never become obligations, retain/expose their segment classification and exclude or deterministically reject those segments. Give any required TextDoc/chunk metadata change an owner. Re-ingest before recording fixtures or exporting labels, and bind those artifacts to the resulting TextDoc digest/version as well as the raw-source pin.

13. **should-fix: Cache identity, cache bypass, and incomplete-result behavior are underspecified.**

    **Location:** plan, Task 7 ResponseCache/Extractor, prompt_version, and C4.

    **Problem:** `get(doc_id, prompt_version, chunk_id)` has no request-hash argument despite the stated request-hash key. The path names also do not distinguish no-cache variance samples. There is no atomic-write/corruption policy, no rule for cached refusal/truncation, and no distinction between historical billed call metadata and a zero-network replay. Prompt version hashes only prompt/schema bytes, so reproducibility also needs the code/ingest/verifier versions. The absolute claim that identical requests are never re-billed cannot cover a crash after the API charged but before the response was durably cached.

    **Concrete fix:** Pass a canonical request fingerprint into both get and put, bind it to source/TextDoc identity, and persist only validated successful responses atomically. Treat corruption as an explicit miss/error and keep failure records separate. Define `OG_EXTRACT_NO_CACHE=1` as bypassing reads without overwriting unrelated canonical samples, and archive each variance response under an attempt ID. Record `cache_hit`, historical usage, and actual incremental cost separately. State the realistic guarantee: durable successful hits avoid another API request. Keep cache storage to parsed output plus the response metadata needed for replay, with an explicit allowlist; never serialize credentials, request headers, client/request objects, environment dumps, or unsanitized exception representations.

14. **should-fix: Fallback billing and model attribution cannot be represented accurately by one flat CallMeta.**

    **Location:** plan, Task 7 CallMeta/parse_response, Task 11 pricing constant, and C4 result metadata.

    **Problem:** The plan records one served model and one set of usage totals, then prices everything as Sonnet 5.5. Anthropic documents that top-level usage describes only the returned attempt; `usage.iterations` carries separate fallback attempts and models. Some declined attempts can be billed too. Requested-versus-served string inequality is not a sufficient fallback detector. A small cached system block may also have no prompt-cache hit, so cache discounts must not be assumed from the presence of `cache_control`. [Refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback), [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

    **Concrete fix:** Preserve per-attempt model/usage and refusal outcome plus end-to-end call latency, using documented fallback metadata. Price each supported served model using a dated, sourced table and mark unknown charges unknown instead of applying the requested model's rate. Keep refusal billing rules explicit or label the result an estimate. Test ordinary success, non-streaming fallback, final refusal, absent cache fields, and a cached replay. Non-streaming fallback omits the declined attempt's partial output, so the plan's first-text approach is not itself a demonstrated bug for this path; retain the usage history for accounting. [Refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback).

15. **should-fix: Gold validation and the matching rule do not yet define an honest, reproducible accuracy measure.**

    **Location:** plan, Task 10 gold format/load_gold/score; C2 labeling export.

    **Problem:** Raw hash plus slice equality does not validate doc_id, segment membership, offset bounds, types/statuses, label completeness, or which ingest produced section metadata. PredItem and its database-to-role/name conversion are unspecified. IoU 0.3 plus equal type measures rough localization, not correctness of the stated obligation. **Executed counterexample:** gold spans `[0,100)` and `[60,160)`, predictions `[0,110)` and `[0,50)` yield only one greedy match, although two threshold-valid matches exist. Ties specify earlier gold but not prediction order. Null-heavy field accuracy and role-only counterparty comparisons can hide systematic missing values or the wrong entity. Currency, anchor, offset, and trigger accuracy are omitted despite feeding claims and deadlines.

    **Concrete fix:** Validate gold against document identity, bounds, segment/evidence shape, typed fields, and an explicit annotation scope; label a full agreement or disclose sampled coverage. Freeze a metric version, threshold, denominators, empty-set/macro conventions, and deterministic tie ordering before C3. Prefer maximum-cardinality matching with IoU as secondary quality, or retain the simpler greedy metric with the demonstrated limitation explicitly documented. Report localization separately from matched-field correctness, known-field recall/coverage, and null cases; compare actual resolved party identities as well as roles and score the retained deadline/currency fields. Add counterexamples and wrong-value/right-span cases. Do not tune gold or the threshold on the final evaluation run.

16. **should-fix: Grounded rate, diagnostics, and scoring entrypoints are incomplete.**

    **Location:** plan, Task 10 grounded_rate/drops_count; Task 11 logging; C4; merged visible_obligation and Makefile.

    **Problem:** **Executed:** an obligation with one grounded and one ungrounded reference remains visible, so the proposed all-references-grounded metric is not 1.0 by construction. If it instead means any grounded reference among visible rows, it is a tautological integrity check rather than extraction grounding success. Append-only `drops_count(log_path, doc_id)` accumulates old runs, while field-nullification flags live on surviving VerifiedItems and may never be logged by a CLI that writes only Drops. No task owns the PredItem query adapter or executable score/results writer; `make eval` remains a stub, despite the stated extraction-eval deliverable. Print cost_usd also lacks a precise result object/source.

    **Concrete fix:** Define separate integrity and proposal-grounding metrics with explicit denominators, zero-item behavior, and selected run/attempt IDs. Record dropped items and surviving-item field corrections distinctly; do not call field sanitization an obligation drop. Key logs by attempt, source/TextDoc, prompt, chunk, and outcome, and derive counts for the evaluated attempt only. Assign the query adapter and extraction scoring CLI/results writer to a named task with exact interfaces and temp-DB tests. Query the selected visible snapshot and deduplicate multiple ClauseRefs without multiplying predictions. Use allowlisted log fields and verify the sentinel credential is absent from every failure/cache/fixture path, not just the happy-path drop file.

17. **should-fix: Variance runs contradict ADR-006 and overwrite the evidence they must compare.**

    **Location:** plan, C4, Task 9 run key, Task 7 cache bypass; ADR-006; eval/results artifact.

    **Problem:** C4 specifies three runs while ADR-006 specifies five. All repetitions share source and prompt_version, so normal writer replacement can discard preceding samples. Global log counts and cached historical costs can then masquerade as per-sample results. With automatic fallback, variance may include served-model changes rather than only extraction nondeterminism. There is no prescribed sample identity, retained prediction set, dispersion statistic, or definition of the baseline used for adoption decisions.

    **Concrete fix:** Use five independent uncached samples to match ADR-006, or explicitly revise the ADR with a justified smaller exploratory protocol before freezing. Archive each sample's proposals, verified predictions, call metadata, model sequence, scores, and hashes outside the production graph; score it before selecting any production snapshot. Report sample count and an explicit statistic such as mean plus range or standard deviation, with fallback samples labeled. For this portfolio wave, one gold document and a small auditable score artifact are sufficient; defer a general experiment framework, broad model bake-off, and automatic prompt-adoption machinery. This keeps the variance evidence without expanding the project beyond the weekend scope.

proceed-after-fixes
