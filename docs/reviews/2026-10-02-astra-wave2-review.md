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

## Round 2

Reviewed bootstrap B2 at `b208907` after `git pull -q`, the revised plan including rev 2.1, the frozen contracts, and all frozen tests. Here, **plan** means `docs/superpowers/plans/2026-10-02-wave2-extract-store-eval.md`. This round changes only this review in the repository.

### A) Round-1 dispositions

1. **Partially resolved.** Kind-specific sanitized payloads and event-date/trigger checks exist, but the new description rule permits unsupported prose and event names remain unchecked; see R2-2 and R2-3.
2. **Partially resolved.** Decimal equality, money units, direction, and deadline cues fix the original examples, but the new token regexes accept partial numeric tokens and the independently valid deadline fields can violate the DB CHECK; see R2-5 and R2-6.
3. **Partially resolved.** Cited party rows, exact names, and unique resolution are improvements, but co-occurrence of a name and role does not establish their association, and an invented event name still resolves; see R2-2 and R2-4.
4. **Partially resolved.** Single-snapshot replacement and transactions pass, but base-first ordering does not repair an existing dependent lineage, and per-document sample DBs cannot represent amendment dependencies; see R2-7.
5. **Resolved.** Explicit chunk outcomes distinguish successful empty output from failure; the CLI preserves the previous snapshot on an incomplete run.
6. **Resolved.** Separately supported fields survive markers, outside-quote markers are diagnosed, status precedence is explicit, and supersession is deferred.
7. **Resolved.** The coordinator-owned v2 contract explicitly replaces migration with a fail-closed rebuild policy, tested on old and reopened databases.
8. **Resolved.** Bootstrap types/schema, disjoint implementation ownership, the writer's independent prerequisite, and C1's verifier prerequisite remove the original scheduling hazards.
9. **Resolved.** Equality of the entire verified payload preserves distinct parties and payments sharing one quote.
10. **Resolved.** The actual nullable schema and local parser contract are compatible; all 35 parser tests pass, including SDK objects, invalid dates, booleans, and NaN. Live schema acceptance remains the already assigned C1 check.
11. **Partially resolved.** Evidence relocation and oversize segments are defined, but rev 2.1's context prefix conflicts with the non-overlap requirement at small caps; see R2-1.
12. **Resolved.** Rev 2.1 requires page-reference lines, handles roman numerals and the Page header, and both chunking and verification suppress classified TOC evidence.
13. **Resolved.** The request/TextDoc fingerprint, atomic successful-only cache, corruption handling, allowlist, and separate no-cache archive are implementable and pass.
14. **Resolved.** Attempt-level usage, served models, unknown-model cost, and cache-hit metadata replace the flat accounting contract; real fallback shape remains C1's responsibility.
15. **Partially resolved.** Gold validation, maximum-cardinality matching, deterministic ties, and known-field coverage pass, but the admitted sampled scope has no evaluation boundary; see R2-8. Role accuracy must still be described as role accuracy, not entity accuracy.
16. **Resolved.** Proposal grounding and integrity are separate, corrections and drops are distinct, and the writer/extract/eval run identity and log interfaces work together in an executed integration probe.
17. **Resolved.** Five uncached samples, retained sample DBs, mean/range reporting, and fallback labels match ADR-006; amendment isolation needs the operational fix in R2-7.

**Disposition totals: 11 resolved, 6 partially resolved, 0 unresolved.**

### B) Satisfiability proof

Created a fresh disposable copy at `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/og-astra-wave2-r2-0l0vyo1s`. Implemented TOC scanning, chunking, prompt/request construction, response parsing, cache, verification, writer, both CLIs, gold loading, and scoring there. Used the repository's v2 schema/db, types, prompts, and existing wave-1 implementations unchanged. The scorer uses an actual augmenting-path maximum-cardinality matching with exact rational IoU costs, not greedy matching or test-specific answers.

`uv sync --locked` succeeded with CPython **3.12.11**. Ran the full suite using `uv run --locked pytest -o addopts="" -q -p no:cacheprovider`, with an additional `--junitxml` output path for counting. All 35 inspected test/fixture/manifest, contract, prompt, and dependency files in the copy were byte-identical to the repository; no frozen tests were altered.

There are two relevant runs:

- **Literal rev 2.1 context prefix:** 611 passed, 1 failed, 2 skipped. The single failure is the contract conflict below.
- **Candidate clarification:** freeze context to the leading, at-most-1500-character segments that actually belong to chunk 1. With only that context choice clarified, the full suite passes: **612 passed, 0 failed, 2 skipped**. This is a demonstrated repair, not a claim that the coordinator has approved that rule change.

| Frozen test file | Literal prefix: pass/fail/skip | Clarified prefix: pass/fail/skip |
|---|---:|---:|
| `tests/test_eval_cli.py` | 5/0/0 | 5/0/0 |
| `tests/test_eval_gold.py` | 16/0/0 | 16/0/0 |
| `tests/test_eval_score.py` | 13/0/0 | 13/0/0 |
| `tests/test_extract_cache.py` | 11/0/0 | 11/0/0 |
| `tests/test_extract_chunk.py` | 11/1/0 | 12/0/0 |
| `tests/test_extract_cli.py` | 7/0/0 | 7/0/0 |
| `tests/test_extract_parse.py` | 35/0/0 | 35/0/0 |
| `tests/test_extract_request.py` | 9/0/0 | 9/0/0 |
| `tests/test_fetch.py` | 23/0/0 | 23/0/0 |
| `tests/test_fetch_recorded.py` | 1/0/0 | 1/0/0 |
| `tests/test_ground.py` | 265/0/2 | 265/0/2 |
| `tests/test_ingest.py` | 23/0/0 | 23/0/0 |
| `tests/test_ingest_toc.py` | 10/0/0 | 10/0/0 |
| `tests/test_markers.py` | 17/0/0 | 17/0/0 |
| `tests/test_schema.py` | 41/0/0 | 41/0/0 |
| `tests/test_schema_v2.py` | 9/0/0 | 9/0/0 |
| `tests/test_textdoc.py` | 19/0/0 | 19/0/0 |
| `tests/test_verify.py` | 78/0/0 | 78/0/0 |
| `tests/test_writer.py` | 18/0/0 | 18/0/0 |
| **Total** | **611/1/2** | **612/0/2** |

**Failure classification:** `tests/test_extract_chunk.py:82`, `test_context_block_only_after_first_chunk`, asserts `not set(ctx_ids) & set(c.segment_ids)`. Classified **test-wrong relative to the literal rev 2.1 prefix rule**, meaning a test/contract contradiction, not an instruction to weaken this useful assertion. The literal prefix contains `p0011`, which is also chunk 2's primary segment at cap 800. The same prefix cannot all be in chunk 1 under that cap. Keep the assertion and amend the rule as R2-1 recommends. There are no remaining impl-wrong frozen-test failures and no other frozen-test failures. Both skips are existing `test_ground.py` property cases explicitly skipped for a single-character quote, not missing implementation or network skips.

**Cross-file consistency:** also executed extract CLI -> writer -> eval CLI on the frozen lease fixture in a separate temporary working directory. It produced two visible obligations, `proposed=2`, `verified=2`, proposal grounding `1.0`, and six call records. DB and log `run_id` agree; DB, log, and score prompt versions agree; all three TextDoc hashes equal `sha256(doc.to_json().encode())`. No workaround or special fixture-dependent run identity was needed. The frozen eval log fixture is independently constructed, so this additional round trip verifies the actual producer/consumer boundary.

**Verifier satisfiability:** all 78 verifier tests are simultaneously satisfiable under Task 8/rev 2.1. Their passing result does not establish the stronger invariant: the separate executable probes in R2-2 through R2-6 demonstrate untested unsafe cases in the rule text itself.

Audit artifacts outside the repository: `/tmp/astra-wave2-literal.xml`, `/tmp/astra-wave2-final.xml`, their corresponding `.txt` outputs, `/tmp/astra_w2_probes.py`, and `/tmp/astra_w2_crossfile.py`. Latest field/writer probe results are in `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/astra-w2-probes-93avmhyf/results.json`. These are disposable evidence, not production implementations.

### C) New revision findings

The examples below target the newly specified rev-2 rules or their composition. References to round-1 findings identify the partial resolutions above rather than restating the original review wholesale. **Counts: 6 blockers, 2 should-fixes.**

1. **R2-1, blocker: The context-prefix and primary-segment rules cannot both hold literally.**

   **Location:** plan, Task 7 chunker and rev 2.1 Context block; `tests/test_extract_chunk.py:82`.

   **Problem:** Rev 2.1 selects the leading non-TOC segments up to 1500 characters, while the main task says context segments never belong to later chunks and every non-TOC segment appears as primary exactly once. At an 800-character cap, that prefix extends beyond chunk 1. **Executed:** the literal rule fails the exact non-overlap assertion with `p0011` in both context and chunk 2. A worker must invent precedence to get green.

   **Concrete fix:** State that chunk 1 is packed first and the fixed context prefix is selected only from its primary segments, up to 1500 characters, always at least one when nonempty. Preserve the full rendered-text soft cap and the frozen non-overlap assertion. This clarification produces the demonstrated 612-pass run; add a test pinning exactly which context IDs are chosen so cumulative and fixed-context interpretations do not diverge.

2. **R2-2, blocker: A checked date can be attached to an invented event name and calculate a false deadline.**

   **Location:** plan, Task 8 rules 1, 7, and 8; Task 9 event insertion/anchor resolution; `visible_obligation`.

   **Problem:** Events require a nonempty name, but only their date is checked against the quote. **Executed:** quoting the frozen verifier fixture's `“Delivery Date” means March 1, 2011.` while naming the event `Commencement Date` passes verification and storage. A separate valid 30-days-after-Commencement obligation then becomes visible with `effective_due = 2011-03-31`, although the actual Commencement definition is blank. This bypass remains after the round-1 fabricated-date fix.

   **Concrete fix:** Require the event name in its copied evidence and require the retained date to belong to that named event's defining clause, not another date in the same segment. Conservatively keep the event date null when that local association is ambiguous. Freeze this swapped-name regression through verify, writer, and the effective-due view.

3. **R2-3, blocker: The new digit-only description gate explicitly admits invented terms.**

   **Location:** plan, VerifiedObligation.description and Task 8 rule 10; `tests/test_verify.py` description tests; ADR-005.

   **Problem:** A description with no digits vacuously passes the rule. **Executed:** a rent-payment quote is stored and returned by `visible_obligation` with description `Landlord waives all rent forever.` No correction is emitted. Digit-run presence also cannot validate reordered amounts, units, actors, or negation. Typed-field sanitization does not protect the displayed free-text field.

   **Concrete fix:** For this wave, set the persisted description to the copied quote, with any model paraphrase confined to clearly unverified diagnostics. Update the two frozen tests that require preservation of model paraphrases and add the waiver counterexample. This reduces implementation work and directly preserves the project's stated citation invariant.

4. **R2-4, blocker: Same-quote role co-occurrence can reverse the actual parties.**

   **Location:** plan, Task 8 rules 11 and 12; Task 9 party/role resolution; frozen verifier preamble fixture.

   **Problem:** The new party rule independently checks that a name and a role occur somewhere in the quote. Both roles occur in the shared preamble used by the tests. **Executed:** DIGITAL 55 MIDDLESEX, LLC proposed as tenant and CONSTANT CONTACT, INC. proposed as landlord both pass against that preamble. Unique role resolution then makes DIGITAL the rent payer in the visible obligation. Exact-name matching and cited association rows do not prevent this reversal.

   **Concrete fix:** Accept only a locally evidenced name-role association, such as the source's `NAME, as ROLE` construction, or require a narrower party evidence slice that contains that association unambiguously. Leave unsupported associations absent and retain unresolved role references as null. Add the swapped-role negative beside the existing two-parties-positive test; do not try to solve arbitrary legal coreference in this wave.

5. **R2-5, blocker: The verified deadline payload can violate the frozen schema's mutual exclusion CHECK.**

   **Location:** plan, Task 8 rules 6 through 8 and rev 2.1 pair rule; `src/og/store/schema.sql`, obligation CHECK; Tasks 9 and 11.

   **Problem:** The rules synchronize `anchor_event` and `offset_days` but never reconcile them with `due_date`. **Executed:** `Tenant shall pay by March 1, 2011 within 30 days after Commencement Date.` independently validates all three fields. With a resolvable event, the writer raises `IntegrityError: CHECK constraint failed: NOT (due_date IS NOT NULL AND anchor_event_id IS NOT NULL)` and rolls back the whole otherwise complete document. This is a verifier/writer contract gap, not a reason to remove the CHECK.

   **Concrete fix:** Define deterministic conflict handling before VerifiedObligation construction. A small conservative policy is to retain the separately evidenced absolute due date, null the relative pair, and record a conflict correction; alternatively drop an ambiguous proposal. Add a verifier test and an end-to-end writer test for this case, including preservation of the prior snapshot if verification elects to fail the document.

6. **R2-6, blocker: The new numeric regexes match prefixes and suffixes of larger tokens.**

   **Location:** plan, Task 8 amount and offset regexes; `tests/test_verify.py` numeric cases.

   **Problem:** Exact Decimal comparison is performed after regex tokenization, so it does not make a partial token safe. **Executed:** `$5.123` supports model amount `5.12` under the supplied two-decimal regex and reaches the visible row. Likewise `1000 days after Commencement Date` matches the suffix `000 days`, verifies model offset `0`, and stores zero when the anchor exists. Neither is the value written in the source.

   **Concrete fix:** Add explicit numeric-token boundaries and reject an entire unsupported precision/grouping token instead of matching its prefix. For offsets, either support the full arbitrary-length digit token or reject a token longer than the supported limit without matching its suffix. Freeze these cases and malformed comma/decimal continuations before dispatch.

7. **R2-7, should-fix: Lineage refusal and sample isolation lack an executable recovery path.**

   **Location:** plan, Task 9 `dependents_exist` precondition, Task 11 ordering and `--no-cache --runs-dir`, C4.

   **Problem:** `Re-extract the lineage base-first` cannot cure a base that already has dependent obligations. **Executed:** after writing the frozen base and amendment fixtures, a base-first rerun immediately raises `WriteRefused('dependents_exist')`. Separately, a fresh `X/amendment.db` has neither its base agreement nor base events; writing that amendment with its real `base_agreement_id` raises an FK failure even if the base was processed first into `X/base.db`. The one-document CLI fixtures do not exercise either case.

   **Concrete fix:** Keep the fail-closed writer check, but document a coordinator rebuild into a fresh whole-graph DB followed by promotion for lineage-wide re-extraction. For variance, either explicitly limit samples to standalone base documents in this wave, or build each sample DB with its necessary base lineage. Reject an unsupported amendment sample before any API calls. Add two-document integration coverage; do not silently drop base IDs or anchors to make isolated samples succeed.

8. **R2-8, should-fix: Sampled gold has no boundary for deciding which predictions are false positives.**

   **Location:** plan, Task 10 Gold.scope, `score(gold, predicted)`, score CLI, and C2 export; `tests/test_eval_gold.py` and `tests/test_eval_cli.py`.

   **Problem:** The format admits `scope: sampled`, but contains no sampled segment/range set and the score CLI sends every visible obligation to the matcher. Correct predictions outside the labeled sample therefore count as false positives. The scorer receives only the obligation list, so it cannot infer which unlabelled regions were inspected. The frozen tests cover only a full agreement and do not close this reporting hole.

   **Concrete fix:** For the weekend baseline, require `full_agreement` for scored reference sets and reject sampled sets at the score CLI. Alternatively define explicit sampled regions and filter predictions consistently before scoring, publishing the coverage. Keep role-only field scores labeled as such and do not present localization or role correctness as full legal-term or entity correctness.

### D) Verdict

proceed-after-fixes

## Round 3

Reviewed `36dbbc3` after `git pull -q`, the plan's overriding Rev 2.2 section and R2-8 detail, the recorded frozen-test changes, and the new pipeline regressions. Only this review is changed in the repository.

### A) Round-2 dispositions

1. **R2-1: resolved.** Chunk-1-only fixed context is explicit and both exact-ID tests pass.
2. **R2-2: not resolved.** The original invented-name case is rejected, but the new date-binding rule still attaches a later unrelated date to a real event name; see R3-1.
3. **R2-3: resolved.** Every stored obligation description is its copied evidence slice, including the waiver counterexample.
4. **R2-4: not resolved.** The original shared-preamble reversal is rejected, but the new first-following-role rule misbinds ordinary role-before-name text; see R3-2.
5. **R2-5: resolved.** Absolute-date precedence nulls the relative pair and the conflict writes and replaces a prior snapshot successfully.
6. **R2-6: resolved.** Complete-token rules reject extra decimal digits, malformed grouping, and the suffix of a four-digit day count.
7. **R2-7: resolved.** The plan retains the writer's fail-closed check, specifies a fresh whole-graph rebuild, and rejects amendment samples at the CLI before calls or output creation.
8. **R2-8: resolved.** The explicitly sampled reference set reports precision lower bounds, null precision and F1, and recall over the supplied labels. This is the coordinator's accepted alternative to requiring exhaustive gold; these figures must retain that sampled-scope disclosure.

**Totals: 6 resolved, 2 not resolved. All original round-2 counterexamples now have the intended safe behavior; the two remaining issues are new variants of the binding rules.**

### B) Refreshed satisfiability proof and probes

Created a fresh copy of the current repository at `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/og-astra-wave2-r3-00xg_fwt`, carried over only the disposable implementation modules, and updated verification and both CLIs to Rev 2.2. The chunker already implements the now-accepted fixed-context rule. `uv sync --locked` succeeded with CPython 3.12.11. All 36 inspected test/fixture/manifest, frozen contract, prompt, and dependency files remained byte-identical to the repository.

Executed the full suite with `uv run --locked pytest -o addopts="" -q -p no:cacheprovider`, adding `--junitxml=/tmp/astra-wave2-r3.xml` solely to record counts: **640 passed, 0 failed, 2 skipped**.

| Frozen test file | Passed | Failed | Skipped |
|---|---:|---:|---:|
| `tests/test_eval_cli.py` | 7 | 0 | 0 |
| `tests/test_eval_gold.py` | 16 | 0 | 0 |
| `tests/test_eval_score.py` | 13 | 0 | 0 |
| `tests/test_extract_cache.py` | 11 | 0 | 0 |
| `tests/test_extract_chunk.py` | 14 | 0 | 0 |
| `tests/test_extract_cli.py` | 8 | 0 | 0 |
| `tests/test_extract_parse.py` | 35 | 0 | 0 |
| `tests/test_extract_request.py` | 9 | 0 | 0 |
| `tests/test_fetch.py` | 23 | 0 | 0 |
| `tests/test_fetch_recorded.py` | 1 | 0 | 0 |
| `tests/test_ground.py` | 265 | 0 | 2 |
| `tests/test_ingest.py` | 23 | 0 | 0 |
| `tests/test_ingest_toc.py` | 10 | 0 | 0 |
| `tests/test_markers.py` | 17 | 0 | 0 |
| `tests/test_pipeline_regressions.py` | 5 | 0 | 0 |
| `tests/test_schema.py` | 41 | 0 | 0 |
| `tests/test_schema_v2.py` | 9 | 0 | 0 |
| `tests/test_textdoc.py` | 19 | 0 | 0 |
| `tests/test_verify.py` | 96 | 0 | 0 |
| `tests/test_writer.py` | 18 | 0 | 0 |
| **Total** | **640** | **0** | **2** |

**Failure classification:** no test-wrong or impl-wrong frozen-test failures. The two skips are the existing single-character-quote property cases in `test_ground.py`. No test was weakened, edited, or skipped to obtain this result.

Re-executed the round-2 probes against the refreshed implementation:

| Probe | Observed outcome |
|---|---|
| Delivery Date quote proposed as Commencement Date | Event dropped; no event row; dependent visible obligation has null effective due date. |
| `Landlord waives all rent forever.` description | Stored description is the original rent-payment quote. The invented waiver is absent. |
| Swapped DIGITAL/CONSTANT CONTACT roles in the shared preamble | Both false party associations dropped; no incorrect payer resolves. The positive pipeline test still resolves the real tenant. |
| Absolute date plus relative pair | Retains `2011-03-01`, nulls offset and anchor, and writes successfully. The frozen replacement regression also passes. |
| `$5.123` proposed as `5.12` | Amount null in verification and the visible row. |
| `1000 days` proposed as `0` | Offset and anchor null, including with an available named event. |
| Amendment `--no-cache` sample | CLI returns 2, makes zero API calls, and creates neither graph.db nor the sample directory. |

The direct-writer lineage probes still raise `dependents_exist` for replacement of an anchored base and an FK error for an amendment inserted into an empty isolated DB. These are the intended writer safeguards, not frozen-test failures: Rev 2.2 moves recovery to a fresh whole-graph rebuild and prevents unsupported samples at the public CLI boundary.

Also repeated extract CLI -> writer -> eval CLI: two visible obligations, matching run identity, matching prompt version and canonical TextDoc hash, and proposal grounding 1.0. An additional sampled-gold probe explicitly checked the R2-8 F1 detail, which the frozen tests do not assert: all micro/macro/per-type precision and F1 values are null, recall remains 1.0 for that fixture, and lower bounds are micro 0.5 and macro 1.0.

Disposable evidence: `/tmp/astra-wave2-r3.xml`, `/tmp/astra-wave2-r3.txt`, `/tmp/astra_w2_r3_update.py`, and `/tmp/astra_w2_r3_probes.py`. Original-probe outputs are at `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/astra-w2-probes-5v4t9nrq/results.json`; new binding and CLI probes are at `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/astra-w2-r3-probes-6fw7717g/results.json`.

### C) New blockers and should-fixes

**Counts: 2 blockers, 0 should-fixes.** Both were verified by execution through verification, the writer, and the visible view. They are gaps in the prescribed rules despite a fully passing frozen suite, not claims that the implementation suite failed.

1. **R3-1, blocker: Absence of another quoted term does not bind a later date to the event.**

   **Location:** plan, Rev 2.2 R2-2 event-date rule; `tests/test_verify.py` event-binding cases and `tests/test_pipeline_regressions.py`.

   **Problem:** The new rule checks order and intervening curly-quoted terms, but not which statement supplies the date. **Executed:** for `“Commencement Date” means January 1, 2011. Rent is payable March 1, 2011.`, a proposal naming Commencement Date with date `2011-03-01` passes without corrections. Both dates follow the name and neither has another quoted term between it and the name. The event is stored as March 1, and a separate 30-days-after-Commencement obligation gets visible effective due `2011-03-31`, although the definition expressly gives January 1.

   **Concrete fix:** Bind the date using a small supported local definition grammar, such as `“Name” means DATE`, rather than an unbounded interval following a name. Stop at unrelated clauses and leave the date null when the name/date relation is not recognized unambiguously. Preserve the existing supported positives, including the explicitly tested `“Rent Date” each mean DATE` case. Add this two-date negative and its January-1 positive through the effective-due view. A conservative grammar is sufficient for this wave; no general semantic parser is needed.

2. **R3-2, blocker: The first role after a name can belong to the next party.**

   **Location:** plan, Rev 2.2 R2-4 party rule; Task 9 unique-role resolution; `tests/test_verify.py` party-binding cases.

   **Problem:** The 120-character window still treats proximity as an association. **Executed:** `This lease is between Landlord Alpha LLC and Tenant Beta Inc.` validates the false party item `{name: "Alpha LLC", role: "tenant"}` because Tenant is the first role after Alpha LLC. The writer stores Alpha LLC as tenant, and an ordinary Tenant-pays obligation resolves its visible payer to Alpha LLC. No drop or correction occurs. The source clearly binds Landlord to Alpha LLC, so this is a wrong association, not merely lost recall on an unsupported layout.

   **Concrete fix:** Require a recognized local name-role construction, such as `NAME, as ROLE`, `NAME (the ROLE)`, or `ROLE NAME`, with bounded connectors and party boundaries. Unsupported constructions should produce no association instead of scanning forward into the next party. Add both false-tenant and correct-landlord cases for this exact quote, and keep the existing two-party preamble positive tests.

### D) Verdict

proceed-after-fixes

## Round 4

Reviewed `a6015e0` after `git pull -q`, Rev 2.3, and the recorded frozen-test additions. The pre-existing modification to `docs/reviews/dispatch-log.md` was left alone; this worker changes only this review.

### A) Round-3 dispositions

1. **R3-1: resolved for the reported counterexample.** The later rent date no longer becomes the event date, and its dependent obligation stays pending. The defining-date positive still schedules January 31 correctly. New same-sentence counterexamples are reported separately below.
2. **R3-2: resolved for the reported counterexample.** In `Landlord Alpha LLC and Tenant Beta Inc.`, Alpha-as-tenant is rejected and the correct roles resolve Beta as payer. New corporate-name and intervening-party cases are reported separately below.

### B) Full suite and adversarial proof

Refreshed the disposable implementation from the current repository at `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/og-astra-wave2-r4-kq7s8w4x`, updated only its verifier, and used locked CPython 3.12.11 dependencies. All 37 inspected frozen test/fixture/manifest, contract, prompt, and dependency files remained byte-identical to the repository.

Executed `uv run --locked pytest -o addopts="" -q -p no:cacheprovider`, with JUnit output for counts. Final result: **650 passed, 0 failed, 2 skipped**.

| Test file under `tests/` | Passed | Failed | Skipped |
|---|---:|---:|---:|
| `test_eval_cli.py` | 7 | 0 | 0 |
| `test_eval_gold.py` | 16 | 0 | 0 |
| `test_eval_score.py` | 13 | 0 | 0 |
| `test_extract_cache.py` | 11 | 0 | 0 |
| `test_extract_chunk.py` | 14 | 0 | 0 |
| `test_extract_cli.py` | 8 | 0 | 0 |
| `test_extract_parse.py` | 35 | 0 | 0 |
| `test_extract_request.py` | 9 | 0 | 0 |
| `test_fetch.py` | 23 | 0 | 0 |
| `test_fetch_recorded.py` | 1 | 0 | 0 |
| `test_ground.py` | 265 | 0 | 2 |
| `test_ingest.py` | 23 | 0 | 0 |
| `test_ingest_toc.py` | 10 | 0 | 0 |
| `test_markers.py` | 17 | 0 | 0 |
| `test_pipeline_regressions.py` | 5 | 0 | 0 |
| `test_pipeline_regressions_r3.py` | 4 | 0 | 0 |
| `test_schema.py` | 41 | 0 | 0 |
| `test_schema_v2.py` | 9 | 0 | 0 |
| `test_textdoc.py` | 19 | 0 | 0 |
| `test_verify.py` | 102 | 0 | 0 |
| `test_writer.py` | 18 | 0 | 0 |
| **Total** | **650** | **0** | **2** |

**Failure classification:** the initial disposable run had 649 passes, one failure, and two skips. It failed `test_verify.py::test_r2_2_date_not_bound_when_another_quoted_term_intervenes` after I removed the older quoted-term guard while applying Rev 2.3's replacement rule. Classified **impl-wrong against the unchanged frozen test**: the new first-date/same-sentence conditions are necessary conditions and can coexist with the older conservative exclusion. Restoring that guard yielded the final result without editing tests. No remaining failures or demonstrated test-wrong failures. The two skips remain the existing single-character-quote property cases.

**Original R3 probes rerun:** the later unrelated date is nulled with `date_not_bound_to_event`, giving null visible effective due; Alpha-as-tenant in the role-before-name example is dropped with `role_not_bound_to_name`, so no false payer resolves. The amendment sample still exits 2 before any API call or output, and the sampled-gold precision/F1 nulling checks still pass.

**Three adversarial variants per rule, all executed through verify -> writer -> visible view:** date cases each include a separate obligation due 30 days after Commencement Date; party cases include an obligation whose payer is the proposed role.

| Variant | Source and proposal | Observed result |
|---|---|---|
| Date 1: relative definition | `“Commencement Date” means the date that is 30 days after March 1, 2011.` Proposed event date March 1. | **Wrong visible term:** stores event March 1 and effective due March 31. The source makes March 1 the relative definition's input, not Commencement Date itself. |
| Date 2: negation | `“Commencement Date” is not March 1, 2011; it is April 1, 2011.` Proposed March 1. | **Wrong visible term:** stores the explicitly negated date and effective due March 31. |
| Date 3: alternative dates | `“Commencement Date” means the later of January 1, 2011 and March 1, 2011.` Proposed January 1. | **Wrong visible term:** stores the earlier date and effective due January 31. |
| Party 1: earlier conjunction | `Landlord and Tenant designate Alpha LLC as Landlord.` Proposed Alpha as landlord. | **Safe positive:** retains the explicit Alpha-landlord association and resolves Alpha for a Landlord-pays obligation. The earlier `and` does not incorrectly block it. |
| Party 2: role word inside company name | `Landlord Holdings LLC, as Tenant, leases space from Alpha LLC, as Landlord.` Proposed `Holdings LLC` as landlord. | **Wrong visible term:** the `Landlord` token inside the full corporate name is treated as a role prefix; fabricated party `Holdings LLC` becomes the visible payer of a Landlord-pays obligation. |
| Party 3: intervening entity without `and` | `Alpha LLC leases space to Beta Inc., as Tenant.` Proposed Alpha as tenant. | **Wrong visible term:** the unrestricted intervening text meets the 120-character/no-and/no-semicolon rule, so Beta's explicit role is assigned to Alpha, which becomes the visible tenant payer. |

A full-name control for Party 2 correctly stores `Landlord Holdings LLC` as tenant and resolves that full name for a Tenant-pays obligation. The failure is the accepted truncated-name/prefix interpretation, not rejection of all companies containing role words. None of the five unsafe variants emits a correction or drop.

Evidence outside the repository: `/tmp/astra-wave2-r4.xml`, `/tmp/astra-wave2-r4.txt`, initial `/tmp/astra-wave2-r4-literal.xml`, and `/tmp/astra_w2_r4_probes.py`. Adversarial results: `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/astra-w2-r4-probes-rrkytbz_/results.json`. Original R3 probe rerun: `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/astra-w2-r3-probes-b564l42j/results.json`.

### C) New blockers

1. **R4-1, blocker: The first date in the sentence need not be the event's literal date.**

   **Location:** plan, Rev 2.3 R3-1; verifier event-date binding and downstream effective-due calculation.

   **Problem:** The executed relative, negated, and later-of variants above all satisfy the new positional test and create wrong visible deadlines. Sentence locality and date order do not distinguish a literal definition from an input to a relative expression or an expressly rejected date.

   **Concrete fix:** Restrict accepted event dates to a small explicit definition grammar, with the date directly following a supported affirmative connector and with no unconsumed qualifying expression. For this wave, leave relative, negative, conditional, and alternative-date definitions null; do not infer or calculate their event date. Freeze the three variants through the visible view, plus the existing direct-date positives. A direct template such as `“Name” means DATE` is a starting point, not a license to accept arbitrary text between the connector and date or to ignore qualifying text afterward.

2. **R4-2, blocker: Party binding can truncate a corporate name or cross another named party.**

   **Location:** plan, Rev 2.3 R3-2(a)/(b); Task 8 name matching; Task 9 unique-role resolution.

   **Problem:** The executed Party 2 and Party 3 cases create wrong visible payers. Case/space-normalized substring matching cannot establish a complete party-name boundary, and arbitrary text excluding only `and` and `;` still admits a different entity before `as ROLE`.

   **Concrete fix:** Match a complete local party declaration and derive the party name and role together from that declaration. Permit only explicit connectors and supported company-descriptor text, not an arbitrary 120-character gap. Treat conflicting name parses, including a role-like word inside a longer declared company name, as unresolved unless a full declaration disambiguates them. For the counterexample, `Landlord Holdings LLC, as Tenant` must bind the full name to tenant and must not license `Holdings LLC` as landlord. Add both failing cases and retain the earlier-conjunction/full-name positives. Unsupported layouts may lose recall; they must not manufacture an association.

### D) Verdict

proceed-after-fixes

## Round 5

Reviewed the assigned `cf22043` baseline after `git pull -q` and implemented Rev 2.4 in a fresh disposable copy. Main advanced concurrently to `ff7b205` during the review; the proof below is explicitly pinned to the requested `cf22043` contracts and frozen suite, rather than mixing later implementation, prompt-schema, or C1 replay changes into it. Repository code and tests were not edited.

### A) Round-4 dispositions

1. **R4-1: not resolved as a class.** All previously reported relative, negated, alternative-date, and directly qualified examples now fail safely, but the grammar's substring search still admits an explicitly negated declaration or a condition beyond its accepted terminator; see R5-1.
2. **R4-2: not resolved as a class.** The exact conflicting-role and verb-phrase examples are fixed, but word boundaries still admit a corporate-name suffix, and the unrestricted descriptor admits another entity's role; see R5-2 and R5-3.

### B) Full suite and executed probes

Disposable copy: `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/og-astra-wave2-r5-xotony_v`. Updated the verifier to the declaration grammar, retaining the explicitly required quoted-term guard. Bare punctuation before `as ROLE` is accepted as required by the plan's own `Landlord Holdings LLC, as Tenant` example and frozen positives. Checked all 38 test/fixture/manifest, contract, prompt, and dependency files in the copy byte-for-byte against Git objects at `cf22043`; none changed.

`uv sync --locked` succeeded with CPython 3.12.11. The first full run of `uv run --locked pytest -o addopts="" -q -p no:cacheprovider`, with additional JUnit output for counts, returned **665 passed, 0 failed, 2 skipped**.

| Test file under `tests/` | Passed | Failed | Skipped |
|---|---:|---:|---:|
| `test_eval_cli.py` | 7 | 0 | 0 |
| `test_eval_gold.py` | 16 | 0 | 0 |
| `test_eval_score.py` | 13 | 0 | 0 |
| `test_extract_cache.py` | 11 | 0 | 0 |
| `test_extract_chunk.py` | 14 | 0 | 0 |
| `test_extract_cli.py` | 8 | 0 | 0 |
| `test_extract_parse.py` | 35 | 0 | 0 |
| `test_extract_request.py` | 9 | 0 | 0 |
| `test_fetch.py` | 23 | 0 | 0 |
| `test_fetch_recorded.py` | 1 | 0 | 0 |
| `test_ground.py` | 265 | 0 | 2 |
| `test_ingest.py` | 23 | 0 | 0 |
| `test_ingest_toc.py` | 10 | 0 | 0 |
| `test_markers.py` | 17 | 0 | 0 |
| `test_pipeline_regressions.py` | 5 | 0 | 0 |
| `test_pipeline_regressions_r3.py` | 4 | 0 | 0 |
| `test_pipeline_regressions_r4.py` | 5 | 0 | 0 |
| `test_schema.py` | 41 | 0 | 0 |
| `test_schema_v2.py` | 9 | 0 | 0 |
| `test_textdoc.py` | 19 | 0 | 0 |
| `test_verify.py` | 112 | 0 | 0 |
| `test_writer.py` | 18 | 0 | 0 |
| **Total** | **665** | **0** | **2** |

**Failure classification:** no test-wrong or impl-wrong failures. The two skips are the unchanged single-character-quote property cases in `test_ground.py`.

**Prior probes rerun:**

- **R2:** swapped event names and party roles are rejected; waiver descriptions become copied quotes; deadline conflicts keep the absolute date and write; `$5.123` and `1000 days` cannot supply truncated numeric values. Direct writer calls still enforce dependency/FK safeguards as intended.
- **R3:** later unrelated dates and the next party's role do not resolve; amendment samples exit 2 before calls or output; sampled precision and F1 remain null with the lower bounds retained.
- **R4:** relative definitions, internal negation, later-of dates, truncated corporate-name/role conflicts, and cross-entity verb phrases all fail safely. Earlier-conjunction and complete corporate-name positives still work.

**New adversarial attempts under the written grammar:** all were executed through verification, the writer, and a visible view. Each date case includes a separate obligation due 30 days after Commencement Date; each party case includes a Tenant-pays obligation.

| Attempt | Observed visible result |
|---|---|
| Full quote `It is false that “Commencement Date” is March 1, 2011.` | **Wrong:** stores event March 1 and returns scheduled effective due March 31, with no correction. |
| Same source, but model quotes only `“Commencement Date” is March 1, 2011.` | **Wrong:** identical scheduled deadline. Grounding the clipped substring does not recover the governing negation. |
| `“Commencement Date” means March 1, 2011; provided that Landlord first delivers possession.` | **Wrong:** the accepted semicolon terminates the match before the condition, yielding an unconditional scheduled deadline of March 31. |
| `“Commencement Date” means March 1, 2011 unless the premises are unavailable.` | **Safe control:** date null, visible obligation pending, because the qualifier occurs before an accepted terminator. |
| `Silver Cloud Holdings LLC, as Tenant.` with proposed party `Holdings LLC`, role tenant | **Wrong:** `Holdings LLC` appears as tenant in `visible_agreement_party` and as payer in `visible_obligation`. |
| `Alpha LLC, a non-tenant company appointing Beta Inc. as Tenant.` with proposed Alpha as tenant | **Wrong:** Alpha is a visible tenant and payer, despite the explicit non-tenant description and Beta's appointment. |
| `The agreement does not designate Alpha LLC as Tenant.` with proposed Alpha as tenant | **Wrong:** Alpha is a visible tenant and payer; the negative prefix is outside the matched local construction. |
| `XAlpha LLC, as Tenant.` with proposed `Alpha LLC` | **Safe control:** letter adjacency is rejected and payer stays null. |
| `Silver Cloud Holdings LLC, as Tenant.` with the full proposed company name | **Safe positive:** stores and resolves the full company name. |

These are six unsafe executions and three controls, grouped into the three blockers below. No unsafe case required bypassing verification or forging a VerifiedItem.

Evidence: `/tmp/astra-wave2-r5.xml`, `/tmp/astra-wave2-r5.txt`, `/tmp/astra_w2_r5_update.py`, `/tmp/astra_w2_r5_probes.py`, and `/tmp/astra-wave2-r5-new-probes.txt`. The prior-round outputs are `/tmp/astra-wave2-r5-prior-r2.txt`, `/tmp/astra-wave2-r5-prior-r3.txt`, and `/tmp/astra-wave2-r5-prior-r4.txt`. New probe results and databases are at `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/astra-w2-r5-probes-yw66k3up/`.

### C) New blockers

1. **R5-1, blocker: A matching declaration fragment can be governed by negation or a condition outside the match.**

   **Location:** plan, Rev 2.4 event-date `quote contains` rule, accepted terminators, and party declarations at a name occurrence; Task 8 grounding.

   **Problem:** The negative-prefix event and party examples satisfy every local token requirement. The semicolon condition also satisfies the exact permitted terminator. They produce wrong scheduled dates or visible party roles. Matching the entire model quote instead of a substring would not fix the clipped-quote version, because the omitted negation remains in the source segment.

   **Concrete fix:** Validate a complete source declaration in its containing source context, not an arbitrary model-selected substring. Define supported affirmative declaration boundaries and reject unconsumed governing prefixes, conditions, or provisos. Use the full source segment/declaration to detect incomplete quote selection; a semicolon is not sufficient proof that qualification ended. For this wave, leave unsupported contextual declarations unresolved. Freeze both full-quote and clipped-quote negative examples plus the semicolon condition, so tightening only the regex inside the quote cannot make the tests superficially green.

2. **R5-2, blocker: Word boundaries do not establish the beginning of a complete corporate name.**

   **Location:** plan, Rev 2.4 party-name boundary requirement and role-after-name declaration.

   **Problem:** In `Silver Cloud Holdings LLC, as Tenant.`, the suffix `Holdings LLC` has no adjacent letter or digit and is immediately followed by the supported role construction. It therefore passes as written, yet creates a different party name and visible payer. The previous conflict safeguard helps only when the discarded prefix happens to be a conflicting role word.

   **Concrete fix:** Parse the name as a whole field from a supported declaration boundary, then compare the proposed name with that entire captured field. Do not search for any word-delimited suffix of the proposed declaration. Derive stored party names from the complete source field, with no silent alias shortening. Add the suffix-name negative and full-name positive together; punctuation-adjacency tests alone do not cover this failure.

3. **R5-3, blocker: The descriptor slot is still unrestricted prose that can assign a role to another entity.**

   **Location:** plan, Rev 2.4 role-after-name optional `a|an <descriptor>` grammar.

   **Problem:** `non-tenant company appointing Beta Inc.` is under 80 characters and contains none of the prohibited punctuation. It is therefore a legal descriptor under the written grammar, and the following `as Tenant` binds to Alpha rather than Beta. The resulting visible association explicitly contradicts Alpha's non-tenant status. This is the old cross-entity failure through the newly permitted descriptor production, not mere recall loss.

   **Concrete fix:** Replace the arbitrary descriptor character class with a finite set of supported company descriptors, such as a jurisdiction plus `corporation` or `limited liability company`. Reject descriptors containing an unrecognized clause or another entity instead of consuming them up to `as ROLE`. Preserve the existing Delaware-descriptor positives and add this explicit non-tenant counterexample through both visible views.

### D) Verdict

proceed-after-fixes


## Round 6

### A) Round-5 disposition under the stop rule

1. **R5-1: resolved.** The original full-quote negative event, clipped negative event, semicolon condition, and negative party counterexamples all fail safely using the containing source sentence; the `unless` control still fails safely.
2. **R5-2: resolved.** The original `Holdings LLC` suffix claim is dropped, the adjacent-character control remains dropped, and the full `Silver Cloud Holdings LLC` positive still binds. This disposition concerns the specified examples; the real-corpus counterexample below is separately within the stop rule.
3. **R5-3: resolved.** The original `non-tenant company appointing Beta Inc.` descriptor cannot assign Tenant to Alpha. The frozen descriptor positives remain green.

### B) Disposable proof and full suite

Pulled `cdab0ad`. Refreshed the disposable copy at `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/og-astra-wave2-r6-jz2b8hb5`, using the current merged implementations and the disposable verifier/extraction entry point. Updated the verifier to Rev 2.5 source-sentence checks, name-start boundaries, and finite descriptors. All 48 tracked tests, fixtures, prompts, dependency files, and pinned contract/schema files selected for comparison match their `cdab0ad` Git objects byte-for-byte. No repository source or test file was edited.

`uv sync --locked` succeeded with CPython 3.12.11. The final full run of `uv run --locked pytest -o addopts="" -q -p no:cacheprovider`, with additional JUnit output for counts, returned **694 passed, 0 failed, 2 skipped**.

| Test file under `tests/` | Passed | Failed | Skipped |
|---|---:|---:|---:|
| `test_eval_cli.py` | 7 | 0 | 0 |
| `test_eval_gold.py` | 16 | 0 | 0 |
| `test_eval_score.py` | 13 | 0 | 0 |
| `test_extract_cache.py` | 11 | 0 | 0 |
| `test_extract_chunk.py` | 14 | 0 | 0 |
| `test_extract_cli.py` | 8 | 0 | 0 |
| `test_extract_parse.py` | 35 | 0 | 0 |
| `test_extract_replay.py` | 10 | 0 | 0 |
| `test_extract_request.py` | 9 | 0 | 0 |
| `test_fetch.py` | 23 | 0 | 0 |
| `test_fetch_recorded.py` | 1 | 0 | 0 |
| `test_ground.py` | 265 | 0 | 2 |
| `test_ingest.py` | 23 | 0 | 0 |
| `test_ingest_toc.py` | 10 | 0 | 0 |
| `test_markers.py` | 17 | 0 | 0 |
| `test_pipeline_regressions.py` | 5 | 0 | 0 |
| `test_pipeline_regressions_r3.py` | 4 | 0 | 0 |
| `test_pipeline_regressions_r4.py` | 5 | 0 | 0 |
| `test_pipeline_regressions_r5.py` | 6 | 0 | 0 |
| `test_schema.py` | 41 | 0 | 0 |
| `test_schema_v2.py` | 9 | 0 | 0 |
| `test_textdoc.py` | 19 | 0 | 0 |
| `test_verify.py` | 125 | 0 | 0 |
| `test_writer.py` | 18 | 0 | 0 |
| **Total** | **694** | **0** | **2** |

**Failure classification:** the initial run had 692 passes, 2 failures, and 2 skips. Both failures were **impl-wrong**, not test-wrong: `test_verify.py::test_r4_role_word_inside_a_company_name_is_not_a_role_prefix` and `test_pipeline_regressions_r4.py::test_truncated_company_name_never_becomes_the_payer`. Applying the new boundary check before detecting a conflicting suffix role accidentally removed Rev 2.4's conflict safeguard. Keeping that safeguard before narrowing the suffix acceptance fixes both, consistent with Rev 2.5's explicit "can only make the grammar smaller" rule. No test changes were needed. The two final skips are the existing single-character-quote property cases in `test_ground.py`.

Also reran the original six unsafe R5 probes and three controls through verification, the writer, and visible views. All six unsafe cases now fail safely: three event-date claims become null and their dependent deadlines remain pending; three party claims are dropped and their dependent payer stays null. The `unless` and adjacent-character negative controls remain safe; the full-name positive remains a visible tenant and payer.

Evidence: `/tmp/astra-wave2-r6-final.xml`, `/tmp/astra-wave2-r6-final.txt`, `/tmp/astra-wave2-r6-r5-probes.txt`, and `/tmp/astra_w2_r5_probes.py`. The initial failure output is `/tmp/astra-wave2-r6.txt`.

### C) Real-corpus check

Executed the copied Rev 2.5 date/role helper functions **on devbox** through `ssh devbox`, using Python on stdin and `PYTHONDONTWRITEBYTECODE=1`. Read all seven `~/Dev/og-integration/data/text/*.json` files; wrote nothing on the devbox. The scan visited **4,279 source-segment sentences**, using the same sentence boundaries as the disposable verifier. Candidate discovery covered quoted defined terms followed by a supported connector and a later date, and both party-declaration productions.

**Counting unit:** a distinct proposed name/date or name/role binding within a source sentence, not an independently annotated legal declaration. For role-after-name sites, discovery tries the possible name fields at the grammar's allowed boundaries, including internal commas and the optional descriptor boundary; for role-before-name sites, it tries the following field through the first allowed delimiter. This intentionally exposes ambiguous fields and ordinary clauses that the grammar accepts as declarations. Repeated identical candidates within a sentence are deduplicated. These are binding-check counts, not Claude extraction counts, precision, recall, or README performance numbers.

| Filing | Sentences scanned | Event binds | Event rejects | Party binds | Party rejects |
|---|---:|---:|---:|---:|---:|
| `applieddigital-2026-ex101` | 174 | 0 | 0 | 39 | 46 |
| `carbonite-2014-ex1024` | 1711 | 0 | 1 | 153 | 310 |
| `constantcontact-2011-ex1041` | 1412 | 0 | 1 | 152 | 286 |
| `constantcontact-2012-ex101` | 150 | 0 | 0 | 9 | 26 |
| `endurance-2017-ex106` | 70 | 0 | 0 | 5 | 26 |
| `mawson-2025-ex101` | 502 | 0 | 0 | 5 | 11 |
| `terawulf-2025-ex10-1` | 260 | 0 | 0 | 1 | 13 |
| **Total** | **4,279** | **0** | **2** | **364** | **718** |

Overall: **364 candidate bindings accepted, 720 rejected**, across 679 candidate-containing sentences. The two rejected date candidates are Carbonite's `“Early Access Date” shall mean and refer to February 1, 2014.` and Constant Contact 2011's `“Previous Agreement” shall mean and refer to ... dated July 19, 2007 ...` (whitespace normalized here, latter excerpt abbreviated). Neither satisfies the closed connector/date rule. Zero date bindings in this census is not a claim that the filings contain no dates or no events.

The accepted candidates contain wrong bindings on real text. Confirmed the following through `verify -> write_snapshot -> visible_agreement_party`, using the unchanged full Applied Digital TextDoc downloaded read-only, real source/textdoc hashes, and isolated temporary databases. The database setup uses test metadata helpers; the source text, segments, grounding, verifier, schema, writer, and visible view are exercised without modification. No VerifiedParty was forged. These are potential verifier admissions for proposed extraction items, not claims that Claude actually emitted those items.

1. **R6-1, blocker: Internal corporate commas and descriptor boundaries still admit incomplete party fields in the real guaranty.**

   **Location:** plan Rev 2.5 R5-2 and R5-3, role-after-name production; `applieddigital-2026-ex101`, segment `p0005`, characters `[346, 633)`.

   **Real source quote:**

   > THIS UNCONDITIONAL SPRINGING GUARANTY OF PAYMENT AND PERFORMANCE (this “Guaranty”) is made as of March 30, 2026 by COREWEAVE, INC., a Delaware corporation (“Guarantor”), to APLD ELN-02 LLC, a Delaware limited liability company (“Landlord”), and is acknowledged and agreed to by Landlord.

   **Problem and execution:** proposed party `INC.` with role `guarantor` produces visible row `("INC.", "guarantor")`, with no drop. Proposed `a Delaware corporation` likewise becomes a visible guarantor. These are a corporate suffix and a descriptor, respectively, not the declared entity `COREWEAVE, INC.`. Both begin immediately after a comma, and both satisfy the remaining written grammar. Correct full-name controls `COREWEAVE, INC.` / guarantor and `APLD ELN-02 LLC` / landlord also remain visible.

   **Concrete fix:** For this supported declaration form, parse the entire entity field from its introducing boundary, consuming the corporate suffix comma as part of the name and the finite descriptor as a separate field. Compare the claimed name with that complete parsed name; neither an internal comma nor the start of a descriptor may independently restart the field. Conservatively reject ambiguous fields. Freeze these two exact corpus negatives together with the two complete-name controls.

2. **R6-2, blocker: The role-before-name production treats an ordinary operative clause as a party declaration in the real guaranty.**

   **Location:** plan Rev 2.4 party production (a), retained by Rev 2.5; `applieddigital-2026-ex101`, segment `p0032`, sentence starting at character `19216`.

   **Real source quote:**

   > Guarantor hereby consents, prospectively, to Landlord’s taking or entering into any or all of the foregoing actions or omissions.

   **Problem and execution:** proposed party `hereby consents` with role `guarantor` passes verification and produces visible row `("hereby consents", "guarantor")`, with no drop. The role precedes the proposed name at quote start, the comma is an allowed field terminator, and the full source sentence contains no listed governing word. The words describe an action, not a named guarantor. The scan's large accepted count includes this class of ordinary role-subject sentences; it cannot be interpreted as 364 correct declarations.

   **Concrete fix:** Restrict production (a) to a supported entity-name field rather than arbitrary text up to a delimiter. For this wave, accept a complete corporate-name form actually supported by the corpus, or disable the ambiguous role-before-name form and leave its unsupported parties unresolved. Add this exact source sentence as a negative through the visible view and retain existing full corporate-name positives. Rejecting additional unsupported names is permissible lost recall under the stop rule.

These are **two real-corpus blockers**, not new synthetic phrasings. No wrong event-date binding was observed in the enumerated corpus candidates. The quote-existence invariant still holds for the wrong party rows; the failure is the semantic identity assigned to a quoted substring.

Corpus evidence: `/tmp/astra_r6_corpus_scan.py` and `/tmp/astra-r6-corpus-scan.json` contain the executed scanner, per-file SHA-256 values, and every candidate with source sentence and decision. The Applied Digital JSON SHA-256 is `f1285c90592014b7b5c7734de703527f5185e9acfd93098484da769fb9e631ec`. End-to-end witnesses are in `/tmp/astra_r6_real_probe.py`, `/tmp/astra-r6-real-probe.txt`, and `/var/folders/b3/sgt3znvd3fs663smcfz_2y_c0000gn/T/astra-r6-real-corpus-8m7obh9_/`.

### D) Known limitations (not blockers)

No new purely synthetic adversarial phrasings were introduced in this round. Unsupported declaration layouts, source-sentence segmentation heuristics, and conservative rejection from unrelated governing words may lose recall and are not blockers. Preserve the agreed ADR-008/README disclosure: date/role binding is a conservative heuristic over a closed grammar; semantic correctness is measured by eval, not proven, while quote-existence remains deterministically enforced. This final review requests only the two demonstrated real-corpus corrections above, not another open-ended synthetic review cycle.

### E) Verdict

proceed-after-fixes
