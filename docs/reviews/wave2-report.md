# Wave 2 report (2026-10-02)

Scope: CLAUDE.md build step 5 (extract, verify, store) plus the extraction half of step 11 (score). Coordinator: Opus 5.5. Advisor: Codex gpt-6-astra, 6 plan rounds ending under a user-approved stop rule. Implementers: Pi on zai/glm-5.3, supervised through Orca on the devbox; the Grok fallback was not needed. Reference set: model-drafted (gpt-6-astra, blind to extraction output), adjudicated by the coordinator, 12 labels spot-checked by the user and accepted as-is.

## Merged

| PR | Task | Notes |
|----|------|-------|
| #7 | ADR-008 extraction contract | one review round-trip |
| #8 | Task 6 TOC sections | 67 duplicate section numbers removed |
| #9 | Task 9 writer | the only code that sets `grounded = 1` |
| #10, #12 | Task 7 chunk/prompt/client/cache, attempt-model fix | #12 fixed against the live API shape recorded in C1 |
| #11 | Task 10 reference loader, scorer, score CLI | exact maximum-cardinality matching |
| #13, #15 | Task 8 verify (rev 2.5, then rev 2.6) | every rule revision pinned by frozen tests first |
| #14 | Task 11 `make extract` | |
| #16 | rev 2.7 fixes | label-form parties, `python -m og.eval` guard, incremental cost |

## What the live API and the real corpus caught

These were found only by C1/C3, not by the offline tests:

- **Schema rejected by the API (400).** The frozen output schema used nullable enums as `type: [string, null]`, which the API rejects. It was fixed with `anyOf` before any corpus run.
- **Attempt model shape.** `usage.iterations[].model` is null when no fallback runs. Every attempt would have been priced as an unknown model.
- **No parties bound in the CC lease.** Its parties appear only as `Landlord: NAME, a Delaware … company.` label rows. Rev 2.7 added that production, taking payer coverage from 0% to 100%.
- **`python -m og.eval` did nothing.** The module was missing its `__main__` guard, which in-process tests cannot see. A subprocess test now covers it.
- **Cost reporting.** Cache replays were counted as spend. `incremental_cost_usd` now separates real calls.

## Results

All numbers come from `eval/results/2026-10-02-extract-*.json`, on prompt `extract_v1@6de99191`, model `claude-sonnet-5-5`, effort high.

**Corpus run:** 7 documents, 72 chunks, all ok. 525 obligations. Incremental cost $2.13.

**Reference lease** (constantcontact-2011-ex1041; 50 reference obligations; scope sampled), over n = 3 samples:

| Metric | Mean | Range |
|--------|-----:|------:|
| Recall (micro) | 0.807 | 0.80 to 0.82 |
| Recall (macro over types) | 0.839 | 0.82 to 0.87 |
| Precision (lower bound only; the set is not exhaustive) | 0.27 | 0.25 to 0.28 |
| Payer (`owed_by`) accuracy on matched items | 0.95 | 0.93 to 1.00 |
| Proposals passing verify | 0.94 | 0.93 to 0.97 |
| Integrity (visible obligations without a grounded same-agreement quote) | 0 | 0 |

ADR-006 asks for 5 variance samples. 3 were run to stay within the $5 API budget (total spend about $3.38).

## Known limitations (documented, not blockers)

- **Date and role binding are conservative heuristics** over a closed declaration grammar (rev 2.4 to 2.7). Semantic correctness of extracted terms is measured by eval, not proven. The quote-existence invariant is enforced deterministically.
- **Parties bind in only 2 of 7 filings.** The others use declaration layouts the grammar does not cover (cover pages split across lines, other preamble forms). Their payer and payee stay unresolved (NULL) rather than guessed.
- **Relative deadlines did not resolve on the reference lease** (0 of 5). Their anchors are phrases ("receipt of an invoice"), not defined events.
- **The CC 2011 table of contents spans 3 pages,** leaving 3 orphan TOC entries outside the TOC section.
- **Refused or truncated chunks record no usage,** so the cost of rare refusals is not counted. None occurred in this run.
