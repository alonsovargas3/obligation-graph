# ADR-011: Contingent deadlines and deterministic timing

Status: accepted (2026-10-02)

## Context

Wave 5 classifies the timing of every visible obligation and computes the
dates the contracts actually state. ADR-010 left all 525 obligations pending
because the corpus carries relative deadlines whose anchor events carried no
dates, so "what do we owe the landlord in the next 90 days" could name no
trigger. The sizing spike (docs/research/2026-10-02-due-date-sizing.md)
projected eight schedulable obligations, but the advisor's executed
prototype (docs/reviews/2026-10-02-astra-wave5-review.md) showed the truth
is subtler: a perfectly grounded quote can still state a false
relationship. 62 says "prior to the Commencement Date", which is not a
due-on date; 238's date qualifies a condition that creates a termination
right rather than a duty; 159 counts business days the corpus never defines
in calendar terms; 490's offset is redacted. Five obligations support a
dated bound, not eight. The design risk is inventing dates the system
cannot point to, which the invariant forbids, so timing had to be derived
from the already-grounded quotes rather than proposed by a model.

## Decision

- **Deterministic timing over cited quotes, in two stages.** No model is
  involved. `og.timing.parse(doc, evidence)` reads only the obligation's own
  grounded quote and returns what that quote says: construction, relation,
  offset, unit, trigger span, anchor name, and any reason decidable from the
  quote alone. `og.timing.resolve(parsed, anchors, legacy_due)` owns the
  final kind, relation, and bound, given only the cited dated anchors of the
  obligation's own agreement and its recorded base. `defined_dates(doc)`
  finds calendar dates for defined terms from Basic Lease Information rows
  and a closed declaration grammar. Rebuilding the graph replays recorded
  extraction responses at $0 (ADR-010), so timing adds no spend and no new
  hallucination surface: either the quote states the answer or it does not.
- **A closed grammar with a pre-registered stop rule.** The trigger
  lexicons, constructions, number tokens, units, reason precedence,
  trigger-span boundaries, and defined-name rules live in
  `prompts/timing_grammar_v1.yaml`, frozen before implementation from the
  seven filings. Phrasings that occur in none of the filings are documented
  limitations, not blockers; advisor review was capped at three rounds, and
  from round two on only corpus-reproducible issues or missed requirements
  counted as blockers. Aggregate classification counts are descriptive, not
  acceptance: the frozen corpus tests and the independently drafted,
  coordinator-adjudicated timing labels (C14) are.
- **Four kinds, subdividing pending.** `scheduled` means a computable bound:
  a cited dated anchor plus a calendar offset, or an inclusive date bound.
  `contingent` means due relative to a quoted outside event (invoice,
  notice, demand, default, completion, term end, defined event, other
  event) with no computable date; 57 is "no later than thirty (30) days
  following receipt of an invoice therefor", an lte bound of 30 calendar
  days anchored on an unobserved invoice. `unresolved` means the quote has
  timing the system cannot compute; every unresolved row carries a reason
  and never a bound. `untimed` means no timing construction at all, and a
  schema CHECK requires every timing field to be null for it. Lifecycle
  keeps its wave-4 values (superseded, scheduled, pending); timing subdivides
  pending, and pending now means not scheduled and not superseded.
- **Unresolved reasons, from the corpus.**
  - `conditional_or_compound`: 238, "If the Commencement Date Conditions
    have not occurred prior to the Outside Completion Date ... Tenant shall
    have the right to terminate this Lease", dates a condition that creates
    a right, not a duty, so May 31, 2014 is not a termination deadline; 239
    requires notice "prior to the earlier to occur of" completion or ten
    business days after the Outside Completion Date, and selecting the dated
    branch would be wrong even with a holiday calendar. The trigger must
    also be the immediate one: 89 binds to "upon demand", never to the
    historical "as of the Effective Date" in the same sentence.
  - `business_days`: 159, "within ten (10) business days after the Effective
    Date", whose anchor is dated 2011-01-01 yet yields no calendar date, and
    434, "within three (3) Business Days ... once all outstanding fees have
    been paid in cleared funds". The trigger stays quoted and visible; an
    external-event business-day obligation is also unresolved, never
    contingent.
  - `redacted_offset`: 490, "within [***] days after the occurrence
    thereof", and 504, "On or prior to the date that is [***] after the date
    hereof". A redaction always wins over any zero-offset fallback.
  - `unsupported_unit`: 279, a cure period of "one hundred twenty (120)
    hours"; hours are recognized as timing and never converted to days.
  - `cross_reference`: 293, "within the time allowed pursuant to Section
    16.1.1"; no offset is guessed for another section's period.
  - `month_granularity`: 443, "in the month that Host receives the
    Curtailment Program Revenue"; no day within the month is invented.
  - `recurring_schedule`: 214, "$[***] per month for months 85-96 of the
    Term", deferred with the rest of the schedules.
  - `anchor_without_date` (Carbonite's Commencement Date is defined as the
    earlier of two undated events), `anchor_not_found` (260 resolves billing
    disputes "within thirty (30) calendar days" that name no start event),
    `conflicting_dates` (a legacy explicit field or an ambiguous anchor name
    disputes the bound; legacy fields win over derived ones and no disputed
    date is ever used), and `relative_to_other_obligation` (reserved; no
    corpus case yet) complete the list.
- **Relations, not just dates.** Timing carries a relation, one of `lt`,
  `lte`, `eq`, `gte`, `gt`, beside the cited bound. "Prior to" and "before"
  map to `lt`; "on or before", "no later than", and "within N days after"
  map to `lte` (bound = anchor + N); "on" maps to `eq`; bare "after" and
  "following" map to `gt`, a lower bound. `effective_due` keeps its exact
  meaning and is set only for `lte` and `eq` bounds. A strict `lt` bound is
  exposed as `deadline: {relation, date, clause}` and is never shown as a
  due-on date; there is no subtract-a-day conversion, because dates are
  calendar dates at day granularity and the relation is stated with them.
  So 62 and 65 ("completed prior to the Commencement Date", 2011-01-01) and
  236 ("prior to the Target Commencement Date", 2014-04-01) carry strict
  bounds, while 514 ("on or before the 1A Expansion Date", 2012-06-01) and
  519 ("no later than the 3A Suite 409 Amended Surrender Date", 2020-06-30)
  carry inclusive ones; exactly these five rows are scheduled.
  `upcoming_deadlines` selects scheduled rows by deadline date inside the
  window whatever the relation and shows the relation, so strict bounds are
  neither omitted nor double counted.
- **Business days stay unresolved.** The only "Business Day" definition in
  the corpus (Mawson, segment p0023) means a day "other than Saturday,
  Sunday or public holiday" on which banking institutions are open, so
  weekday-only arithmetic would itself be an inferred term and a holiday
  calendar an imported one. The rev-1 weekday exception was cut: a
  business-day offset is unresolved with reason `business_days`, its trigger
  still quoted, and the stored unit is never silently executed as calendar
  addition.
- **Citation rules and evidence ownership.** A trigger span is an exact
  TextDoc slice contained in one of the obligation's own grounded extraction
  citations, in the same agreement. Timing ClauseRefs are owned by
  `obligation_timing.trigger_clause_ref_id`, with
  `clause_ref.obligation_id` left null, so extraction evidence is
  untouched: obligation 128 keeps its original citation and its IoU against
  the reference. An anchor is joined by id to a visible dated event in
  exactly the obligation's agreement or its recorded base, and a scheduled
  row's stored bound must equal that anchor's cited date plus the calendar
  offset, recomputed inside the view; derived dates come only from the view,
  so revoking either citation removes the date everywhere (the swapped 62/65
  citation and the foreign Carbonite event are frozen negatives). The views
  are acyclic by construction: the internal `grounded_obligation` helper
  feeds `visible_obligation_timing`, which feeds `visible_obligation`; the
  literal owner join was rejected by SQLite as circularly defined on the
  real graph. Events from defined-date rows deduplicate by normalized name
  within one agreement: a dated deterministic candidate replaces an undated
  model event of the same name and cites its full declaration, equal dates
  collapse, conflicting dates leave the event dateless, and local ambiguity
  never falls back to a base event. Schema v5 rebuilds rather than migrates
  (ADR-008), so these constraints apply to a replayed graph, not a patched
  one.
- **Recurring schedules are deferred.** Rent rows such as 214 carry real
  timing, but issue #26 Phase 2 owns schedules: one obligation can stand for
  five dated rows (CC 2012's 515), and the period dates sit in adjacent
  table cells the quote does not contain. Such rows are unresolved with
  reason `recurring_schedule`, honestly counted, with no day invented.
  Phase 1's honest yield is the classification itself, not scheduled rows.

## Consequences

"What do we owe the landlord in the next 90 days" now answers with the five
scheduled bounds, relations shown, plus contingent rows that name their
cited trigger, and every remaining row says why it has no computable date
instead of passing silently as pending. The cost is a closed grammar whose
misses surface as unresolved reasons or documented untimed limitations
rather than false dates, and a two-stage contract whose second stage needs
the writer to supply cited anchors. Derived dates live in views that recheck
citations on every read, so readers inherit the invariant instead of
re-implementing it, and the graph remains reproducible by replay at $0.

## Alternatives considered

- **A model classifier for timing:** adds spend and a hallucination surface
  where the grounded quote already states the answer; a later model pass, if
  ever approved, would still be subject to these deterministic rules.
- **One due-on date, subtracting a day for strict bounds:** invents a
  performance date the contract does not state and discards the relation.
- **Schedule whatever a date mentions:** 238 and 239 have perfectly grounded
  spans stating false deadlines; the duty-versus-condition and
  compound-alternative rules reject them.
- **Weekday-only business-day arithmetic:** the only corpus definition
  excludes public holidays, so the arithmetic would import an unstated
  calendar.
- **Call unrecognized constructions untimed:** 279, 293, 434, 490, and 504
  proved "no timing language" false; explicit reasons keep the failure mode
  visible.
- **Two anchor paths with informal precedence:** parsing and cited
  resolution are separate authorities with one rule set each, so SQL, MCP,
  UI, and eval share the same relation and agreement policy.
- **Literal visible-owner joins in the views:** circularly defined on the
  real graph; the dependency split keeps every reader working.
- **Recurring schedules now:** needs per-row recurrences and cited row
  context the current extraction does not emit; deferred to Phase 2.
