# Wave 1 plan review

Reviewed `CLAUDE.md`, `docs/research/2026-10-01-approach.md`, and `docs/superpowers/plans/2026-10-01-wave1-scaffold-to-ground.md`. In the locations below, **plan** means that last file. Scope is pre-implementation review, with no application changes.

Execution evidence: copied the supplied Python and SQL blocks unchanged into a disposable directory and ran them under Python 3.12.7. The supplied TextDoc, schema, fetch, ground, and marker tests passed: **46 total = 5 + 9 + 7 + 12 + 13**. Additional probes below demonstrate gaps those tests do not catch. No ingest implementation was supplied, so its nine tests were inspected, not reported as executed. Ruff checks used the plan's settings with a currently resolved version; production should freeze the actual tool versions in `uv.lock`.

1. **blocker: A grounded reference can expose an obligation from a different agreement.**

   **Location:** plan, Task 1 Steps 6 to 7, `src/og/store/schema.sql`, `clause_ref` and `visible_obligation`; `CLAUDE.md`, the invariant and reader contract.

   **Problem:** The view checks only `c.obligation_id = o.id AND c.grounded = 1`. It does not require matching agreement IDs. The CHECK also accepts negative offsets, zero-length spans, and empty text. Execution accepted a reference with agreement `a2`, offsets `(-5, -5)`, and empty text, then exposed its obligation in `a1`. Even structurally valid text in another agreement must not ground this obligation. The supplied schema test also uses `char_end=10` for the 12-character text `Tenant shall`, so it encodes inconsistent copied-span metadata.

   **Concrete fix:** Require agreement identity in the visibility predicate and enforce identity for obligation-linked references at insertion/update, using a composite FK or triggers. Require nonnegative, nonempty ranges and nonempty copied source text; once source copying is the stored-text contract, validate its length against the range. Fix the inconsistent fixture before red. SQLite cannot prove source-text equality from a boolean alone: explicitly reserve setting `grounded=1` for the validated writer, with boundary tests that check the source hash and copy the returned slice. Add wrong-agreement, invalid-range, and stale-grounding tests before freezing.

2. **blocker: Derived deadlines and graph edges can state uncited terms.**

   **Location:** plan, Task 1 Steps 6 to 7, `event`, `defined_term`, edge tables, and `visible_obligation`; `CLAUDE.md`, cited events/edges; research, Anti-drift and Practical gaps.

   **Problem:** `event.clause_ref_id` is nullable and the deadline view never checks the event's evidence. Execution returned `2026-01-31 / scheduled` from an uncited event, even when the event belonged to another agreement. The provided relative-deadline test explicitly rewards an uncited event. Edge FKs require an existing reference, but permit `grounded=0`; execution inserted such a trigger. There are no grounded edge/defined-term reader views, so the claim that the DB enforces the invariant for every reader is incomplete.

   **Concrete fix:** Require a grounded citation for any event date used in `effective_due`, and keep the deadline pending when that evidence is missing. Make the test create the relevant grounded event reference. Define whether cross-agreement anchors are allowed and require explicit cited linkage if they are. Add canonical visible views for edges and defined terms, joining grounded evidence and eligible endpoints as appropriate, and require future readers to use them. Test both insertion and later loss of grounding, including the event and edge reference chains returned with results.

3. **blocker: The ingest section rule contradicts a required test.**

   **Location:** plan, Task 3 Rules and Step 2, `detect_sections` and `test_offsets_point_at_text`.

   **Problem:** The rule treats `2.1 Tenant shall pay Base Rent ...` as a new section and ends the preceding article section there. The test requires `section_for(Tenant...).heading == "RENT"`. A flat, nonoverlapping Section list cannot both use clause-level sections as specified and attribute that offset to the article section. Execution confirmed that the exact numbered-clause regex matches the fixture's `2.1` line. A weaker worker is likely to disable numbered-section detection to pass the frozen test.

   **Concrete fix:** Choose and document a single flat section granularity before red. Prefer keeping the specified numbered clauses, changing the test to assert section number `2.1`, and defining what its heading contains. If article context is required, add an explicit parent/context field and corresponding shared-interface changes in Task 1 rather than overlapping intervals or silently inheriting headings. Pin the complete expected section list for the fixture.

4. **blocker: The red-first protocol cannot be followed in the supplied task order.**

   **Location:** plan, Supervision protocol item 1; Task 1 Steps 1 to 8; Task 2 Step 1 and the Task 1 fetch stub.

   **Problem:** Task 1 must first commit only tests, but its executable test environment requires the uncommitted scaffold from Steps 1 to 3. It then implements TextDoc before adding the schema tests, violating the single frozen red baseline. Task 2's existing `fetch.py` raises SystemExit at import time, so `from og import fetch` aborts pytest collection rather than producing the intended missing-API failures. This also differs from a clean expected ImportError/assertion red result.

   **Concrete fix:** Introduce an accepted tooling/bootstrap commit before the red gate, with an import-safe package and stubs whose exit behavior is guarded by `if __name__ == "__main__"`. Specify either one red commit containing both Task 1 test files before either implementation, or separate explicitly tracked red/green substeps. For each task, name the exact baseline SHA and runnable command. Verify the red commit in an isolated checkout, not by changing a live worker's branch.

5. **blocker: Literal frozen tests cannot pass the required lint gate.**

   **Location:** plan, Supervision protocol items 2 to 3; supplied tests in Tasks 1, 2, and 4; Task 1 Ruff settings.

   **Problem:** Execution of `ruff check tests` on the copied tests found eight violations, including import ordering and line length. `ruff format --check tests` would reformat four files. The protocol requires an empty test diff after red except the property-test addition, so normal formatting after the red commit is forbidden even if assertions are unchanged.

   **Concrete fix:** Run Ruff import fixes and formatting on the intended tests before red, have the coordinator compare their semantics with the reviewed tests, and freeze those formatted files. Add a documented coordinator-approved correction process for genuinely defective frozen tests that records the old/new assertions and reruns the red check. Do not leave workers to choose between weakening tests and failing lint.

6. **should-fix: TextDoc validation does not establish reliable citation metadata.**

   **Location:** plan, Task 1 Step 5, `src/og/textdoc.py`; research, deterministic checks at artifact boundaries.

   **Problem:** Execution showed `validate()` accepting a segment whose range is in `s2` but whose `section_id` is `s1`, page `999` with no such page, overlapping segments, duplicate section IDs, and a zero-length section. Sections/pages may leave gaps, and load/from_json do not validate at all. Valid offsets alone therefore do not establish a correct section or page citation.

   **Concrete fix:** Define empty-document behavior, then validate unique section IDs and page numbers, section/page coverage and ordering, nonempty meaningful spans, segment ordering/nonoverlap, and agreement between each segment's declared metadata and its actual containing interval. Define whether a segment may cross a section/page boundary; splitting there is the simpler contract. Validate on load/from_json as well as save, and add negative tests for these cases. Preserve support for hand-built grounding documents with an empty segment list.

7. **should-fix: Grounding can return a successful match with stale or contradictory section attribution.**

   **Location:** plan, Task 4 Semantics and Step 3, `ground()` and `GroundResult`; `CLAUDE.md`, same-section fallback and ClauseRef shape.

   **Problem:** The range pass ignores `section_id`. Execution grounded `TERM` in section `s2` while the input explicitly named `s1`. An unknown section ID is silently replaced with the offset's section, as required by one test but not stated in the Semantics text. GroundResult returns offsets without corrected section/page, leaving a later writer free to retain the model's incorrect metadata. Existence of a quote does not establish its claimed section, page, or interpretation.

   **Concrete fix:** Specify whether an explicit known section constrains the range pass; preferably reject or fall back within it when the supplied range disagrees. Explicitly document the unknown-ID policy. Require the writer to derive section/page from the final validated offsets and copy the final source slice, never persist the model's stale metadata. Add conflicting-section and boundary-crossing tests. Keep semantic extraction accuracy separate from the exact-match audit; the latter proves text existence, not that an arbitrary description is entailed.

8. **should-fix: The property-test recipe makes an invalid claim about fallback method.**

   **Location:** plan, Task 4 Step 5.

   **Problem:** Shifting offsets by up to 50 characters does not guarantee the range pass fails. A zero shift, a range still containing the normalized quote, or a repeated short quote can return `method="range"` correctly. Whitespace-only substrings normalize to empty and should fail, but the recipe only excludes boundary cuts and section crossings. A worker could distort correct grounding behavior to satisfy the added test.

   **Concrete fix:** Generate 200 nonempty normalized quotes wholly inside one section. For true ranges, require range success and slice equality. Test fallback separately with a deliberately nonmatching short range and an explicit section ID, verifying that the range contains no match first. Add deterministic tie/overlap cases. Execution exhaustively checked `_find_all` over small strings containing ordinary spaces, tabs, and NBSP: 12,261 returned hits all satisfied normalized slice equality. There is no demonstrated off-by-one bug in `_norm_map` here: the normalized needle is stripped, so the last matched character is non-whitespace.

9. **should-fix: Exhibit resolution lacks the URL context and fixture needed for the real fetch gate.**

   **Location:** plan, Task 2 Steps 1 to 3, `resolve_exhibit` and anchor resolution.

   **Problem:** Step 3 supplies an accession directory URL, while the parser assumes filing-detail rows with `EX-10.1` metadata. A filename directory listing cannot satisfy that predicate. The only fixture has a root-relative href; execution with `href="ex10-1.htm"` returned the invalid URL `https://www.sec.govex10-1.htm`. The interface has no base URL with which to resolve a directory-relative link. This review did not fetch the live SEC index, so its exact markup remains unverified.

   **Concrete fix:** Pin the filing-detail index URL, verify it contains the desired exhibit row, and record a representative offline fixture before freezing tests. Pass the index URL into the resolver and use `urljoin`, with an allowed SEC archive destination check. Select the document link in the matching row explicitly. Test root-relative, directory-relative, absolute, absent, and ambiguous matches; distinguish an unsupported index layout from an absent exhibit. Extract the filing date from identified filing metadata, not a guessed directory timestamp.

10. **should-fix: Ingest can label modified bytes with a previously pinned source hash.**

    **Location:** plan, Task 2 `fetch_all`; Task 3 `ingest_file` and CLI; research, typed artifacts and deterministic boundary checks.

    **Problem:** Task 3 receives a sha256 string and is told to ingest every existing local file, but is never told to verify that file against the hash. Its fixture even passes a dummy hash. Thus `make ingest` can produce a TextDoc citing a pinned source while processing different bytes. Fetch also writes files before the complete manifest update, so a later download failure can leave unpinned local files available for ingest.

    **Concrete fix:** Verify actual raw bytes against a non-null manifest digest at the CLI ingestion boundary and refuse a mismatch or missing pin. Keep a clearly named pure parsing helper for tests if arbitrary fixture hashes are useful. Persist file/hash updates atomically per completed source or stage them consistently, and test a failed later download plus subsequent ingest. Task 3's real smoke gate must run on Task 2's verified artifacts, not merely whatever files happen to exist.

11. **should-fix: Text normalization and page tracking need an explicit shared coordinate algorithm.**

    **Location:** plan, Task 3 Rules and Step 3, `html_to_text`.

    **Problem:** Recording page offsets while appending raw strings and then collapsing newlines/spaces changes all subsequent offsets. The plan forbids re-searching final text but does not specify a remapping strategy. Nested `div/p` and `table/tr` blocks also invite duplicate text or separators. Rules do not settle leading/trailing/consecutive page breaks, styles with spaces/case differences, or an empty final page. The single page-break-before fixture leaves `page-break-after`, modern break styles, and `<hr>` untested despite the Review Focus claiming both kinds are pinned.

    **Concrete fix:** Specify an emitter that performs normalization before assigning final character positions, or retain an explicit raw-to-final position map. Walk each text node once, emit cell separators once, preserve NBSP and quotes, and exclude non-document script/style text. Deduplicate coincident page starts, prohibit accidental empty pages, and parse the intended CSS declarations independently of spacing/case. Add fixtures combining nested blocks, inline tags, newline collapse, all supported page markers, and breaks at document edges, with exact text and offset assertions.

12. **should-fix: Ownership lists and the integration DAG omit required writes and artifacts.**

    **Location:** plan, Tasks 1 to 3 Files lists, Task 3 Steps 3 and 5, Execution topology, Wave 1B scout.

    **Problem:** Task 1 is told to create/commit `uv.lock`, `src/og/fetch.py`, and `src/og/ingest/__main__.py`, but they are absent from its Files list. Task 3 must implement `src/og/ingest/__init__.py`, also absent from its list. Task 2's manifest permission says only scout-provided entries although it must update the existing anchor. Separate git worktrees do not share gitignored `data/raw/`; merging Task 2 does not deliver its files to Task 3. Task 3 also cannot independently finish its stated real-corpus acceptance while Task 2/scouting is unfinished.

    **Concrete fix:** Correct the ownership lists before dispatch. Make Task 1 the sole owner of `pyproject.toml`, `uv.lock`, and Makefile; Task 2 the sole post-scaffold writer of the anchor and approved scout entries in `data/sources.yaml`; Task 3 the sole post-scaffold writer of ingest files including `__init__.py`. Keep the scout read-only. Permit parallel unit work, then add an explicit corpus-integration gate with verified raw-file transfer or a rate-limited fetch in the receiving worktree. Run combined acceptance after merging all relevant branches. Task 5's ADR files are otherwise disjoint, but refresh their assertions after schema/grounding fixes.

13. **should-fix: Retry and supervision rules need authority and evidence details.**

    **Location:** plan, Execution topology and Supervision protocol items 1 to 7; current Orca worker contract.

    **Problem:** A quota error or a second scope drift is not by itself proof that the old worker exited. Relaunching immediately risks two editors and stale completion messages. A quota failure before red has no "last red-verified commit" to restart from. Reading only 50 transcript lines every ten minutes can miss out-of-scope edits; checking the report/branch alone does not inspect uncommitted files. The plan does not spell out transfer of test-freeze evidence, pre-red fallback, review checkout isolation, or coordinator-driven corrections to defective frozen tests.

    **Concrete fix:** Require positive exit/accepted settlement evidence and the runtime's stop/retry procedure before starting Grok on the same task. Preserve Task/Dispatch identity, use a fresh authoritative dispatch, reject stale lifecycle messages, and record base/red SHAs, tool versions, test hashes, approvals, and any salvaged uncommitted work. Define pre-red retries from the accepted bootstrap/base. At checkpoints inspect actual status/diffs plus transcript, and acknowledge follow-ups according to the runtime guide. Freeze tests across retries; changing tests requires a recorded review decision and renewed red verification. Keep coordinator verification in a separate checkout and use `uv sync --locked` so acceptance does not quietly alter dependencies.

14. **should-fix: Deadline columns allow silent coercion and invalid scheduled dates.**

    **Location:** plan, Task 1 Step 7, `obligation`, `event`, and `visible_obligation`.

    **Problem:** SQLite's `INTEGER` affinity does not reject fractional offsets. Execution stored `offset_days=1.9`, then `printf('%+d days', ...)` silently calculated one day. Execution also returned `effective_due='garbage'` and lifecycle `scheduled` for an invalid direct date. Simultaneous direct and relative dates silently prefer the direct date, and half-populated anchor/offset pairs are allowed without a policy.

    **Concrete fix:** Define valid ISO date handling, validate calendar dates at the writer boundary, and enforce integer offset storage without truncation. Specify precedence or prohibit conflicting deadline representations. Define the allowed incomplete representation for unresolved deadlines and test it. Add invalid-date, fractional-offset, negative-offset, leap-day, and conflicting-source cases before freezing schema tests.

15. **should-fix: Marker detection is not yet a redaction/blank enforcement boundary.**

    **Location:** plan, Task 4 `markers.py`, Task 1 status fields, Task 5 ADR-005; `CLAUDE.md`, blank/redacted terms must never be inferred.

    **Problem:** All 13 supplied marker cases passed unchanged in execution, including spaced stars; there is no demonstrated regex failure in those cases. However, the functions only detect markers and the schema permits status `blank` alongside arbitrary amounts/dates. No contract says how marker results constrain extracted fields or mixed known/redacted clauses. A weaker wave-2 worker could treat status as a cosmetic label while exposing invented terms. Broad bare-star matching can also classify formatting as redaction, so context and false-positive policy should be explicit rather than hidden in the helper.

    **Concrete fix:** Record the next writer's contract now: copy and ground the source quote, preserve marker evidence, leave the specific unavailable fields unset, and never fill form placeholders from metadata or model knowledge. Define mixed redacted/blank precedence and how known fields remain available with their own support. Add integration acceptance for a marked amount beside an independently stated deadline; do not simply null every field of any obligation containing a marker. Keep regex matching deterministic and do not claim it establishes semantic support.

16. **should-fix: Fetch tests do not establish the full offline/rate-limit contract.**

    **Location:** plan, Task 2 Steps 1 to 2, `MockTransport`, `RateLimiter`, and `fetch_all`; Global Constraints.

    **Problem:** All seven supplied fetch tests passed in execution. The MockTransport setup correctly associates returned responses with requests, so `raise_for_status()` is not a bug here. The fake sleep in the limiter test records a delay but never advances its fake clock, proving only the second call requests 0.2 seconds. Redirects in the internally created client can issue additional HTTP requests without another limiter wait; independently created fetchers have independent budgets. The tests also omit HTTP failures, corrupted cached bytes, and missing hashes. The internally created client is never closed.

    **Concrete fix:** Use a fake sleep that advances the clock, assert several consecutive request-start times, and test invalid rates. Execution with that advancing fake clock confirmed ordinary sequential waits at 0.0, 0.2, 0.4, and 0.6 seconds. Define one active fetch budget for the corpus, handle redirects/retries through the limiter, and add corresponding MockTransport tests. Close clients owned by `fetch_all`, retain caller ownership of injected clients, and explicitly disable real network access in the test environment. Keep index discovery/scouting under the same agreed request budget when running concurrently.

17. **nit: Acceptance wording and references need mechanical cleanup.**

    **Location:** plan, Review Focus item 5, Task 1 Step 3 note, Task 4 acceptance, and aggregate test-count reporting.

    **Problem:** Review Focus refers to `test_markers`, but the actual tests are three parametrized functions in `tests/test_markers.py`. The anchor note points to Task 2 Step 4 although resolution is Step 3. The intended grounding grep for `fuzz` would reject the supplied docstring `No fuzzy matching`; if run without extended-regex support, the alternation can instead falsely pass. Exact total counts are not provided for merged acceptance.

    **Concrete fix:** Correct the references, inspect forbidden imports/calls rather than banning explanatory comments, and state baseline counts: Task 1 is 14, fetch is 7, ingest is 9, ground is 12, markers are 13, totaling 55 before the property test and 56 if that test is one pytest item. Recalculate counts after accepting the additional regression tests above, and record collected test IDs alongside totals so a matching count alone is not treated as proof.

proceed-after-fixes

## Round 2

### A) Disposition of the 17 original findings

1. **resolved**: Obligation-linked references now have agreement-match triggers, structural span CHECKs, and a matching-agreement visibility predicate; the writer/source-copy contract and fixture lengths are corrected.
2. **partially resolved**: Grounded event and edge filtering exists, but event and defined-term citations can still come from another agreement; see R2.1.
3. **resolved**: The flat clause-level sections, new `article` field, and frozen expected section list agree and pass together.
4. **resolved**: The coordinator bootstrap and complete pre-implementation red suite remove the former task-order and import-stub contradiction.
5. **resolved**: The frozen tests pass both locked Ruff checks, and the plan now gives the coordinator an explicit test-correction procedure.
6. **resolved**: Validation rules specify coverage, metadata agreement, uniqueness, nonempty spans, and validation on load; the conforming disposable TextDoc passes all 19 tests.
7. **resolved**: The reference grounder constrains known explicit sections, rejects cross-section matches, and returns derived section/page metadata.
8. **resolved**: True-range and forced-fallback properties are now independently satisfiable; two single-character fallback cases are explicitly skipped by the frozen tests.
9. **resolved**: Resolver context, URL joining, exact Type matching, errors, and a real-index recording gate are explicit; all 23 fetch tests pass without special cases for individual assertions.
10. **resolved**: Ingest verifies pinned raw bytes and fetch persists each completed document's pin atomically, addressing the original source-provenance and later-download-failure gaps.
11. **partially resolved**: The specified emitter satisfies all current fixtures, but buffered text around non-block page markers still loses or misplaces page boundaries; see R2.3.
12. **partially resolved**: Ownership and shared raw paths are fixed, but Task 3's branch does not receive Task 2's manifest pins merely because the raw files are shared; see R2.2.
13. **partially resolved**: Exit evidence, fresh dispatches, salvage, and coordinator review are specified, but the freeze artifact is absent in this snapshot and pre-push retries can discard Task 1 dependencies; see R2.5 and R2.6.
14. **resolved**: The reference schema rejects invalid dates, fractional offsets, incomplete anchor pairs, and conflicting deadline representations in the locked Python/SQLite environment used for this proof.
15. **resolved**: ADR-005 now records the source-copy, grounded-writer, marker-evidence, and field-specific missing-value contract for wave 2; marker detection is not presented as semantic verification.
16. **partially resolved**: Per-fetch redirect limiting, client closure, offline HTTP tests, and failure handling are fixed, but the claimed shared request budget across the scout and fetch worker has no coordination mechanism; see R2.7.
17. **resolved**: References and comment-grep acceptance are corrected, and the integration report must record collected IDs; the actual collected totals are documented below.

**Totals: 12 resolved, 5 partially resolved, 0 wholly unresolved.** These are dispositions of the original findings, not a claim that all rev-2 issues are closed.

### B) Satisfiability proof

Created a disposable repository copy at `/tmp/og-astra-round2-1a5yhmx2`, excluding the original Git metadata and virtual environment. All implementation writes occurred in that copy. Original repository file hashes were recorded before the work and verified unchanged before this appendix was written.

In the copy, implemented `src/og/textdoc.py`, `src/og/fetch.py`, and `src/og/ingest/{__init__,__main__,html,sections}.py` from the written rules. Copied `src/og/ground.py`, `src/og/markers.py`, `src/og/store/schema.sql`, and `src/og/store/db.py` directly from the plan's reference blocks. The implementation uses the specified line emitter, flat sections, atomic fetch writes, request-hook limiter, and validating TextDoc boundary. It does not change or replace tests, alter the reference grounder, bypass assertions, or condition behavior on test names.

Ran `uv sync --locked` successfully, then `uv run --locked pytest -q --junitxml=/tmp/og-astra-round2-initial.xml`. The first implementation run passed all non-skipped tests. Repeated the suite with test-ID reporting and `/tmp/og-astra-round2-final.xml` to retain a per-file tally. Environment: **CPython 3.12.11, SQLite 3.50.4**, using the supplied `uv.lock`. No venv/pip fallback was needed.

| Frozen test file | Passed | Failed/errors | Skipped | Interpretation |
|---|---:|---:|---:|---|
| `tests/test_textdoc.py` | 19 | 0 | 0 | All rules exercised by this file are satisfiable |
| `tests/test_schema.py` | 33 | 0 | 0 | Exact reference SQL and db.py pass |
| `tests/test_fetch.py` | 23 | 0 | 0 | MockTransport, redirect hooks, atomic pins, resolver, and limiter tests pass |
| `tests/test_ingest.py` | 16 | 0 | 0 | Exact text, section list, page markers, hashes, and PDF exclusion pass |
| `tests/test_ground.py` | 265 | 0 | 2 | Exact reference grounder passes; the two skips are intentional single-character fallback cases |
| `tests/test_markers.py` | 17 | 0 | 0 | Exact reference regexes pass |
| **Total** | **373** | **0** | **2** | **375 collected items** |

There were **no frozen-test failures** to classify as TEST wrong versus disposable implementation wrong, and no corrective implementation iteration was needed. No frozen assertion was demonstrated to contradict the written rules for its tested input. The 250 parametrized property items comprise 248 executed passes and 2 explicit skips, alongside 17 ordinary grounding tests. The schema and marker subtotal reproduces the coordinator's 50 passes.

Also ran `uv run --locked ruff check tests` and `uv run --locked ruff format --check tests`: both passed, with all seven Python test/support files already formatted. A SHA-256 comparison confirmed that every copied frozen test and fixture remained byte-for-byte identical to the original snapshot. The disposable implementations are evidence only, not proposed production patches or a claim of full lint/real-corpus acceptance. No live SEC fetch or recorded-index test was performed; those remain Task 2 work.

The retained scratch implementations and XML reports make the proof inspectable, but they are temporary artifacts outside the repository. Passing these tests establishes satisfiability of the current acceptance suite, not completeness of the invariant checks. The following additional probes expose behavior the frozen suite does not currently cover.

### C) Remaining and new rev-2 findings

1. **blocker: Event and defined-term citation identity is still unchecked.**

   **Location:** plan, Task 1 reference `schema.sql`, `visible_obligation`'s `anchored` CTE and `visible_defined_term`; `tests/test_schema.py`, grounded-event and defined-term tests.

   **Problem:** The anchor's event agreement is checked against the obligation's agreement/base, but the event's citation agreement is never checked against the event. Likewise, the defined-term view only checks `grounded=1`. With the exact reference schema, execution inserted an event attributed to agreement `a` whose grounded citation belonged to unrelated agreement `b`; an obligation in `a` then returned `2026-01-31 / scheduled`. A defined term attributed to `a` with that citation was also visible. Clearing the citation's grounded flag correctly hid its effects, proving this is the missing identity condition rather than a general grounding-filter failure. The obligation-reference trigger does not cover these nullable-obligation references.

   **Concrete fix:** Require `c.agreement_id = e.agreement_id` in the event evidence predicate and `c.agreement_id = d.agreement_id` in `visible_defined_term`. Prefer enforcing those identity relationships on insertion/update too, while retaining defensive view predicates so parent changes cannot silently expose mismatched evidence. Add negative tests for both wrong-agreement citations and update paths. Keep the separately authorized same/base event-to-obligation relationship; it does not authorize a citation from an unrelated third agreement. This is a reference-schema defect that passes the frozen tests, not an unsatisfiable frozen test.

2. **should-fix: Shared raw files do not deliver the manifest required by Task 3's smoke test.**

   **Location:** plan, Execution topology Waves and Wave 0 shared-data setup; Task 3 Step 3 and CLI filtering; `data/sources.yaml`.

   **Problem:** Task 3 starts rebased on Task 1, while Task 2 independently edits its own tracked `data/sources.yaml`. Only `data/raw` and `data/text` are shared. Task 3 therefore still sees the bootstrap anchor with `sha256: null`, even after Task 2 has populated shared raw files and pins in another branch. Its required CLI correctly skips that anchor, and it cannot report the requested real-corpus sections. The final all-merged gate does not make Task 3's earlier individual acceptance executable. An ingest already in flight during later downloads could also observe an incomplete corpus snapshot.

   **Concrete fix:** Split Task 3 acceptance into independent unit completion and a corpus smoke gate that explicitly waits for Task 2's manifest commit, merges/rebases that commit into the review/integration checkout, and uses the matching completed raw snapshot. The coordinator can run the smoke there or redispatch the worker after providing the updated manifest. Do not make the ingest worker edit pins or rely on symlinks to transfer tracked manifest state. Specify which corpus commit/hash set produced the reported text artifacts.

3. **should-fix: A pending page break can consume buffered text from the wrong side of the marker.**

   **Location:** plan, Task 3 Emitter algorithm items 2 to 5; `tests/fixtures/ingest/pages_mixed.htm`.

   **Problem:** `<hr>` sets `page_pending` but is not a line boundary. Break styles can also occur on elements outside the block set. Existing `current` text then survives across the break, and only the next appended line consumes the flag. Following the written algorithm, execution on `Alpha<hr>Bravo` produced `AlphaBravo` on one page. Execution on `<p>Alpha <span style="break-before:page">Bravo</span>.</p>` produced one line and one page as well. The fixture avoids the problem by placing markers between already flushed block lines. Thus the algorithm passes its frozen tests while violating the intended preservation of page boundaries for these inputs.

   **Concrete fix:** Define marker ordering explicitly: flush pre-break buffered text, then mark the next line as a new page; for after-break styles, flush the element's content before setting the pending flag. Make `<hr>` a structural boundary as well as a page marker. State whether inline-element page styles are honored or intentionally excluded, and test the chosen behavior. Add inline/loose-text fixtures with exact text, page starts, and segment bounds rather than relying solely on paragraph-delimited markers.

4. **should-fix: Article-title continuation can swallow a new section heading.**

   **Location:** plan, Task 3 Sections rules, empty ARTICLE heading plus next uppercase line.

   **Problem:** Any following line of at most 80 characters without lowercase letters becomes the ARTICLE title, with the instruction that it stays inside that section. Such a line may itself match `SECTION 2 RENT`, another ARTICLE, or an uppercase numbered clause. The finest-section rule simultaneously makes it the next section. Execution of the straightforward parser on `ARTICLE 1\nSECTION 2 RENT\ntext.` gave article heading/context `SECTION 2 RENT` and a separate section 2, demonstrating the bad attribution and conflicting instructions. The existing title-continuation fixture uses `DEFINITIONS`, so it cannot catch this.

   **Concrete fix:** Accept the uppercase continuation only when the next line does not independently match any section-start pattern. Track that consumed title line explicitly; otherwise keep the ARTICLE heading empty and let the next heading begin its own section. Pin ARTICLE-followed-by-SECTION, consecutive ARTICLE headings, and ordinary uppercase-title cases before freezing the amendment.

5. **should-fix: Freeze evidence and locked entrypoints do not match the hand-off description.**

   **Location:** plan, State at hand-off and Supervision protocol item 1; `tests/FROZEN.sha256`; `Makefile` fetch/ingest targets.

   **Problem:** `tests/FROZEN.sha256` does not exist in the reviewed repository snapshot, confirmed again immediately before writing this appendix. The description says it hashes every file under `tests/`, which would include itself and generated `__pycache__` files unless exclusions are explicit. This is not a reproducible freeze procedure. Separately, `make fetch` and `make ingest` still invoke `uv run` without `--locked`, unlike the global rule and test/lint targets.

   **Concrete fix:** Before dispatch, commit a deterministic manifest of the baseline tracked test/fixture files, excluding the manifest itself and generated artifacts, and record the bootstrap SHA. Specify the exact recomputation/comparison procedure and handling of Task 2's two authorized additions. Reuse those fixed baseline hashes across retries, accepting a changed baseline only through the documented coordinator correction process. Add `--locked` to the coordinator-owned fetch/ingest Makefile commands. My independent hash checks establish this review's test integrity but do not substitute for the project's missing hand-off artifact.

6. **should-fix: A pre-push retry can discard a later task's dependency baseline.**

   **Location:** plan, Supervision protocol item 5, fallback start commit; Waves 1A/1B.

   **Problem:** If a worker has no pushed commit, the retry always starts at the bootstrap. Tasks 3 and 4 are required to start after Task 1 merges and are rebased on it. A quota failure before their first push therefore sends the Grok retry back to a branch with no TextDoc implementation. The original task's actual accepted base is lost even though its tests remain frozen. This reintroduces an avoidable missing-dependency failure during recovery.

   **Concrete fix:** Persist each dispatch's exact accepted base SHA, including prerequisite merges, before starting the worker. Retry from the last verified pushed worker commit or that task-specific base SHA, not unconditionally from bootstrap. Include the frozen-test manifest and prerequisite SHAs in the retry payload, and verify the branch and working tree against them before restoring any salvage. The new positive-exit and fresh-dispatch requirements otherwise address the original retry-authority problem.

7. **should-fix: The shared SEC request budget remains a statement without an owner.**

   **Location:** plan, Global Constraints, Task 2 `fetch_all` default limiter, Corpus scout during Wave 1A.

   **Problem:** Each default `fetch_all` call creates its own limiter, while the concurrent scout runs in a separate process. The hook correctly limits redirects and index requests within one client, as the executed tests show, but it cannot coordinate the scout or another invocation. Nothing specifies how those callers consume the claimed single 5 req/s budget. A weaker implementation can satisfy every frozen test and the local API contract while violating that global rate policy.

   **Concrete fix:** Choose the simplest explicit coordination policy: serialize live SEC network phases under coordinator ownership, or route all such calls through one shared request-budget mechanism. State how the recorded index fetch participates. Do not ask workers to invent distributed rate limiting independently; a documented no-overlap schedule is sufficient for this small corpus. Keep the per-request hook and fake-clock tests, which are now correct.

### D) Verdict

The frozen suite is satisfiable without weakening tests: 373 passes, 2 intentional skips, no failures. Resolve the remaining reference-schema blocker and the six concrete execution/algorithm gaps above before dispatching weaker implementation workers; no redesign of the overall architecture is needed.

proceed-after-fixes

## Round 3

### A) Round-2 finding dispositions

1. **R2.1 resolved**: Event/defined-term insert and update triggers enforce citation identity; defensive view predicates reject moved citations, and edge views now apply their stated agreement policies. All 41 schema tests pass with the exact revised reference SQL.
2. **R2.2 resolved**: The coordinator now owns corpus smoke after Tasks 2 and 3 merge, using the pinned manifest commit and matching shared raw snapshot, with corpus SHA recorded.
3. **R2.3 resolved**: The emitter specifies line flushing before setting page-pending state for both loose `<hr>` and inline break styles; the new mixed inline fixture passes with exact text and page offsets.
4. **R2.4 resolved**: Article-title continuation excludes all section-start patterns, empty article headings produce `article=None`, and all three new section regressions pass.
5. **R2.5 resolved**: Fetch/ingest targets use `--locked`; the coordinator clarified and added a blocking Wave 0 gate requiring the committed freeze manifest, successful hash verification, expected red collection errors, and recorded bootstrap SHA before dispatch. The manifest is not yet generated in this snapshot, so this is resolution by an explicit pre-dispatch gate, not a claim that the gate has already run.
6. **R2.6 resolved**: Each dispatch records its accepted dependency-bearing base SHA; retries without a pushed worker commit start from that base and verify prerequisites and freeze evidence.
7. **R2.7 resolved**: Live SEC phases are serialized under coordinator ownership, with Task 2 waiting for its network window and integration fetch occurring afterward.

### B) Refreshed disposable proof

Created a fresh copy of the current repository at `/tmp/og-astra-round3-pemmt4tm`. Reused the prior disposable TextDoc and fetch implementations, updated only the disposable ingest emitter and section detector to the rev-3 rules, and copied schema.sql, db.py, ground.py, and markers.py directly from the current reference blocks. No repository application or test file was edited.

Ran `uv sync --locked` followed by `uv run --locked pytest -q --junitxml=/tmp/og-astra-round3.xml` under **CPython 3.12.11 / SQLite 3.50.4**. The refreshed implementation passed on its first full-suite run.

| Frozen test file | Passed | Failed/errors | Skipped |
|---|---:|---:|---:|
| `tests/test_textdoc.py` | 19 | 0 | 0 |
| `tests/test_schema.py` | 41 | 0 | 0 |
| `tests/test_fetch.py` | 23 | 0 | 0 |
| `tests/test_ingest.py` | 20 | 0 | 0 |
| `tests/test_ground.py` | 265 | 0 | 2 |
| `tests/test_markers.py` | 17 | 0 | 0 |
| **Total** | **385** | **0** | **2** |

There are **387 collected items**. The schema-plus-marker subtotal is 58, reproducing the coordinator's result. The two skips remain the deliberately excluded single-character fallback property cases. There were no failures to classify as test-wrong or impl-wrong and no test-specific implementation corrections.

All 12 copied test source and fixture files remained byte-for-byte unchanged, verified by SHA-256. Generated `__pycache__` files were excluded from that comparison. Locked Ruff check and format-check of the seven Python test/support files also passed. The scratch implementations and JUnit XML remain outside the repository for inspection. This proof confirms the frozen suite and reference implementations are mutually satisfiable; real SEC recording, corpus smoke, production implementation review, and the newly explicit freeze gate remain the planned execution checks.

### C) New blockers or should-fixes

none

### D) Verdict

All seven Round-2 findings are resolved, with R2.5 enforced through the coordinator's explicit blocking pre-dispatch gate. Proceed under those gates and the revised supervision protocol.

agree-to-proceed
