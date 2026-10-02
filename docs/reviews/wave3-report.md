# Wave 3 report (2026-10-02)

**Scope:** CLAUDE.md build steps 7 (change-order diff) and 8 (decision gates), plus the change-order half of step 11 (eval).

**Roles:**
- **Coordinator:** Opus 5.5.
- **Advisor:** Codex gpt-6-astra. It ran 3 plan rounds under a pre-registered stop rule, with 21 findings, all accepted, and agreed to proceed in round 3.
- **Implementers:** Pi on zai/glm-5.3, supervised through Orca on the devbox. The Grok fallback was not needed.
- **Reference set:** drafted blind by gpt-6-astra and adjudicated by the coordinator with no changes. The user spot-checked all 12 gate labels and accepted them.

## Merged

| PR | Task | Notes |
|----|------|-------|
| #17 | Task 21: ADR-009, ADR-003 pre-registered skip policy | |
| #18 | Task 14: RulesGate | lexicon and base-section references; the signature block is excluded |
| #19 | Task 16: change check client | `count_tokens` reservation, no fallback, allowlisted cache |
| #20 | Task 15: HaikuGate, JevGate slot, fail-open cascade | skip only on 3/3 literal "no" |
| #21 | Task 18: change writer and re-extraction invalidation | snapshot, hash, and span recheck in one transaction |
| #22 | Task 17: change verify | target ranges, date roles, price rules |
| #23 | Task 20: change reference loader and paired scorer | |
| #24 | Task 19: `og.change` CLI, chain snapshot, ChangeReport | includes a Task 17 bug fix found by the frozen CLI tests |
| #25 | rev 2.3 fixes | price values with units; a stray price label becomes a correction |

The suite has 1,122 tests passing, all frozen before implementation.

## What the live run caught (C7, rev 2.3)

The first live run completed, but **every proposed price finding was dropped**. That was 8 correct rent amounts across both amendments. There were two causes, both mismatches between the frozen prompt and the verifier:

- **Amounts written with units.** The schema asks for the amount exactly as written (`$41,496.00/month`), but verify accepted only a plain decimal.
- **A stray target label on a price finding.** The model attached "Section 4 of 2A" to each 3A rent cell, and the label rule dropped the whole finding. Price findings never store a label. The label is now discarded and logged as a correction, and the finding is kept.

Both fixes were pinned first by frozen replay tests built from the recorded real responses (`tests/fixtures/api/change_v1/`). Rerunning cost only the Haiku gates, because the check responses were cached.

## Results

All numbers come from `eval/results/2026-10-02-change-*.json`. Prompt `change_v1`; checks on `claude-sonnet-5-5` at effort high; gates on `claude-haiku-4-5-20251001` with 3 samples.

**Change findings.** Gold and predicted counts are in finding units; matching is strict segment identity (rev 2 R9).

| Change order | Gold | Predicted | TP | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| 1A (First Amendment) | 10 | 10 | 8 | 0.80 | 0.80 |
| 3A (Third Amendment) | 7 | 4 | 4 | 1.00 | 0.57 |

**1A per kind:**
- Price changes are 5/5, with every amount, currency, and row context correct.
- Supersessions are 3 of 4. The miss and both false positives are strict-matching artifacts. The checker cited the right amendment clause each time, but a different old segment inside the same target:
  - 1A `p0012` → base `p0448` instead of `p0451`;
  - 1A `p0037` → `p0888` (the Table A caption) instead of `p0893`.
- The one potential conflict (1A `p0035` vs base `p0721`) was not proposed.

**3A per kind:**
- The shifted date is 1/1: surrender moves June 30, 2018 → June 30, 2020, **+731 days**, with the old date cited from the amendment's own recital.
- Price changes are 3/3, with no old value or delta, because the prior rates are in 2A, which is not in the corpus.
- Supersessions are 0/3:
  - The checker did not propose the two deletions whose targets are in 2A (`Section 1.A of 2A`, `Section 2.C of 2A`).
  - The notice-address replacement (`p0023`) was proposed but dropped, because the quote clipped the "Notwithstanding anything in the Lease to the contrary" cue.

**Gates** (pre-registered skip rule: rules miss plus a unanimous 3/3 Haiku "no"):

| Change order | Skipped checks | Skip type | Cascade recall vs reference | Cascade recall vs ungated |
|---|---|---|---|---|
| 1A | guarantee | `confirmed_safe_skip` | 5/5 (miss bound ≤ 0.45) | 3/3 (≤ 0.63) |
| 3A | guarantee, sla | `confirmed_safe_skip` ×2 | 3/3 (≤ 0.63) | 2/2 (≤ 0.78) |

- **Skip safety:** all 3 skips are confirmed safe. The ungated check found nothing in that category, and the user-checked reference label is "no".
- **No recall loss:** there were no gate misses on either reference. Gated findings equal ungated findings (retention 1.0).
- **Miss bounds:** the bounds are one-sided Clopper-Pearson 95% upper bounds on the miss rate. They are wide, as they must be with 2 to 5 positives per document.
- **Haiku coverage:** Haiku was consulted only where the rules found no hit (1 of 6 questions on 1A, 2 of 6 on 3A), and all of those were negatives. Its standalone recall is therefore undefined (null), not 100%.
- **Disagreement with the reference:** there is one. On 3A termination the rules fired ("surrender", "default" in the estoppel) where the reference says no. That costs only a redundant check, never a missed finding.

**Cost** (recorded usage, `PRICES_2026_10`):

| Change order | Ungated (all 6 checks) | Gated (checks run + gates) | Gate overhead |
|---|---:|---:|---:|
| 1A | $0.385 | $0.378 | $0.013 |
| 3A | $0.371 | $0.346 | $0.017 |

- **Small savings.** Each check reuses a ~96k-token cached chain prefix, so the skipped checks were the cheap ones (10 to 104 output tokens). Gating saves 2 to 7% here; the savings would grow with longer check outputs.
- **Latency.** Gated latency in the results files is a replay of cached checks, not an independent live pipeline, and is labeled as such.
- **Spend.**
  - **Wave 3 actual spend:** about $0.82 (C0 probe $0.005, first C7 run $0.785, rerun $0.029).
  - **Total project spend:** about **$4.20 of $5**.

**Graph:** the ungated runs wrote **zero supersession edges**. No replacement clause overlaps exactly one visible obligation on each side, which Astra predicted in round 1. Edges are optional by rev 2 R11. Every finding is still visible at clause level, with grounded ClauseRefs on both sides or a cited out-of-corpus target.

## Definition of done: change-order demo

| Criterion | Met by | Status |
|---|---|---|
| At least one supersession | 1A Exhibit A replaced (`p0017` → base `p0808`), Item 7 restated (`p0019` → `p0442`), Table A of Exhibit F replaced (`p0037` → `p0893`) | met |
| At least one shifted date or price | 3A surrender June 30, 2018 → June 30, 2020 (+731 days); 8 rent amounts with row context | met |
| At least one gate skip the ungated run confirms was safe | 1A guarantee; 3A guarantee and SLA | met (3) |

## Known limitations (documented, not blockers)

- **The Second Amendment (2A) and the OS Rider are not filed in the corpus.** Their clauses appear as unresolved targets, and 3A's changed rents carry no old value or delta.
- **The checker missed both 2A deletions in 3A.** Single-sample checks (one model call per category) leave per-check variance unmeasured.
- **Strict segment-identity matching undercounts 1A.** Two correct clause pairs cite a neighboring old segment inside the same target.
- **Closed grammars.** The cue, target, and date-role grammars are closed lists. A clipped cue drops the finding (3A `p0023`); it is never accepted unverified.
- **Small gate samples.** The gate metrics come from two related amendments with small positive counts. They are reported as measured on this pair, not as a calibrated safety rate.
- **Exhibit A's diagram is not in the TextDoc.** Only its caption is cited.
