# ADR-003: Fail-open decision gates

Status: accepted (2026-10-01)

## Context

Change orders are expensive to check in full, so bounded yes/no gate questions
decide which checks run. A gate answers before the work, when confidence is
lowest. A missed price change is worse than any token bill, so the failure
mode of a wrong or unsure gate must be defined up front.

## Decision

Gates fail open: low confidence, backend error, timeout, or an unavailable
backend means the downstream full check runs anyway. A gate may skip work; it
may never suppress a finding.

- Three-tier cascade, cheapest first: deterministic rules, a classifier
  backend behind the `DecisionGate` protocol, then the full check.
- Every decision is logged: question, backend, answer, confidence, latency,
  tokens, cost.
- Gate recall is the headline metric, not cost saved. Target 100% recall on the test set; report precision and skipped-check rate alongside. Every change-order eval runs twice, gated and ungated; the ungated run is ground truth for gate recall.
- Thresholds are calibrated to a false-negative target on the labeled set, with a Clopper-Pearson upper bound on miss rate reported honestly, wide as it will be on a small set.

## Pre-registered skip policy (wave 3)

Wave 3 freezes the skip rule before any scored run, and this section
supersedes the calibration sentence in the Decision above. A check is
skipped only when the deterministic tier found no hit and the classifier
tier returned a unanimous three-of-three "no" with no error, failed sample,
or disagreement (`GATE_POLICY = {"samples": 3, "skip": "unanimous_false"}`).
The threshold is not fitted to the labeled set: with two change orders,
calibration would be indistinguishable from memorizing the test set, so the
rule is fixed by policy and every deviation fails open into the full check.

What survives from the superseded sentence: the ungated run remains
mandatory ground truth, misses are still counted against it, and a
one-sided Clopper-Pearson 95% upper bound on the miss rate is still reported
with the miss count and the binomial assumption, however wide two change
orders make it. Reporting names each skip `zero_baseline_skip`,
`confirmed_safe_skip`, or `baseline_miss`, so a skip that hid a finding is
visible as such.

## Consequences

Safety is bought with redundant full checks; the cost log shows what gating
actually saves. Calibration stays honest about small-sample width. Ungated
runs are mandatory, so the baseline is always measured.

## Alternatives considered

- **Fail closed / precision-first:** risks suppressing real findings.
- **Fixed thresholds, uncalibrated:** an unmeasured miss rate is a hidden
  false-negative budget.
- **Cost-first optimization:** optimizes the metric that matters least.
