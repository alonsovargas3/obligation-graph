# Wave 3 advisor review, round 1

Reviewed plan rev 1 at `74aed92`, the relevant CLAUDE.md requirements, ADR-003/005/008, wave2-report.md, and the merged grounding, verification, extraction, store, and evaluation interfaces. Read the three TextDocs and queried schema-v2 `graph.db` on devbox in SQLite read-only mode. No API calls, source/test edits, commits, or remote writes were made.

**Findings: 6 blockers, 6 should-fixes, 0 nits.** The demo is plausible as a cited clause-level report. The proposed obligation-edge rule does not currently have a demonstrated legitimate edge on this corpus.

## Findings

1. **W3-1 | blocker | Grounding an old quote does not establish that it is the amendment's target.**

   **Location:** plan Review Focus 1; Task 17 old-side and conflict rules; Task 18 edge creation.

   **Problem:** The plan explicitly allows a base-lease quote to pass verification for a deletion that names missing 2A, leaving evaluation to detect the mismatch. That publishes an incorrectly scoped relationship. A grounded conflict pair similarly need not be a conflict at all. The incomplete chain also prevents a general claim that the base plus 1A is the operative agreement immediately before 3A.

   **Concrete counterexample:** 3A `p0013` states `Section 2.C of 2A is hereby deleted in its entirety and of no further force or effect.` A proposed supersession can cite any grounded base clause as its old side and satisfy all written verification rules. The new and old quotes exist, but the base clause is not Section 2.C of 2A. The preamble also names an OS Rider absent from these three inputs.

   **Proposed fix:** Freeze document aliases and target resolution for this chain: Original Lease/base, 1A/first amendment, and unresolved 2A/OS Rider. An explicit target must agree with the old-side document and clause, or remain unresolved with `old=None` and the copied target label. Never substitute a base clause for an absent target. Distinguish supported supersession assertions from model-proposed potential conflicts; conflicts need an identified common subject and must disclose the incomplete chain. Unresolved targets cannot produce obligation edges or lifecycle changes. The exact 3A deletion is a mandatory negative for a base old side and a positive for an unresolved target.

2. **W3-2 | blocker | A self-restated old side can supersede the very same obligation.**

   **Location:** Task 17 `old_doc="self"`; Task 18 overlap rule; schema-v3 `supersedes` and lifecycle view.

   **Problem:** `self` is permitted for all kinds, and neither the edge rule nor the listed schema changes excludes identical endpoints or requires an older document. A cue plus unique overlap is insufficient evidence that the overlapping obligation itself has been replaced.

   **Concrete counterexample, verified by executing the plan's overlap predicate:** 3A `p0012` contains `deemed to refer to` and overlaps exactly one current visible obligation, **519**, type `delivery`. Use that paragraph for both new and old spans with `kind="supersedes"`, `old_doc="self"`, and null values. Both quotes ground; both overlap sets are `{519}`. The written rule produces `519 -> 519`, making the newly stated surrender obligation superseded. This uses actual stored rows, not invented obligations.

   **Proposed fix:** Keep self-restated evidence available for date comparisons and clause-level reporting, but prohibit it from producing obligation supersession edges. Require distinct endpoint IDs, new agreement equal to the change order, old agreement strictly earlier in the verified chain, and a resolved clause target. Enforce these conditions in the writer and in the edge/lifecycle visibility predicates, with a DB CHECK for distinct endpoints. Freeze the real `p0012` self-edge negative. Apply identical edge eligibility in `visible_supersedes` and the inlined lifecycle condition.

3. **W3-3 | blocker | Date and money token membership does not bind the compared values to the changed term.**

   **Location:** Task 17 shifted-date and price-change rules; RawFinding/Finding fields; Task 19 ChangeReport.

   **Problem:** Values can be real tokens yet have the wrong old/new role, suite, period, or basis. The proposed contract has no evidence for the subject of a comparison. Bare table-cell quotes also cannot contain a meaningful target label when `old_doc=None`, although that is the natural representation of added prices.

   **Concrete counterexamples:** 3A `p0011` contains three dates: June 30, 2018, July 1, 2018, and June 30, 2020. Executing the existing `_find_dates` confirms all three. A self comparison with old `2020-06-30`, new `2018-06-30` passes the written tests and reports **-731 days**, reversing the actual extension. For money, base `p0454` labels Suite 1.5 and `p0455` quotes `$33,428.11 per month`; 1A renames that suite to 405. 3A `p0018` quotes `$35,596.80/month` for Suite 409. Both tokens pass `_money_candidates`, yet their subtraction, $2,168.69, is not a supported price change for one suite. The new amount, period, and Suite 409 heading are separate segments (`p0018`, `p0017`, `p0014`).

   **Proposed fix:** Add grounded context references or a narrowly bounded source-context rule that identifies the changed subject and schedule row. Pin the actual 3A surrender pattern: old scheduled surrender versus new expiry, rejecting reversed and commencement-date pairings. Compare prices only for the same identified subject and compatible units; when the prior rate is unavailable in 2A, retain a cited added schedule value with no fabricated old rate or delta. Permit the row's context citation to supply its target and period without fabricating a multi-segment verbatim quote. Freeze these real examples before implementation.

4. **W3-4 | blocker | Snapshot IDs alone do not prove the diff used the text behind the current graph.**

   **Location:** ChainDoc, `change_run_chain`, Task 18 writer/invalidation, Task 19 chain loading, schema-v3 visible views.

   **Problem:** The CLI only requires a current extraction run, while the writer receives no TextDocs or explicit verified snapshot bundle. A TextDoc can change after ingest without re-extraction, or an extraction can replace the graph between check and write. Matching the IDs that the caller supplies is not enough. The view's universal test is also vacuously true if required chain rows are missing. Citation ownership during deletion is unspecified.

   **Concrete counterexample:** Re-ingest the base, leaving extraction run 2 and its 166 obligations in the DB, then run a change check over the new TextDoc. New offsets can be grounded against the new text while edge overlap is evaluated against old obligation offsets. Merely recording run 2 makes the proposed stale-run view pass. A missing base row in `change_run_chain` likewise leaves no mismatching row for that view to reject.

   **Proposed fix:** Freeze a complete, nonempty chain snapshot contract containing ordered document IDs/roles, source pins, canonical TextDoc hashes, and extraction-run identities, including the change order. Verify each TextDoc hash against its extraction run before calls. Inside `BEGIN IMMEDIATE`, recheck the same vector and every copied span before setting `grounded=1`; reject changed snapshots while preserving the previous run. Require complete membership, not only consistency of rows that happen to exist. Delete dependent change edges, decisions, findings and exclusively run-owned references before extraction refs/obligations/runs; do not delete shared extraction evidence. Preserve wave 2's separate cross-document event-dependency guard or use its documented whole-graph rebuild path. There are currently no cross-document event dependencies in this graph, so that guard does not block the requested corpus invalidation test.

5. **W3-5 | blocker | The skip predicate does not enforce the pre-registered experiment or catch failures at the cascade boundary.**

   **Location:** Task 15 `run_cascade`; `OG_GATE_SAMPLES`; Task 19 completeness decision.

   **Problem:** The listed predicate accepts an empty sample tuple with externally supplied `answer=False, confidence=1.0`, because `all(...)` is true for an empty sequence. It also accepts one unanimous sample when `OG_GATE_SAMPLES=1`, despite the pre-registered 3/3 rule. Rules/backend exceptions escaping `decide`, malformed decisions, and an empty/missing question set do not have pinned handling. `all(needed checks ok)` can incorrectly describe an empty or incomplete question inventory as complete.

   **Concrete counterexample, executed:** the exact written expression returns `run_check=False` for both `samples=()` and `samples=(False,)` with false answer, confidence 1, and no error. This violates the stipulated three-sample skip rule without a model disagreement being needed.

   **Proposed fix:** Validate exactly six unique expected categories and the frozen gate policy. For the scored run, permit a skip only for exactly three literal Boolean false samples, no error, and a valid classifier decision; validate environment overrides before network calls. Catch failures from either tier at the cascade boundary, log a short error code, and run the check. Completeness must account for every category as either a valid skip or an ok check. Test missing categories, duplicate categories, zero/one samples, thrown rules/backend exceptions, and malformed decision objects as well as the timeout case.

6. **W3-6 | blocker | The stated API cap is not enforceable by the proposed accounting and call interfaces.**

   **Location:** Global Constraints cost/budget; Checker and HaikuGate constructors; C0/C7; Budget table; wave-2 client failure handling.

   **Problem:** `OG_BUDGET_USD` is per CLI invocation, yet the same $1.10 is described as shared across C0 and C7. There is no shared per-call budget contract for the classifier's internal sample loop and the checker. Reusing extraction's parse/failure approach also loses usage on refused or truncated responses, a known wave-2 limitation. Unknown fallback prices cannot safely be counted as zero. Checking only after a whole gate or run allows additional calls after exhaustion.

   **Concrete counterexample:** C0 spends money, C7 starts again with $1.10, and one check consumes output tokens before `max_tokens` is returned. The current extraction pattern returns an empty attempts list for that response. The subsequent gate/check can still appear funded. Even without that bug, one last 8192-token output alone can add about $0.082 after a near-cap request is admitted, before considering input or fallback.

   **Proposed fix:** Use one shared budget controller at every actual client call, including each gate sample, with usage captured before parsing or status rejection. The coordinator deducts C0 spend from C7's remaining allowance; a durable accounting framework is unnecessary for these two steps. Unknown cost stops further calls with an incomplete outcome. Define whether the number is a hard reservation cap or a soft stop with bounded overshoot; do not advertise a hard $1.10 cap with post-call checks alone. Preflight the remaining check budget, make failure stops sticky across documents/modes, preserve old snapshots, and record failed-call usage. Cost arithmetic and feasible reductions are below.

7. **W3-7 | should-fix | Paired runs and cached latency need a stronger identity than change-order ID.**

   **Location:** Task 16 cache key; Task 19 `--no-cache`, `both`, report loading; Task 20 comparisons; `change_run` schema.

   **Problem:** The gated-subset claim depends on reusing the exact ungated outcomes, not merely making the same request later. `--no-cache`, missing/corrupt cache entries, different question definitions, or replacing only one mode breaks that pairing. The named cache key does not explicitly hash the category question definition. A gated report's new-obligation list also depends on edges from the ungated run, so replacing that run can change the gated report without changing its row. Cache replay wall time is not an observed live gated-check latency.

   **Concrete counterexample:** Run `--mode both --no-cache`; a normal interpretation sends the needed gated checks again and can get different findings, invalidating Review Focus 6. Or overwrite the ungated snapshot after a prompt change and score it against an older gated row. Equal change-order IDs do not make this a comparison.

   **Proposed fix:** Pin a paired evaluation ID and full request fingerprints, question/policy versions, chain snapshot vector, and baseline run identity. In `both`, replay the same in-memory or persisted successful outcomes even when the initial calls bypass the cache. Fingerprint the complete effective request, including category definition. Refuse scoring unmatched pairs and invalidate or explicitly detach the dependent gated report when its baseline changes. Report actual incremental spend and replay wall time separately from counterfactual recorded check cost and summed original latencies; include gate overhead and disclose this is a replay comparison, not two independently timed live pipelines.

8. **W3-8 | should-fix | The gate metrics are useful conditional measurements, not a semantic safety certificate.**

   **Location:** Global Constraints headline metric; Task 20 scorer; C6 labels; C8 demo; ADR-003 update.

   **Problem:** `positive = ungated kept >= 1 finding` is sound for asking whether gating suppresses that fixed baseline's output, provided the baseline completed. It is not ground truth for whether the amendment touches the category. An empty check can miss a true change or have every proposal dropped. Under the proposed cascade, Haiku is only observed on rules misses; an all-12 Haiku recall cannot be inferred from those samples. Twelve labels from two related amendments are not twelve independent contracts.

   **Concrete counterexample:** If 1A's service-level replacement is missed or dropped by the ungated check, a classifier skip is called `skips_confirmed_safe` despite a positive gold SLA label at `p0037`. With the proposed lexicons below, Haiku is likely called only on three negative categories, yielding no positive denominator for its standalone recall. Reporting 100% there would be misleading.

   **Proposed fix:** Keep baseline-relative category recall and also report finding-retention recall, reference-label recall, and all disagreements. Require a complete paired baseline for any skip confirmation. Name zero-baseline skips explicitly; reserve stronger confirmed-safe wording for skips also negative in the adjudicated reference set. For Haiku, report only its observed subset and coverage, with null recall when it has no positives, or deliberately fund a separate all-question baseline. Define one-sided versus two-sided Clopper-Pearson and its denominator as positive category cases, not repeated classifier samples; show miss counts and label the binomial assumption. For example, zero misses in 9 positive cases still gives a one-sided 95% upper miss bound of about 28.3%. Disclose two related documents, model-drafted/adjudicated labels, user spot-checking, and no held-out calibration. ADR-003's existing calibration wording must be superseded explicitly by the pre-registered policy.

9. **W3-9 | should-fix | The finding matcher can credit the wrong target, and its storage representation is underspecified.**

   **Location:** Task 20 reference format/matching; Finding and schema-v3 `change_finding`; Task 17 deduplication.

   **Problem:** Any overlap is enough, and `target_label` is not compared. Two unresolved targets with the same kind and overlapping amendment span match even if their labels differ. `old_doc="self"` is represented in gold but not preserved as that sentinel in Finding/SQL, so workers need a canonical rule. A schema-complete full-agreement reference also needs an explicit enumeration unit to avoid counting one broad paragraph as either one finding or several at convenience.

   **Concrete counterexample:** 1A `p0012` renames four suites in one paragraph. A broad supersession quote with one incorrect copied target can overlap the intended reference, and a small shared fragment can earn equal localization credit. 3A's unresolved 2A deletion can match an incorrect substring target because both old sides are None.

   **Proposed fix:** Pre-register the finding unit, kind/category ownership, minimum localization criterion, and normalized target identity for unresolved targets. Normalize `self` to the change-order document ID consistently or store explicit old-side origin; never infer it differently in the loader and scorer. Retain maximum-cardinality matching, but provide change-specific candidate edges rather than silently reusing wave 2's type/IoU adapter. Report old/new value, delta, target and currency accuracy separately, with coverage. Define cross-category deduplication for the combined report while retaining category provenance for gate evaluation. Freeze the full reference set before scored output and do not loosen these rules to obtain the demo.

10. **W3-10 | should-fix | B3 must pin real-text lexicons, signature boundaries, and section-type mapping.**

    **Location:** Task 14, GateContext, `gate_questions_v1.yaml`, and the 1A section-reference test.

    **Problem:** These details determine both which checks run and whether the expected rules tests are satisfiable. Signature exclusion cannot mean everything after the first signature marker: 1A's installation and SLA exhibits follow its signatures. The real section-type mapping is not the likely intuitive one. Flattened section numbers can also collide with exhibit numbering.

    **Concrete counterexamples:** 1A `p0035` references `Section 8.3.1 and 9.1.1 of the Lease`. The stored base obligations in 8.3.1 are **107 and 108, both `other`**; 9.1.1 contains **113 `other` and 114 `notice`**. A test expecting an 8.3.1 SLA hit with `section_types={sla}` cannot pass honestly. The SLA text at `p0105` through `p0113` occurs after the signature block. The scope phrase `Section 2.C of 2A` must never resolve to a base section.

    **Proposed fix:** Freeze the lexicons and category-to-obligation-type mappings below, including explicit defined-term entries such as ECT and their categories. For the 8.3.1 test, expect its actual type or enrich the context with a grounded base-section lexical classification; do not relabel extraction rows. Define precise signature-block end/resumption at exhibits, whitespace handling, prefix-wildcard boundaries, and all-hit evidence deduplication. Union ambiguous duplicate section-number types conservatively or retain qualified section identity, rather than overwriting dictionary entries. Keep reference classification conservative and distinguish it from the stricter target resolver used for findings.

11. **W3-11 | should-fix | Define demo supersession as a clause-level finding; do not force an obligation edge.**

    **Location:** Task 18 edge rule; Task 19 report; C8; CLAUDE.md Definition of done.

    **Problem:** Current extraction coverage does not align with amendment replacement clauses. An overlap rule can find a numerical candidate without finding a legitimate replacement obligation. Conversely, genuine deleted provisions can have no new obligation at all. A demo criterion based on edge count would incentivize incorrect lifecycle updates.

    **Concrete evidence, executed against the real graph:** base has **166** visible obligations, 1A **5**, and 3A **7**. In 1A, cue-bearing segments `p0012`, `p0017`, `p0018`, `p0019`, and `p0037` each overlap **zero** visible obligations. In 3A, cue-bearing `p0011`, `p0013`, and `p0023` also overlap zero; only `p0012` overlaps delivery 519 and `p0014` overlaps payment 520. Their old surrender/rent provisions refer to missing 2A. Thus there is no demonstrated correctly targeted, older-document edge supported by this snapshot. The literal rule can nevertheless make invalid edges, including W3-2.

    **Proposed fix:** Explicitly count a grounded clause-level replacement/deletion with an unresolved target as a demo supersession, displaying the missing old document honestly. 3A `p0013`, or 1A's Exhibit A replacement at `p0017`, supplies a credible example. Keep zero obligation edges if none qualify. The real 3A June 2018 to June 2020 extension supplies the shifted-date example after W3-3. A safe skip remains contingent on actual baseline and reference results; do not force it. Clarify that `new_obligations` currently means visible amendment obligations without a resolved supersession edge, not proof they are legally novel. Do not retrospectively mark obligations superseded merely to satisfy the walkthrough.

12. **W3-12 | should-fix | Freeze the remaining cross-task interfaces and schema-transition tests before parallel dispatch.**

    **Location:** Contract files, B3, Tasks 14-20, execution topology, existing schema tests.

    **Problem:** Parallel workers still have to invent the shape of `run`, `chain_runs`, report dictionaries, log records, budget integration, gate-context construction, and deletion ownership. Task 20 modifies the eval subcommand but does not explicitly list `src/og/eval/__main__.py` in file ownership. Schema v3 invalidates existing frozen tests as well as adding new ones. Requiring the entire newly red suite to pass in every isolated wave-3A worktree is impossible until the other implementations exist.

    **Concrete counterexamples:** `tests/test_schema_v2.py` explicitly expects `user_version == 2`; `tests/test_schema.py` inserts supersedes rows without the newly mandatory `change_run_id`. These need coordinator-authored changes. Task 18 cannot infer span revalidation and run ownership from an untyped `run` argument, while Task 20 cannot safely pair runs from a log format invented later by Task 19. An unchanged cached response after a question-definition edit is also an interface-level bug, not something each worker should resolve independently.

    **Proposed fix:** B3 should freeze typed run/snapshot/log/report contracts, canonical hashes and provenance, category/skip policy, budget hooks, evidence ownership, exception/drop enums, and exact function signatures. Explicitly assign context/chain building to Task 19, `og.eval.__main__` to Task 20, and all schema/test adaptations to the coordinator before regenerating the freeze manifest. Define per-task red/green checks plus unaffected wave-1/2 regressions; require the full suite at the integrated checkpoint. Task 19 follows 14-18; C7/C8 also wait for Task 20 and the frozen reference set. Record base SHAs, check freeze hashes at dispatch/mid-flight/return, and give a Grok fallback the same frozen scope and failing-test evidence. No worker should repair a contract or weaken a test to reconcile these gaps.

## Corpus walkthrough and proposed RulesGate lexicons

These are conservative run-check triggers, not assertions that each mentioned category changed. Freeze them before C6/C7; do not remove false-positive terms merely to obtain skips. Match whole words, with the plan's trailing prefix wildcard. Use `fee` and `fees`, not `fee*`, which also matches the corpus's `feet`.

| Category | Proposed lexicon | Suggested section types |
|---|---|---|
| price | `rent`, `fee`, `fees`, `escalat*`, `cap`, `caps`, `commission*`, `cost*` | payment, penalty |
| dates | `date*`, `commenc*`, `expir*`, `surrender*`, `extend*`, `extension*`, `deliver*`, `milestone*`, `notice period*` | delivery, notice |
| termination | `terminat*`, `cure*`, `default*`, `surrender*` | termination_right, penalty, notice |
| guarantee | `guarant*`, `backstop`, `credit support`, `letter of credit`, `surety`, `collateral` | guarantee |
| sla | `uptime`, `power`, `cool*`, `service level*`, `service credit*`, `electric*`, `HVAC`, `battery`, `ECT*`, `generator*` | sla |
| parties_or_sites | `assign*`, `premises`, `site*`, `suite*`, `capacity`, `pathway*`, `address*` | delivery, other, conservatively |

Executing these lexical checks over all amendment segments, excluding only 1A `p0060`-`p0084` and 3A `p0042` onward, gives:

| Check | 1A | 3A |
|---|---|---|
| price | Run: rent schedule `p0039`-`p0050` | Run: rent `p0014`-`p0022` |
| dates | Run: expansion date and installation deadline | Run: extended surrender and term dates |
| termination | Run conservatively: default/estoppel and surrender mentions | Run: surrender/extension-option text and default/estoppel |
| guarantee | No rules hit; classifier may permit skip | No rules hit; classifier may permit skip |
| sla | Run: Service Levels `p0037` plus ECT/power/HVAC exhibit | No rules hit; classifier may permit skip |
| parties_or_sites | Run: renumbered/expanded suites | Run conservatively: suites and notice-address change |

Only **1A guarantee, 3A guarantee, and 3A SLA** are eligible for a cascade skip with this configuration. Three unanimous negatives would give at most three skips out of twelve checks, not six or twelve. Ordinary broker indemnities are not automatically guarantor/backstop/credit-support changes: the extractor labels 3A's broker indemnity as `guarantee` (obligation 524), which is a warning against substituting extraction types for the gate reference labels. Every eligible skip still needs the actual classifier and complete ungated run; none is promised by this review. The 8.3.1 `other` mapping can conservatively trigger parties/sites, but cannot be presented as evidence of an SLA obligation there.

## Budget and scope assessment

The cost estimate is plausible only with small outputs and useful prompt-cache hits; it is not a worst-case bound. The exact rendered segment strings, before system/schema overhead, contain **225,205 characters for the base**, **16,582 for 1A**, and **10,509 for 3A**. At an explicitly approximate four characters per token, the two requests carry about **60,447** and **63,074** input tokens. One full-prefix cache write per amendment plus five reads each costs about **$0.432** using the plan's stated rates, before output, system overhead, gate calls, retries or fallback. Reuse of the base prefix across amendment requests can reduce that; changed block layout or expiry can increase it. These are scenarios, not token measurements.

Twelve full 8192-token outputs add **$0.983** by themselves. Around 2,000 output tokens per check adds **$0.24**, putting the two-cold-prefix scenario near $0.67 before gates. The real wave-2 amendment extractions used 2,330 output tokens for 1A across two chunks and 2,015 for 3A in one chunk; that is context for uncertainty, not a forecast for six focused high-effort checks. The table's $0.45 check estimate leaves little output allowance under the two-cold-prefix scenario. Budget for thinking/fallback usage as actually recorded, not just JSON length.

With the lexical coverage above, the cascade needs at most **9 Haiku samples**, versus the table's 36. Thirty-six is appropriate only for a separately measured all-question Haiku baseline or a worst-case all-miss cascade. Choose explicitly between those experiments. Preserve the shared base as its own stable cached block if possible, estimate/measure input tokens at C0, reserve headroom, and lower output caps/effort deliberately if needed before the scored experiment. Do not spend the remaining credit chasing a promised skip or repairing missing 2A context with model guesses.

For this portfolio scope, keep Jev as the existing unavailable protocol slot, avoid general amendment algebra or learned calibration, and allow clause-level reports without automatic edges. The useful minimum remains twelve complete baseline checks, a paired gated replay, twelve honestly disclosed category labels, and a small cited findings reference. The stricter source/snapshot checks above protect that minimum rather than expanding product scope.

## Verification evidence

Read-only corpus/DB export: `/tmp/astra_w3_read_corpus.py` and `/tmp/astra-w3-corpus.json`. Executed cue/obligation overlap inventory, lexical walkthrough, date-token enumeration and rendered-size checks: `/tmp/astra_w3_probes.py` and `/tmp/astra-w3-probes.txt`. Empty/one-sample skip truth table and budget arithmetic were also executed with Python. No wave-3 implementation or frozen test suite exists yet, so these are checks of the written predicates and actual inputs, not claims that implemented wave-3 tests passed. Respect the pre-registered three-round limit; later blockers should be confined to these real inputs or missed CLAUDE.md requirements.

## Verdict

proceed-after-fixes

## Round 2

Reviewed rev 2 at `2dc61e3`. Refetched the three TextDocs and queried `graph.db` read-only on devbox; the documents are unchanged from round 1 and the graph still has 166 base, 5 first-amendment, and 7 third-amendment visible obligations. The following dispositions assess the written contract, not an implemented wave-3 test suite. No live API calls were made.

### A) Round-1 dispositions

1. **W3-1: partially.** The explicit missing-2A case now fails safely, but document-only targets still permit an unrelated old clause, and the closed target production does not recognize the real Basic Lease Information reference; see R2-1.
2. **W3-2: resolved.** Self origin, equal endpoints, and an old document that is not earlier all prevent an edge; the real 519 self-edge is rejected.
3. **W3-3: partially.** The original reversed date, isolated commencement date, and cross-suite price delta are rejected, but a clipped quote from the same real paragraph defeats the shared-role test; see R2-2.
4. **W3-4: resolved.** The complete snapshot vector, TextDoc hash checks, transactional recheck, span recheck, cardinality requirement, and owned-reference deletion address the stated staleness paths.
5. **W3-5: resolved.** The fixed three-literal-false policy, six-category validation, boundary exception handling, and completeness inventory close the stated fail-open gaps.
6. **W3-6: partially.** Shared per-call budgeting, C0 subtraction, sticky stops, and usage-before-parse are specified; the reservation formula still underprices its own token estimate for a cache write and is not a hard bound; see R2-3.
7. **W3-7: resolved.** Pair IDs, full effective-request fingerprints, in-memory replay even with no-cache, baseline invalidation, and separated timing/cost bases address the comparison problem.
8. **W3-8: resolved.** Baseline-relative and reference metrics, disagreements, reference-confirmed skips, observed-subset Haiku reporting, and the specified interval/disclosures address the measurement claims.
9. **W3-9: resolved.** A declared clause-target unit, explicit old origin, segment-based matching, unresolved-label equality, separate field accuracy, and category-preserving deduplication now define the metric.
10. **W3-10: resolved.** Lexicons, actual section-type mappings, signature resumption at exhibits, literal prefix behavior, and union of duplicate section types are pinned.
11. **W3-11: resolved.** A clause-level supersession meets the demo criterion, zero obligation edges is acceptable, and new obligations are labeled according to the actual graph operation.
12. **W3-12: resolved.** B3 contract ownership, schema-test adaptation, per-task versus integration acceptance, and the required merge/reference dependencies are specified.

**Disposition count: 9 resolved, 3 partially resolved, 0 unresolved.**

### B) Executed rev-2 probes

Used disposable Python scripts outside the repository to apply the rev-2 predicates to the actual source slices and exported visible obligations. Target parsing allows the natural quoted and dotted/alphanumeric forms of `<id>`; it does not silently add the missing multiword Basic Lease Information production. The existing production `ground()` independently accepts the old/new source quotes used in the target and clipped-date counterexamples. These are rule-satisfiability probes, not claims that a future wave-3 writer has already stored these results.

**Target resolution:**

| Source | Rev-2 recognized target | Result |
|---|---|---|
| 3A `p0013` | `Section 2.C of 2A` | Alias unresolved. `old=None`, origin unresolved is the supported result; a base old side is rejected with `target_not_in_corpus`. |
| 1A `p0017` | `Exhibit “A” to the Lease` | Resolves to the base document only. An unrelated grounded base rent quote still satisfies that scope restriction. |
| 1A `p0019` | No match | `Item 7 of the Basic Lease Information to the Lease` contains an intermediate qualifier the closed pattern does not allow. |
| 1A `p0037` | `Table A of Exhibit “F” to the Original Lease` | The nested Exhibit production matches and resolves to the base document only. The same unrelated rent quote is still admitted as an old side by the written scope rule. |

The unrelated old quote in both document-only probes is base `p0455`, whose source says `$33,428.11 per month for the period commencing on the Commencement Date and expiring on the last day of the twelfth (12th) full calendar month of the Term of the Lease.` Its grounded offsets are `[48490, 48658)`. It is a rent provision, not Exhibit A or Table A of Exhibit F. The corresponding amendment quotes also ground exactly at `[2963, 3076)` and `[6660, 7020)`.

**Self-edge:** 3A `p0012` still overlaps exactly obligation 519. With the proposed identical old/new spans and `old_origin=self`, rev 2 rejects the edge: origin is not chain, the old document is not earlier, and the endpoints are identical. A self-restated clause-level finding need not make that obligation superseded. None of the real cue/overlap inventory supplies a new justification for a legitimate edge; zero remains the honest demo expectation.

**Dates in 3A `p0011`:** for the following table, the old positive quote is the exact source substring `Currently, the portion of the Premises located in Suite 409 of the Building is scheduled to be surrendered to Landlord on June 30, 2018`.

| Pair/quote selection | Rev-2 result |
|---|---|
| Old positive quote; new `expiring June 30, 2020` | Accept: shared END role, prior-state cue present, exactly one date in each quote, delta **+731 days**. |
| Reversed old/new quotes | Reject: the old 2020 expiry quote lacks a prior-state cue. |
| Old positive quote; new `commencing July 1, 2018` | Reject: END versus START. |
| Whole paragraph for either side | Reject: the paragraph contains three date tokens. The intended positive therefore needs narrower copied quotes. |
| Old positive quote; new `commencing July 1, 2018 and expiring` | **Wrong acceptance:** the new quote has one date and both START and END words. The shared END class admits **+1 day** as a surrender-date shift. |

The last quote is an unchanged contiguous substring of real 3A, not a newly invented phrasing. `ground()` accepts it at `[2747, 2783)`. The following source date, June 30, 2020, has been omitted from that quote while its governing word `expiring` remains.

**Prices:** the existing money parser finds `33428.11` in base `p0455` and `35596.80` in 3A `p0018`. Rev 2 rejects the cross-document pair because any non-null old value is prohibited. The new `35596.80` amount with null old value/delta and a same-document context quote from `p0017` is permitted. The previous target-label requirement no longer obstructs this added/restated price. This is a stated new amount with context, not evidence of a $2,168.69 increase.

**Rules walkthrough:** rev 2 excludes exactly 1A `p0062`-`p0084` and 3A `p0043`-`p0057`. It retains the signature-page announcement before each block, and resumes at 1A `p0085` so the installation and SLA exhibits remain in scope. Applying the frozen lexicons gives these counts of distinct segments with at least one lexical hit:

| Category | 1A hit segments | 3A hit segments | Consequence |
|---|---:|---:|---|
| price | 5 | 3 | Both checks run. |
| dates | 17 | 15 | Both checks run. |
| termination | 3 | 3 | Both checks run conservatively. |
| guarantee | 0 | 0 | Both may reach Haiku. |
| sla | 10 | 0 | 1A runs; 3A may reach Haiku. |
| parties_or_sites | 39 | 10 | Both checks run conservatively. |

The base graph still maps 8.3.1 to `other` and 9.1.1 to `other` plus `notice`. The specified section-reference hits therefore reinforce parties/sites, dates and termination, not SLA. They do not add a guarantee or 3A SLA hit. The eligible skip set remains exactly **1A guarantee, 3A guarantee, 3A SLA**, requiring at most nine cascade samples. No actual classifier skip or confirmed-safe skip was claimed or manufactured.

**Skip truth table:** assuming a valid classifier tier and no error, the literal-Boolean rule gives:

| Samples | Skip? |
|---|---|
| `()` | No |
| `(False,)` | No |
| `(False, False)` | No |
| `(False, False, False)` | Yes |
| `(0, 0, 0)` | No: literal Boolean validation is required, not Python tuple equality alone. |
| `(False, False, None)` | No |

**Reservation arithmetic:** rendered segment bodies total 241,787 characters for base plus 1A, and 252,296 for base plus 1A plus 3A. System/schema/header overhead is not included in those counts. Applying the new formula at 4096 output tokens:

| Request | `ceil(chars/3)` | Written reservation, input at $2/M | Cold cache write at the same token estimate, $2.50/M | Difference |
|---|---:|---:|---:|---:|
| 1A chain | 80,596 | $0.202152 | $0.242450 | $0.040298 |
| 3A chain | 84,099 | $0.209158 | $0.2512075 | $0.0420495 |

This calculation holds even if the character estimate were an exact token bound and there were only one model attempt. With precisely the reserved amount remaining, the formula admits the request even though its own estimated cold-write charge exceeds that amount. It is an arithmetic counterexample to the reservation guarantee on the real request lengths, not a claim that an API call actually spent these amounts.

As a separate **feasibility scenario**, using the round-1 four-characters-per-token approximation, two cold prefixes, ten reads, $1.09 after an assumed $0.01 C0, and 2,000 output tokens per check: all twelve checks are admitted under the written reservation; check spend is about **$0.672324**, leaving **$0.417677** before gates. With 4096 output tokens per check, all twelve are still admitted in that scenario, spending about **$0.923844**, leaving **$0.166157** before gates. The revised $0.72 estimate is consequently plausible with short outputs. Neither scenario establishes a hard bound, and the second does not fund C7b's required $0.25 remaining allowance. Actual C0 usage, request overhead, token counts, cache outcomes and fallbacks must determine the live budget.

Evidence: `/tmp/astra-w3-r2-corpus.json`, `/tmp/astra_w3_r2_probes.py`, `/tmp/astra-w3-r2-probes.txt`, `/tmp/astra_w3_r2_ground_probe.py`, and `/tmp/astra-w3-r2-ground.txt`. The probe-output SHA-256 is `918fa7c97409f1f539a23578a156b8aba86e9447b2e7ec5ad3ce6adf33299ad0`.

### C) New blockers within the stop rule

1. **R2-1 | blocker | A document-only match still permits a wrong old clause on the real Exhibit/Table replacements.**

   **Location:** Rev 2 R1 target resolution, R2 edge eligibility, and R11 demo supersessions.

   **Problem and real counterexample:** 1A `p0017` explicitly replaces Exhibit A; `p0037` explicitly replaces Table A of Exhibit F. A proposed old side containing base `p0455` rent is grounded in the resolved document and passes the only scope condition provided for either target kind. The new quotes have the required supersession cues and null values. Thus the report can still present an unrelated old rent provision as the superseded provision. `target_resolution=document` describes the resolver's weakness; it does not make that old-side assertion correct. These examples create no obligation edge because the amendment paragraphs overlap no obligations, but the ChangeReport itself is covered by CLAUDE.md's invariant.

   **Concrete fix:** Separate document resolution from clause resolution. For an Item/Exhibit/Table target without a supported target range, retain the explicit copied target as unresolved at the clause level, with no asserted old clause and no edge. Alternatively freeze the narrow target ranges from this corpus: Basic Lease Information Item 7 begins at base `p0442`, Exhibit A at `p0807`, and Table A within Exhibit F at `p0888`; reject old spans outside the identified target range. The Exhibit A TextDoc contains its caption, not the diagram's contents, so do not imply the diagram's terms were recovered. Require clause-level resolution, rather than document resolution alone, for edges. Add the literal `of the Basic Lease Information to the Lease` production for `p0019`, or explicitly retain that reference as an unresolved target instead of silently ignoring its scope. Freeze the two unrelated-rent negatives and all four requested target examples.

2. **R2-2 | blocker | A role word for an omitted following date can classify the remaining date incorrectly.**

   **Location:** Rev 2 R3 shifted-date shared-role test.

   **Problem and real counterexample:** With the valid old scheduled-surrender quote, the exact new substring `commencing July 1, 2018 and expiring` contains one date plus both START and END words. The written shared-class predicate accepts the START date as an END date and produces a one-day surrender extension. This is the real July-commencement failure through quote clipping, not a new synthetic clause. Checking only that the quote has one date does not establish which date a role word governs.

   **Concrete fix:** Bind each date occurrence to its governing construction using the containing source segment. For this corpus, `commencing <date>` is START and `expiring <date>` is END; an `expiring` cue whose date lies beyond the selected quote cannot classify an earlier date. Reject incomplete constructions and require one compatible bound role on each side. Preserve the positive scheduled June 2018 to expiring June 2020 pair. Add this exact clipped source fragment beside the original isolated commencement negative; no broader synthetic search is needed.

3. **R2-3 | blocker | The new hard-reservation formula is below a supported charge at its own token estimate.**

   **Location:** Rev 2 R6 `reserve`/`settle` and the revised hard-cap claim.

   **Problem and reproducible counterexample:** On the actual 1A rendered request length, the formula reserves $0.202152. Pricing its 80,596 estimated input tokens as a cold cache write instead produces $0.242450 with the same 4096-token output ceiling. At $0.202152 remaining, admission therefore does not reserve enough. The 3A figures fail in the same way, as shown above. Settlement after the response cannot undo that excess. Character division is also an estimate rather than a proven token bound, and one-attempt output reservation does not cover multiple billed fallback attempts.

   **Concrete fix:** Reserve against the maximum applicable input tariff, including cache creation, and a defensible token upper bound covering the complete effective input. Specify a bounded fallback/attempt envelope and include it in the reservation, or decline calls whose maximum bill cannot be bounded under the hard-cap policy. Use actual priced usage only to release unused reservation. Keep the sticky stop and usage-before-parse rules already accepted. If the project chooses an estimated soft stop instead, remove the hard-cap claim and resolve that budget-policy change before C7; the current arithmetic cannot substantiate the advertised guarantee. Freeze tests using these real chain lengths and cold-cache pricing, not only cheap cache reads.

#### Known limitations

No new synthetic contract phrasings were introduced. General amendment interpretation, unsupported target layouts outside these three documents, broader date-language coverage, and novel adversarial wordings remain limitations under the stop rule. Segment-based matching measures clause localization rather than token-level semantic correctness; its separately reported field metrics remain necessary. No implemented wave-3 suite or real API overspend was claimed in this review. Only the demonstrated corpus target/date cases and the reservation arithmetic above are advanced as blockers.

### D) Verdict

proceed-after-fixes
