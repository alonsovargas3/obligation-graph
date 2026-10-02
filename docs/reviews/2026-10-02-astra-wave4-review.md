# Wave 4 plan review, round 1

Reviewed main `0b36ca4`, the wave 4 rev 1 plan, CLAUDE.md, ADR-001 through ADR-009, wave 2 and 3 reports, and the relevant merged readers, writers, clients, caches, ingest, and scoring code. This review made no model calls and changed no implementation or tests. Devbox probes opened the integration graph read-only; mutation probes used an in-memory backup, never the original database.

## Findings

### W4-1 [blocker] Freeze a citation-complete read contract, not merely a visible obligation row

**Location:** Global Constraints; Contract files; Task 30; schema v4.

**Problem:** The permitted SQL list cannot supply the promised output: `visible_obligation` has foreign-key IDs but no citation columns or party names, and the list omits agreement/source metadata, event evidence, and even the newly proposed `visible_agreement_site`. `AgreementOut.parties`, `sites`, `ObligationOut.owed_to`, and `anchor_event` have no explicit evidence contract. A grounded obligation quote alone does not prove the joined party role, site, or anchor date. An obligation being visible proves that at least one citation is grounded, not that every joined citation is grounded. The proposed source-text check for `FROM clause_ref` also misses an unrestricted `JOIN clause_ref`.

**Counterexample:** Real obligation 34 can retain its grounded obligation quote while base party citation 65 is revoked. Its obligation remains visible, but its landlord-role binding no longer is. Likewise, a relative deadline needs both the obligation quote and the cited anchor, not just a date computed by the view. `list_agreements()` must return grounded party/site evidence rather than bare facts or arbitrary citations added to satisfy an every-item assertion.

**Fix:** Freeze the complete supporting-object shapes and legal joins before dispatch. Add citation-bearing visible projections, or explicitly permit grounded, same-agreement ClauseRef joins anchored to visible rows, plus an explicit metadata-table allowlist. Return party-role and site citations and anchor evidence where used; null unresolved bindings. Distinguish source metadata and gate diagnostics from contractual terms in the citation test. Test a visible obligation with one grounded and one ungrounded citation, revoked party/event/site evidence, and all four tools. Resolve all fields within one SQLite read snapshot or one query: replace the blanket prohibition on opening transactions with permission for a read transaction, so concurrent re-extraction cannot mix an old row with new or missing citations.

### W4-2 [blocker] The existing extraction scorer bypasses the visible party binding

**Location:** Task 34; `src/og/eval/score.py:pred_from_db`; Global Constraints.

**Problem:** Reusing the scorer does not satisfy the new edge invariant. It reads roles from raw `agreement_party` and anchor names from raw `event`. Neither is checked for a currently grounded citation. The plan assigns no worker these reader changes while saying eval inherits the invariant and `og.query` is the only reader.

**Counterexample verified by execution:** In an in-memory copy of the real graph, setting `clause_ref.id=65` to ungrounded reduced the CC base's visible party bindings from two to one. `pred_from_db()` still returned **92** predictions with `owed_to='landlord'`, including obligation 34, before and after revocation. The role accuracy calculation can therefore credit an unsupported binding.

**Fix:** Make the scorer consume the same citation-safe bindings as the query API, or explicitly retain specialized scoring readers that use visible party/event projections. Add the real-row revocation regression and assign ownership of `eval/score.py`. Do not weaken the test to checking only the obligation's own quote.

### W4-3 [blocker] A stale ChangeReport looks like a completed empty check

**Location:** Task 30 `change_order`; `src/og/change/report.py:load_change_report`; Task 34 change scoring.

**Problem:** The helper reads the run, gates, and costs from raw run tables, while findings alone use freshness-filtered views. The new public surface can present an old gate decision next to current amendment obligations and no findings, without explaining that the check is invalid. `score_change()` similarly checks pairing but obtains runs from `change_run`, not `fresh_change_run`.

**Counterexample verified by execution:** On the real 3A gated run, changing the base extraction's TextDoc hash in an in-memory copy made `fresh_change_run` empty. The report then returned zero prices and zero shifted dates, but still returned six gates, seven amendment obligations, the old run ID, and cost `0.34601460000000006`.

**Fix:** Require a fresh run before constructing any completed report or scoring either side of a pair. Return a structured `stale_change_run` error with `make change` guidance, and keep missing, stale, and completed-empty states distinct. Authorize the report/scorer changes in the file-ownership list. Test the full MCP/UI/eval path using this mutation, including a fresh ungated run with a missing or stale gated partner.

### W4-4 [blocker] Gate replay cannot simultaneously cost zero and preserve the published cost tables under the proposed contract

**Location:** Global Constraints reproducibility; Task 33 gate cache; Task 34; C9/C10.

**Problem:** `GateDecision` has only one `cost_usd`, and `_run_costs()` adds it to both recorded and incremental cost. A replay that sets this to zero loses historical gate cost; one that preserves it reports fresh spending. The proposed cache payload also lacks latency, and existing run latency measures wall time. Thus results cannot be equal apart from date and run IDs. C9 itself is a new gate sample, so unchanged answers are something to verify, not assume.

**Counterexample verified by execution and code trace:** Stored gate overhead is `$0.012564` for 1A and `$0.016581` for 3A, with gate latencies 2,768 and 5,482 ms. Existing 3A results report gated cost `$0.3460146`, incremental spend `$0.016581`, and run latency 5,497 ms. A completely offline replay must change incremental spend and wall time. Extraction cache payloads do not retain original latency either.

**Fix:** Freeze separate recorded cost/latency and incremental spend/replay-wall-time fields, including gate cache-hit identity. Preserve original gate usage and latency in an allowlisted recorded payload; bypass reservation and client construction on a hit. Update the run-cost calculation and scorer, not only `HaikuGate`. Specify a deterministic semantic-results projection for C10 comparison, explicitly excluding operational timings, IDs, and incremental-spend differences. Keep historical measurements separately labeled and make C9's newly recorded gate outcomes the pinned replay baseline after rescoring.

### W4-5 [should-fix] Make the replay manifest and no-key acceptance concrete

**Location:** ADR-010 scope; Task 33; C10.

**Problem:** Moving cache files and changing directory defaults is not a complete replay contract. Both CLIs currently construct `anthropic.Anthropic()` before cache lookup. The global plan correctly requires lazy construction, but Task 33's implementation list and acceptance mention only directory changes and warm gate calls. A miss with a real key also becomes live extraction, outside the advertised zero-cost replay and outside the change budget's protection.

**Counterexample verified by execution:** All **seven** TextDocs regenerated identically from the devbox's pinned raw bytes; all **72 extraction** and **12 change** fingerprints hit the current caches under the documented defaults. This supports replay, but only for those exact inputs and configuration. Changing chunk size or effort produces another key. No fresh SEC download was performed in this review: a fresh fetch will either accept the same SHA-pinned bytes or fail the existing digest check, not silently accept new bytes.

**Fix:** Commit a manifest of source hashes, canonical TextDoc hashes, effective model/effort/chunk settings, required fingerprints, and payload digests. Test the lazy-client path by making construction and every network method fail if touched. Provide a strict recorded-only mode for C10 that errors with the missing fingerprint instead of spending. Freeze the gate fingerprint algorithm: full effective request, relevant document identity and rendering policy, and distinct sample index. Keep volatile run IDs out of content-cache keys and keep snapshot freshness checks separate. Specify a writable cache overlay if normal runs should avoid mutating committed evidence.

### W4-6 [should-fix] The blanket redaction policy contradicts the existing field-level evidence contract

**Location:** Global Constraints redacted/blank handling; Review Focus 1 and 4; Task 30; ADR-005 and ADR-008.

**Problem:** The plan nulls every amount/date/party field whenever an obligation is redacted or blank. ADR-005 explicitly preserves independently supported fields. It is unclear whether party filtering happens before or after this new masking, and the blanket phrase about no number anywhere could accidentally prohibit numbers in the required verbatim quote.

**Counterexample verified by execution:** Carbonite has 17 visible redacted obligations, including 14 payments; payment 204 has a null amount and a quote containing an unredacted third-month period. Applied Digital obligations **490** and **504** are redacted but have cited, bound payer COREWEAVE and payee APLD ELN-02. Their amounts/dates are already null. Hiding their parties changes query coverage without protecting a hidden amount. Carbonite 381 legitimately quotes an unredacted thirty-day invoice period beside hidden amounts.

**Fix:** Choose and document either field-level preservation, as in ADR-005, or an explicit stricter presentation policy in ADR-010. Freeze exactly which fields are suppressed, including anchor/offset/trigger and nested output, and how masked bindings affect matching and unresolved counts. Preserve the verbatim quote. Tests should prohibit inference of the hidden value, not every numeric token in a redacted clause. Exercise both real Applied Digital rows as well as Carbonite payment rows.

### W4-7 [should-fix] An explicit historical `as_of` still produces no scheduled deadlines

**Location:** Dates constraint; party question; Task 30; README walkthrough.

**Problem:** The plan attributes the demo problem to old dates and proposes a historical date. The stored coverage problem is stronger: none of the obligations has a computable due date. A party-filtered empty response also does not establish that no duties exist.

**Counterexample verified by execution:** The graph has **525 visible obligations, all pending**, zero superseded and zero with `effective_due`. A window from 2018-04-01 through 2018-06-30 therefore schedules none, as does every other window. Only **168/525** have `owed_to` bound: 146 in the CC base and 22 in Applied Digital. There are **114** landlord-payee rows and 54 tenant-payee rows before the plan's blanket masking; two landlord rows are redacted. Carbonite and both amendments have no bound payee. The 2018-to-2020 date shift exists in change findings, not scheduled obligations.

**Fix:** Freeze these coverage fixtures and demo honest pending results plus the cited ChangeReport date shift. Define `unresolved_party_count` over the same non-party filters before pagination, including revoked or policy-hidden bindings; distinguish unresolved from a resolved different payee. Explain that pending means no computable deadline, not overdue or no obligation. Do not fill dates or inherit amendment parties to make the demo look populated.

### W4-8 [should-fix] Site pins need field support and agreement-scope semantics

**Location:** Sites contract; Task 30 filters; Task 33 writer.

**Problem:** Grounding an arbitrary quote does not itself verify separately supplied `name` and `location`. A list of agreement sites also cannot safely become one asserted obligation-level site, especially with multiple sites. The singular `ObligationOut.site` has no ambiguity policy.

**Counterexample from real text:** Exact pins are feasible: CC base `p0542` is `55 Middlesex Turnpike, Bedford, Massachusetts`; 1A `p0006` and 3A `p0005` contain that address. Carbonite `p0694` says `The land located at 2121 South Price Road, Chandler, Arizona.` But Carbonite `p0723` describes cross-connections between the Chandler address and `120 E Van Buren Phoenix, AZ 85004`. Labeling every obligation as physically performed at one inherited site overstates the evidence.

**Fix:** Require the displayed pin fields to be copied or explicitly normalized from their cited quote, with no inferred capacity. Freeze the four feasible pins and leave other sites unknown where unsupported. Represent these as cited agreement-associated sites and label the site filter accordingly. Keep an obligation's directly bound site null unless directly supported; use a list or an explicit ambiguity result for multi-site agreements, not a first-row choice.

### W4-9 [should-fix] Site references must participate in snapshot replacement and schema rebuild

**Location:** B4 schema v4; Task 33 `store/writer.py`; C9 setup.

**Problem:** The current deletion order removes agreement ClauseRefs after parties/events, with no site association cleanup. A new foreign key from `agreement_site` will prevent the second extraction from replacing the snapshot. A shared mutable site row could also change another agreement's displayed location without changing that agreement's citation. B4 must update the version guard as well as SQL.

**Counterexample by code trace:** `_delete_snapshot()` eventually executes `DELETE FROM clause_ref WHERE agreement_id = ?`; a retained site association referencing the CC `p0542` pin would block it. The integration DB is schema v3, while `connect()` deliberately refuses older schemas under ADR-008.

**Fix:** Delete only the replacing agreement's site associations before its site-owned citations, then insert verified pins inside the existing transaction. Specify stable site identity and avoid changing shared factual fields under other agreements' references. Freeze same-input repeat extraction, changed/removed pin, invalid-pin rollback, shared-site, and older-schema tests. Assign `db.py`'s version bump to B4 and explicitly rebuild the integration graph from recorded extraction before C9, then recompute change runs.

### W4-10 [should-fix] Status filtering, limits, and pending completeness are not one shared API yet

**Location:** Query signatures; Tasks 30 through 32.

**Problem:** The UI endpoint accepts `status`, but `get_obligations()` does not. The query defaults to 200 rows, while MCP exposes neither limit nor pagination. `count` is undefined as returned count versus total matches. Implementing deadlines by calling the default obligation query could silently drop pending rows.

**Counterexample verified by execution:** An unfiltered graph query has 525 rows, and Carbonite alone has **202**. Filtering the first page in JavaScript can produce a false empty status result or a truncated count. Returning only 200 of the 525 pending obligations without metadata contradicts the promised separate pending list.

**Fix:** Freeze status versus lifecycle filter semantics and push filters into the shared query before limiting. Define total, returned, truncated, and unresolved counts explicitly. Add bounded pagination or expose a documented limit to both clients, with deterministic ordering. Either paginate deadlines with the same metadata or explicitly return the complete pending set; do not silently reuse the 200-row cap. Test Carbonite's 202 rows and the corpus's 525 pending rows.

### W4-11 [should-fix] Read-only change lookup is acceptable only as an explicitly stored-report operation

**Location:** Task 31 `check_change_order(path)`; ADR-010; C11.

**Problem:** CLAUDE.md's tool name suggests checking an input amendment. The new behavior intentionally retrieves a stored corpus report. Without exact path rules, a filename match can return the pinned amendment's report for a different file, or imply that an uploaded amendment was checked.

**Counterexample:** `data/raw/endurance-2017-ex106.htm` identifies the pinned 3A; an unrelated `/tmp/endurance-2017-ex106.htm` need not contain those bytes. Returning 3A's known shifted date for both would be a wrong answer about the second file.

**Fix:** State in the tool description and result that this loads an existing verified report and performs no analysis. Freeze exact matching of IDs, manifest local paths, and bare filenames; reject ambiguous or unrecognized paths instead of reducing arbitrary paths to their basename. If an existing file is accepted as input, verify its source pin before lookup. Include source/snapshot identity and an explicit stored-report indicator. Retain the pipeline instructions for new amendments. This scoped design can satisfy the existing-corpus demo; do not advertise checking new files over MCP.

### W4-12 [should-fix] Freeze the Desktop launch context and the actual SDK result handling

**Location:** Task 31; report helper; C11/C12.

**Problem:** Desktop does not necessarily launch from the repository. DB, text, manifest, and UI paths have different resolution conventions. Passing an absolute DB path alone does not fix the report helper's relative `data/text`. Tests also need to inspect the SDK envelope rather than treating `call_tool()` as a returned dict.

**Counterexample verified by execution:** The installed SDK is the expected MCPServer API: `@server.tool()` registration, async `list_tools()` and `call_tool()`, and synchronous `run(transport='stdio')` are valid. A tool annotated `-> dict` returned a `CallToolResult` with JSON in `content[0].text`, `structured_content=None`, and `is_error=False`. Separately, running the real 3A report helper with an unavailable text directory changed its five unresolved-document aliases to an empty list, silently implying a more complete chain.

**Fix:** Freeze a Desktop command using an absolute uv path and repository directory, or resolve every data asset from an explicit workspace root. Test launch from an unrelated cwd, real stdio initialization/list/call, missing/older DB handling, and stdout protocol cleanliness. Parse the actual SDK result envelope in tests, or use typed output models and explicitly test structured output. A missing TextDoc must be an error/unknown state, not an empty unresolved list. Keep C12 as a required user-confirmed acceptance record; an SDK subprocess smoke test is useful but is not evidence that Claude Desktop was tested.

### W4-13 [should-fix] Pin the aggregator's evidence sources and preserve the existing metric caveats

**Location:** Task 34; Numbers constraint; C11; ADR-006/008/009.

**Problem:** There is no aggregate result schema or rule for choosing committed files, matching logs to graph runs, combining document metrics, or carrying historical variance. The latest log line is not necessarily the graph's run. A single replay cannot reproduce three independent samples. The existing sampled-score helper retains only micro/macro precision lower bounds while nulling per-type precision, so per-type lower bounds require an explicit addition.

**Counterexample:** The committed extraction summary describes three samples and sampled 50-obligation labels; the devbox has 24 extraction run log records, and the latest one belongs to 3A, not the reference base. Haiku was observed only on three negative category cases, so its recall is null. Selecting the latest dated file or averaging per-document percentages can change the headline without any model change.

**Fix:** Freeze an aggregate schema and explicit result manifest/CLI input, including corpus and prompt hashes. Join logs by the current extraction/change run identities, reject missing/incomplete/mismatched inputs, and aggregate drops over the intended corpus. Preserve sampled precision labeling, per-type lower bounds, field coverage, the n=3 historical variance disclosure, reference-relative and baseline-relative gate metrics, Haiku coverage/null recall, skip classifications, miss bounds, and replay cost/latency distinctions. Generate README tables from one explicitly pinned committed aggregate artifact; test tampered values and a missing block. Keep historical samples labeled historical unless their archived responses are also replayed separately.

### W4-14 [should-fix] Separate worker acceptance from the late README and real UI acceptance gates

**Location:** Task 34 tests; Task 32 tests; B4; C11/C12; execution topology.

**Problem:** A frozen test against the repository README cannot pass during Task 34 if the coordinator only authors README in C11. There is no README at the reviewed commit. Conversely, required element IDs and endpoint equality do not prove that the browser actually filters rows or displays their citations. These sequencing gaps let a worker either fail for an unowned artifact or pass a nonfunctional page.

**Counterexample:** Task 34 cannot legally create the missing README, and Task 32 can satisfy static element checks with inert controls. The plan's final Definition of done also still requires the Desktop user step, while the walkthrough link remains a user deliverable.

**Fix:** Test renderer/checker behavior on temporary README fixtures during Task 34, then activate the real committed-artifact check after C11, or have B4 provide the coordinator-owned generated skeleton. Require one browser integration/manual acceptance covering filtering, a Carbonite redacted payment, exact clicked clause, and a 1A/3A change pair with gates; render source text as text, not HTML. Track Desktop confirmation and the walkthrough link as explicit final acceptance items, not implicit consequences of passing unit tests. Freeze any additional shared report/scorer/schema contract edits identified above before parallel workers start.

## Verified replay and feasibility assessment

- Re-ingesting the seven existing pinned raw files produced byte-identical canonical TextDoc JSON for every document. Extraction cache coverage was 5/5 TeraWulf, 20/20 CC base, 2/2 1A, 1/1 3A, 28/28 Carbonite, 10/10 Mawson, and 6/6 Applied Digital. Both change orders hit all six category caches.
- Extraction keys hash the canonical full effective request, source SHA, and canonical TextDoc SHA. The request includes prompt/schema, model, effort, max_tokens, fallback settings, and rendered chunks; chunk size, context rendering, sections, and ingest output therefore matter. Change keys hash the full request plus each ordered agreement ID, source SHA, and TextDoc SHA. Current change keys do not include new extraction run IDs; those correctly remain a separate snapshot validity check. A new gate cache must preserve the same separation.
- A fresh fetch is reproducible conditional on retrieving the SHA-pinned SEC bytes with the required EDGAR User-Agent and using the locked ingest environment. The current fetcher refuses changed bytes. There is no evidence of a key mismatch in the present corpus, and no reason to spend the remaining API budget rerunning extraction.
- No inferred numeric redaction leak was found in the real visible Carbonite/Applied Digital rows. All 19 redacted rows have null stored amount/date/anchor/offset fields, and their descriptions are source quotes. The risks identified here concern new serialization policy, supporting citations, and invalidated evidence.
- The installed MCP 2.2 API named by the plan is correct. The missing pieces are output-envelope assertions, workspace-independent operation, and the actual Desktop acceptance, not an SDK replacement.
- The change-order Definition of done is feasible with the existing data: cite a 1A replacement, the 3A date shift or a rent cell, and a confirmed-safe guarantee/SLA skip. Zero obligation edges remain an accepted wave 3 limitation. The README's semantic-memory and future episodic-memory section should remain a direction, as the plan already requires.

## Verdict

proceed-after-fixes
