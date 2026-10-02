# ADR-009: The change-order diff contract

Status: accepted (2026-10-02)

## Context

Wave 3 diffs a change order against its agreement chain (base, earlier
amendments, the change order) into cited findings. As in extraction
(ADR-008), the model proposes and deterministic verify decides; the writer
is the only code that sets grounded=1. The new risks are specific to diffs:
the amendment may delete a clause of a document the corpus does not hold
(3A deletes "Section 2.C of 2A"), it may restate the old term itself
("scheduled to be surrendered to Landlord on June 30, 2018"), and it invites
derived values the quote never states (an annualized rent). Six gate
questions decide which of six category checks run, and those calls are large
(about 81k input tokens for the 1A chain), so the cost cap must be provable,
not estimated.

## Decision

- **Clause-level findings.** The unit is one finding per (kind, changed
  clause target): one amendment paragraph that renames four suites through a
  single target reference is one supersedes finding. Kinds are supersedes,
  shifted_date, price_change, and potential_conflict; the fourth is reported
  as model-proposed and needing review, requires a grounded old quote in a
  resolved chain document, and never produces edges.
- **Old-side origin: chain, self, or unresolved.** `old_origin` is chain (a
  chain document other than the change order), self (the change order
  restates the prior term, so the old ClauseRef points at the change order),
  or unresolved (the target is named but absent from the corpus, so there is
  no old side). An unresolved target keeps only a `target_label` copied
  verbatim from the new quote; a model that supplies a grounded base quote
  anyway is dropped (`target_not_in_corpus`,
  `target_clause_unresolved`), never silently retargeted.
- **Target resolution through a frozen table.** Explicit targets are
  recognized by a closed pattern (Section, Article, Item, Exhibit, or Table
  of an alias) and resolved through `prompts/change_aliases_v1.yaml`, which
  freezes document aliases and per-target segment ranges pinned to the
  TextDoc hash (Basic Lease Information Item 7, Exhibit A, Table A of
  Exhibit F). Resolution is section (a numbered Section or Article whose
  number must match), range (a table entry; the old span must lie inside
  it), document (an Item, Exhibit, or Table in a corpus document with no
  range entry; kept with no old side), or unresolved (a document outside the
  corpus, such as 2A or the OS Rider; composite aliases like TKD Lease
  count as unresolved). Edges require clause-resolved targets.
- **Dates bound to a role in the source.** A shifted_date needs exactly one
  date token per side, and each token's role (END, START, DELIVERY, PAYMENT)
  is the class of the nearest preceding role word in the containing segment,
  computed on the segment, not the quote; that word must lie inside the
  cited quote, and old and new roles must be equal. A self old side must
  also carry a prior-state cue (currently, scheduled, previously, and the
  like), so a restated term is not paired with the date it supersedes by
  accident.
- **Prices added, not diffed.** A price_change in this corpus is a price
  added or restated: `old_value` is null and there is no delta, because the
  only prior rates for the changed rents are in 2A, which is not filed, and
  cross-document deltas would need subject binding the corpus cannot
  exercise. Each new amount must be a money token of the new quote, may
  carry a grounded context ref for its row period or heading, and currency
  is USD only when the quote has "$".
- **New obligations from extraction; edges from ungated runs only.** New
  obligations are the change order's visible obligations from the wave-2
  extraction pipeline, never a model call. supersedes edges and the
  superseded lifecycle are written only by ungated runs; the eligibility
  view requires a fresh ungated run, a grounded citation in the change
  order, distinct endpoints, the superseding obligation in the change order,
  the superseded one strictly earlier in the chain, and grounded
  same-agreement ClauseRefs on both endpoints. The writer additionally
  requires a clause-resolved target and exactly one overlapping visible
  obligation of the same type on each side; the DB rejects self-edges. A run
  is visible only while its chain snapshot still matches the current
  extraction runs, and the writer re-checks the snapshot vector and every
  span inside its transaction, keeping the previous run on mismatch. Gated
  runs write findings and gate decisions only. Zero edges is an acceptable
  outcome.
- **Paired runs and gated replay.** Every change order runs twice, ungated
  then gated, paired by `pair_id`. The gated run replays the ungated run's
  check outcomes by request fingerprint (the full effective request: system
  text, schema, category definition, model, effort, max_tokens, and the
  chain snapshot vector), in memory even with --no-cache, so its findings
  are a subset by construction and only gate overhead is new. A gated run
  alone requires a stored ungated run with an identical fingerprint;
  replacing an ungated run deletes its paired gated run; the scorer refuses
  unmatched pairs. Reporting keeps actual incremental spend,
  counterfactual recorded check cost, summed original latencies, gate
  overhead, and replay wall time (labeled a replay comparison, not two
  independently timed live pipelines) separate.
- **A provable budget cap.** Before every check or gate call,
  `messages.count_tokens` runs on the complete request including
  `output_config` (C0 verified the count then equals billed input), and the
  budget reserves the worst case: every input token at the model's highest
  input tariff plus max_tokens at the output tariff. A reservation that
  does not fit, a count_tokens failure, or an unknown price stops the run
  (`budget_stop`, sticky for the invocation) with nothing written, and
  settle() replaces the reservation with the priced actual usage, captured
  before status rejection so refused and truncated responses are charged.
  Checks and gates send no server-side fallback, so one call bills at most
  one attempt and the cap is provable. Extraction keeps its
  per-attempt-accounted fallback (ADR-008): its chunked calls are small and
  a fallback response passes the same verify either way, while a hidden
  second attempt on an 80k-token check would double the reserved worst
  case.
- **Pre-registered rules, not tuned ones.** The skip policy was frozen as
  `GATE_POLICY` before any scored run (ADR-003): a skip requires the rules
  tier to find no hit and the classifier tier to return exactly three
  literal False samples with no error. The supersession cue list, the target
  pattern, and the date-role classes are likewise closed; a phrasing that
  occurs in none of the three chain documents is a documented limitation,
  not a blocker. The advisor review ran under its own pre-registered stop
  rule: at most three rounds, and from round two on only issues
  reproducible on the chain documents or required by CLAUDE.md count as
  blockers.
- **Known limitations.**
  - 2A and the OS Rider are named by 3A but not filed, so their clauses
    surface as unresolved targets and changed rents carry no old value or
    delta.
  - Exhibit A's range holds the caption and page footer only; the diagram
    is not in the TextDoc, and no diagram terms are claimed.
  - The cue, target, and date-role grammars are closed lists; phrasings
    outside them drop with logged reasons rather than pass unverified.
  - Each category check makes a single model call, so per-check variance is
    unmeasured in this wave (ADR-006 covers extraction variance).
  - Scoring matches old sides by segment identity, so a checker citing a
    different segment inside the same frozen target range scores as a
    mismatch; the results disclose this strictness.

## Consequences

Findings cite clauses on both sides or honestly report that the old side is
unavailable, so an out-of-corpus deletion reads as such instead of a
plausible invention. Edges are sparse but each one traces to a grounded
clause pair in a chain snapshot that provably matches the store. Gated runs
cannot change graph state, so the recall comparison never corrupts the thing
it measures, and replay makes the gated run nearly free. The cost cap holds
by reservation, at the price of runs that stop incomplete when the worst
case does not fit, which is reported rather than forced. Misses from the
closed grammars appear as drops and mismatches, keeping the failure mode
visible.

## Alternatives considered

- **Document- or paragraph-level findings:** too coarse to cite both sides
  or to point an edge at one obligation.
- **Infer out-of-corpus targets from the base lease:** invents a term the
  corpus cannot point to; the invariant forbids it.
- **Cross-document price deltas:** need subject binding this corpus cannot
  exercise, and the prior rates live in the missing 2A.
- **Edges from gated runs:** gate-skipped categories would silently lack
  edges, making graph state depend on gate answers.
- **Server-side fallback for checks and gates:** an unbilled second attempt
  would break the provable worst case per call.
- **Fuzzy or range-level old-side matching:** would credit near misses;
  strict segment identity with the strictness disclosed is chosen instead.
- **Tune the skip threshold on the labeled set:** with two change orders,
  tuning is memorization; the policy is pre-registered (ADR-003).
