# Due-date sizing spike (Phase 0 of issue #26)

Date: 2026-10-02. Read-only, no model calls. Data: wave 3 integration graph (`~/Dev/og-integration/data/graph.db`, schema v3, 525 visible obligations, 16 events) and the 7 TextDocs. Scripts were throwaway Python on the devbox (not committed).

## Headline

| Question | Answer |
|---|---|
| Obligations that Phase 1 (defined-date binding) can turn into `scheduled` | 8 of 525 (1.5%) |
| Additional obligations Phase 2 (recurring schedules) can turn into `scheduled` | 25 rent-schedule rows (+1 recurrence-rule obligation) |
| Phase 1 + 2 together | about 33 to 34 of 525 (6.3% to 6.5%) |
| Contingent by nature (timing depends on an external event) | 214 exclusive, about 214 to 245 after correcting the heuristic (41% to 47%) |
| No timing language at all | 205 (39%) |
| Any of the 33 scheduled dates falling after 2026-10-02 | 0 (all fall between 2011 and 2020) |

The yield is small because the corpus is mostly covenants, not dated payments, and the two largest leases are either fully dated and expired (Constant Contact 2011) or redacted with a by-reference Commencement Date (Carbonite). The honest user-facing gain from this work is mostly the `contingent` / `unresolved` classification, not scheduled rows.

## Method and heuristics

Per obligation I used the grounded `clause_ref.span_text` (the quote), `obligation.trigger`, `obligation.description`, and the containing TextDoc segment (looked up by `char_start`). All 525 obligations have exactly one grounded clause_ref in the same agreement, so the join is 1:1.

| Signal | Heuristic | Likely error direction |
|---|---|---|
| Timing language (any) | Quote contains an absolute date, an "N days/months/years" phrase, or a timing word (within, no later than, on or before, prior to, following, upon, promptly, monthly, annually, per month, first day, anniversary, until, throughout, and similar), or `trigger` is populated | Over-counts: "throughout", "prior to", "upon" also appear in non-deadline text. Under-counts nothing obvious |
| Cat 1, defined date | Quote names a defined term that I verified by hand has a concrete calendar date in the TextDoc (list in the defined-date table), or the quote has an absolute date | Over-counts: 4 of 18 hits are false positives (the term is mentioned but is not a deadline anchor) |
| Cat 2, recurring dated schedule | Payment whose quote has a period (date range, "months N to M of the Term", or "period commencing ... expiring ...") plus a `$` amount, `[***]`, or "per month". Then I also looked 900 characters past the quote for dated rent tables | Under-counts: tables whose rows are not separate obligations (CC 2012 has one obligation for a 5-row table) |
| Cat 3, contingent | Quote contains an event keyword (notice, demand, request, receipt, invoice, default, breach, failure, termination, expiration, surrender, completion, delivery, power-on, acceptance, if / in the event) and timing language, and is not already a cat 1 offset | Mixed. Over-counts bare "if" and "delivery" hits; under-counts approvals, payments of fees, outage events (see spot checks). Net: probably a slight undercount |
| Recurrence words | monthly, quarterly, annually, per month, each month, first day of each, /month, per year | Under-counts recurrence stated in a different segment from the quote (rent rule 3.1 is its own obligation) |

Buckets in the per-document table are exclusive with precedence cat 2, cat 1, cat 3, other timing, none. Non-exclusive counts are also given. I adjusted five payment rows (CC 2012 #515, Endurance #520 to #523) into cat 2 by hand-confirmed neighbor context, because their date ranges sit in adjacent segments or table cells rather than in the quote.

## Per-document table

Exclusive buckets (rows sum to total).

| Document | Total | Any timing | Recoverable via defined date or absolute date (cat 1) | Recurring, dated or term-indexed schedule (cat 2) | Contingent (cat 3) | Other timing (vague or term-scoped) | No timing |
|---|---:|---:|---:|---:|---:|---:|---:|
| applieddigital-2026-ex101 | 25 | 14 | 0 | 0 | 13 | 1 | 11 |
| carbonite-2014-ex1024 | 202 | 127 | 4 | 13 | 84 | 26 | 75 |
| constantcontact-2011-ex1041 | 166 | 106 | 4 | 20 | 66 | 16 | 60 |
| constantcontact-2012-ex101 | 5 | 2 | 1 | 1 | 0 | 0 | 3 |
| endurance-2017-ex106 | 7 | 5 | 1 | 4 | 0 | 0 | 2 |
| mawson-2025-ex101 | 87 | 49 | 0 | 0 | 37 | 12 | 38 |
| terawulf-2025-ex10-1 | 33 | 17 | 0 | 0 | 14 | 3 | 16 |
| Total | 525 | 320 | 10 | 38 | 214 | 58 | 205 |

Notes: "Any timing" is the unadjusted count (CC 2012 and Endurance schedule rows are not in it). The cat 1 column excludes cat 2 rows. Non-exclusive cat 1 hits are 18 (6 Carbonite, 8 CC 2011, 2 CC 2012, 2 Endurance); 6 obligations are both cat 1 and contingent. Statuses: 506 active, 19 redacted (17 Carbonite, 2 Applied Digital). No obligation has a populated `anchor_event_id` or `due_date`; 94 have a `trigger` string (Carbonite 33, CC 2011 28, Mawson 21, TeraWulf 6, Applied Digital 6).

## 1. Defined dates

Status key: concrete = the TextDoc states a calendar date; by reference = defined from another event or term; external = known only when an event happens; blank = placeholder or redacted. "Obligations" counts obligations whose quote, trigger, or description names the term (term in quote in every case).

| Doc | Term | Status | Exact source text | Obligations |
|---|---|---|---|---:|
| CC 2011 | Effective Date | concrete (BLI row) | `4. Effective Date/ Commencement Date: (a) Effective Date: January 1, 2011 (b) Commencement Date: January 1, 2011` | 2 |
| CC 2011 | Commencement Date | concrete (same BLI row). No `event` row exists for it | same row as above | 6 |
| CC 2011 | Term | by reference, computable | `Term: Approximately seventy-two (72) full calendar months (i.e., commencing on the Commencement Date and expiring on the last day of the seventy-second (72nd) full calendar month thereafter).` The lease's own example: `the seventy-two (72) full calendar month Term of this Lease would commence January 1, 2011, and expire on December 31, 2016.` | 37 mention "Term" (almost all are "throughout the Term", not deadlines) |
| CC 2011 | Suite 1.5 Expiration Date | by reference (upper bound only) | `"Suite 1.5 Expiration Date" shall mean and refer to the earlier to occur of (a) the last day of the twenty-fourth (24th) month of the Term of the Lease, and (b) the earlier termination of this Lease.` | 2 |
| CC 2011 | Suite 1.5 Surrender Date | by reference | `... the later to occur of (a) the Suite 1.5 Expiration Date, and (b) the date on which Tenant has surrendered the Suite 1.5 Tenant Space to Landlord ...` | in the same 2 |
| CC 2011 | Deadline Date | by reference, blank anchor | `"Deadline Date" shall mean and refer to the date that is thirty (30) days following the latest date of execution as set forth on the signature page attached hereto.` Signature page: `Executed as an instrument under seal as of the ____ day of _________________, 2011.` | 1 |
| CC 2011 | New Pathway Completion Date | external | `"New Pathway Completion Date" shall mean and refer to the date of the New Pathway Completion Notice.` | 1 |
| CC 2011 and Carbonite | Delinquency Date | rule on another date | Carbonite: `the date that is five (5) days after the date on which any particular payment of Rent is due from Tenant to Landlord.` | 2 |
| Carbonite | Early Access Date | concrete (already bound as an event) | `"Early Access Date" shall mean and refer to February 1, 2014.` | 0 |
| Carbonite | Effective Date | concrete | `(a) Effective Date: December 31, 2013 *(being the latest of the parties' respective dates of execution of this Lease, as set forth on the signature page of this Lease, the "Effective Date")` | 2 (both are false positives, see below) |
| Carbonite | Target Commencement Date | concrete | `(b) Target Commencement Date: April 1, 2014.` | 1 |
| Carbonite | Outside Liquidated Damages Date | concrete | `(d) Outside Liquidated Damages Date: May 1, 2014.` | 0 |
| Carbonite | Outside Completion Date | concrete | `(e) Outside Completion Date: May 31, 2014.` | 2 |
| Carbonite | Early Delivery Date | blank | `(c) Early Delivery Date: Not applicable.` | 0 |
| Carbonite | Commencement Date | by reference (event-driven) | `The "Commencement Date" shall mean the earlier of: (x) the date upon which Landlord has completed the Commencement Date Conditions; or (y) the date Tenant commences to use the Premises for the Permitted Use.` | 6 |
| Carbonite | Initial Term | by reference | `The "Initial Term" shall mean and refer to approximately forty eight (48) full calendar months (i.e., commencing on the Commencement Date and expiring on the last day of the forty eighth (48th) full calendar month thereafter)` | 27 mention "Term" |
| Carbonite | Warranty Expiration Date | by reference | `The "Warranty Expiration Date" shall be defined as the date twelve (12) months after the Commencement Date.` | 0 |
| Carbonite | Base Rent amounts | blank (redacted) | `$[***] per month for the period commencing on the Commencement Date and expiring on the last day of the third (3rd) full calendar month of the Term of the Lease.` | 14 redacted payment obligations |
| Mawson | Effective Date | concrete | `This Master Colocation Agreement (the "Agreement") is made on March 16, 2025 ("Effective Date")` | 0 |
| Mawson | Initial Date | external | `"Initial Date" means the date on which the Colocation Servers under the Service Order, or the first batch of Colocation Servers if there are more than one batch under the Service Order, are powered-on for normal Colocation and operation.` | 1 |
| Mawson | Initial Term | by reference to an external date | `expiring on the third (3rd) anniversary of the Initial Date (the "Initial Term" and together with the Holdover Period the "Term")` | 2 mention "Term" |
| TeraWulf | Effective Date | concrete (note: the agreement is flagged `is_form`) | `entered into as of this 13th day of August, 2025 (being the latest of the parties' dates of execution; the "Effective Date")` | 0 |
| TeraWulf | Term of the Fluidstack Lease | not stated in this document | `the Term of the Fluidstack Lease will be automatically extended for a Transition Period ... (the length of such period to be defined by Google, but not to exceed 120 days)` | 0 |
| Applied Digital | Springing Event Trigger Date | external | `(the date of such occurrence, the "Springing Event Trigger Date")` | 1 |
| Applied Digital | Lease Term | not stated in this document | Guaranty is `made as of March 30, 2026`; the lease dates sit in other documents | 0 |
| CC 2012 | 1A Expansion Date | concrete (parenthetical) | `Effective as of June 1, 2012 (the "1A Expansion Date", Original Suite 418A is hereby expanded ...` | 2 |
| CC 2012 | 1A Effective Date | by reference (signature page) | `as of (but not necessarily on) the latest date of execution shown on the signature page hereto (the "1A Effective Date")` | 0 |
| CC 2012 | Commencement Date | cross-document | `commencing on the Commencement Date, the Premises shall consist of ...` (the date lives in the CC 2011 lease: January 1, 2011) | 0 |
| Endurance | 3A Suite 409 Amended Surrender Date | concrete (parenthetical after a range) | `commencing July 1, 2018 and expiring June 30, 2020 (the "3A Suite 409 Amended Surrender Date")` | 1 |
| Endurance | 3A Effective Date | by reference (signature page) | `as of (but not necessarily on) the latest date of execution shown on the signature page hereto (the "3A Effective Date")` | 0 |

Of the 16 extracted events: 5 have a concrete date in the text (Early Access Date, Carbonite Effective Date, Mawson Effective Date, 1A Expansion Date, 3A Amended Surrender Date); only the first is bound today. Only 3 obligations reference those 4 unbound events, and 2 of those are false positives. The larger gap is events that were never extracted: CC 2011 Commencement Date and Effective Date, Carbonite Target Commencement Date, Outside Completion Date, and Outside Liquidated Damages Date have concrete dates but no `event` row. So Phase 1 needs event coverage (derive events from BLI rows) as much as new declaration grammar.

### The 18 cat 1 hits, classified by hand

| Class | Ids | Count |
|---|---|---:|
| Real deadline on a concrete date, schedulable in Phase 1 | 62, 65 (complete installation prior to the Commencement Date, Jan 1 2011); 159 (Memo of Lease within 10 business days after the Effective Date); 236 (satisfy conditions prior to Target Commencement Date, Apr 1 2014); 238 (right to terminate if not occurred prior to Outside Completion Date, May 31 2014); 239 (notice within 10 business days after Outside Completion Date); 514 (completion on or before the 1A Expansion Date, Jun 1 2012); 519 (surrender no later than Jun 30 2020) | 8 |
| Rent schedule lead-in, belongs to Phase 2 | 37, 39, 45, 51 (CC 2011); 515 (CC 2012); 520 (Endurance) | 6 |
| False positive, term named but not a deadline | 89 (indemnity), 265 (statement for the year in which the Effective Date occurs), 284 (document dated Dec 30, 2011), 399 (price as of the Effective Date) | 4 |

Two of the 8 (159 and 239) use business days, which `offset_days INTEGER` in calendar days cannot represent exactly.

## 2. Recurring payments

- Payment obligations: 152 (CC 2011 54, Carbonite 58, Mawson 21, TeraWulf 10, Applied Digital 4, Endurance 4, CC 2012 1).
- Quote states a recurrence word: 44 (50 when the containing segment is included).
- Quote sits in a rent schedule row (period plus amount): 33 in the quote (CC 2011 20, Carbonite 13), plus 5 dated rows found through neighbor context (CC 2012 1, Endurance 4). Total 38.
- Absolute-dated period inside a quote: 0. Every dated schedule row (CC 2012, Endurance) has its dates in an adjacent segment or cell, not in the obligation's quote. That matters for Phase 2: the date range must be cited from row context, as the issue already proposes.
- The recurrence rule itself, "Base Rent shall be paid ... in monthly installments in advance on the first day of each and every calendar month throughout the Term", is a separate obligation in two leases: #68 (CC 2011, p0576) and #247 (Carbonite, p0779). Schedule rows state only "per month".

Examples:

| Id | Segment | Quote (shortened) | Schedulable |
|---|---|---|---|
| 44 | p0467 | `$51,123.99 per month for months 61 to 72 of the Term.` | Yes, with Commencement Date January 1, 2011 (rows span months 1 to 72, 2011 to 2016) |
| 37 | p0455 | `$33,428.11 per month for the period commencing on the Commencement Date and expiring on the last day of the twelfth (12th) full calendar month of the Term of the Lease.` | Yes, same anchor |
| 520 | p0014 | `Tenant agrees to pay Base Rent, as it relates to Suite 409, during the 3A Suite 409 Extended Term ... according to the following schedule:` rows `July 1, 2018 - December 31, 2018 | $35,596.80/month`, `January 1, 2019 - December 31, 2019 | $36,664.70/month`, `January 1, 2020 - June 30, 2020 | $37,764.65/month` | Yes, fully dated (rows are #521 to #523, segments p0018, p0020, p0022) |
| 515 | p0039 | `Effective as of the 1A Expansion Date, Tenant hereby agrees to pay the following amounts ...` then five dated rows from `June 1, 2012 - January 31, 2013 (months 18 - 25 of the Term) $0.00/month` to 2016 | Yes, but one obligation stands for five periods, so extraction must emit per-row recurrences |
| 204 | p0596 | `$[***] per month for the period commencing on the Commencement Date and expiring on the last day of the third (3rd) full calendar month ...` | No: amount redacted and the Commencement Date is event-driven |

Carbonite's 13 schedule rows (plus one rule, #247) cannot schedule: amounts are `[***]` and the anchor is by reference. CC 2011's 20 rows split across Suites 1.5, 1.5.1, 1.5.2 and others; row #38 expires on the Suite 1.5 Expiration Date, which is an upper bound only (it may end earlier on termination). Other CC 2011 payment dates are contingent (30 days after invoice, demand, or receipt) or unrelated to the signature date, which is blank (Prepaid Rent #58 is due on execution).

Phase 2 candidates: 20 (CC 2011) + 1 (CC 2012) + 4 (Endurance) = 25 rows, plus the rule obligation #68 for day-of-month, so 26.

## 3. Contingent

214 obligations exclusive, 222 non-exclusive (an obligation can carry two categories). Keyword groups over the quote (obligations may match several):

| Trigger group | Obligations |
|---|---:|
| notice, demand, request, notify | 139 (120 in the strict set) |
| if / in the event / provided that / upon occurrence | 82 |
| termination, expiration, surrender, cancel | 71 |
| receipt, receiving | 52 |
| completion, delivery, acceptance, power-on | 41 |
| exercise, election, option | 36 |
| invoice, statement, bill | 35 |
| default, breach, failure to, delinquency | 33 |
| casualty, condemnation, force majeure | 15 |
| assignment, transfer, sublease | 12 |
| Springing Event, draw, letter of credit | 10 |

Most common literal phrases ("N" stands for the spelled number; parties normalized):

| Phrase | Count |
|---|---:|
| within N days of / after `<party>` demand therefor | 9 |
| within N days following the date upon which `<party>` received ... | 4 |
| within N days after written request by `<party>` | 3 |
| within N days following `<party>` receipt of such statement | 3 |
| within N days after `<party>` receipt of an invoice | 2 |
| within N days after occurrence of a chronic or continuous outage | 4 |
| within N days of delivery of each generator fuel (delivery) | 2 |
| upon an Event of Default | 2 |
| prior to the expiration of each such policy | 2 |
| within N days after receipt of written notice from `<party>` | 2 |

Examples: CC 2011 #57, `no later than thirty (30) days following receipt of ...` an invoice; TeraWulf #11, `within 15 days after the receipt of the Akela Termination Notice (including the associated invoice)`; Applied Digital #509, `shall be paid by Guarantor within thirty (30) days after written demand`.

## 4. Undated by nature versus recoverable

The per-document table above is the answer. In summary, of 525:

| Bucket | Count | Share |
|---|---:|---:|
| Recurring dated or term-indexed schedule (cat 2) | 38 | 7.2% |
| Defined-date recoverable (cat 1) | 10 (+ the 6 lead-ins already in cat 2 and 2 false positives in "none") | 1.9% |
| Contingent (cat 3) | 214 | 40.8% |
| Other timing: vague ("promptly", "timely", "at all times") or term-scoped | 58 | 11.0% |
| No timing language | 205 | 39.0% |

Of the 38 cat 2 rows, 25 are actually schedulable (20 CC 2011, 1 CC 2012, 4 Endurance); 13 Carbonite rows are not.

## Spot checks (20 random obligations, read by hand)

Sample 1 (random seed 7, any bucket) and sample 2 (seed 11, cat 3 and other timing only).

| Id | Heuristic bucket | My reading | Verdict |
|---|---|---|---|
| 332 | none | SNDA efforts covenant, no time | correct |
| 155 | cat 3 | security transferred on a successor's interest | correct |
| 405 | other | fees may be incurred only after prior written approval, an event dependency | wrong, contingent |
| 50 | cat 2 | `$51,123.99 per month for months 61 to 72 of the Term` | correct |
| 75 | none | keep books and records | correct |
| 97 | cat 3 | 30 days after receipt of audit report | correct |
| 375 | cat 3 | upon an Event of Default | correct |
| 60 | none | leases for the Term, no distinct deadline | correct |
| 520 | cat 1 (adjusted to cat 2) | dated schedule lead-in | correct after adjustment |
| 220 | none | cost at provider contract cost | correct |
| 434 | other | within 3 Business Days once fees are paid | wrong, contingent |
| 448 | cat 3 | if Host fails to remedy within 14 days | correct |
| 492 | cat 3 | on request after rejection | correct |
| 197 | cat 3 | on a Continuous Outage | correct |
| 194 | other | credit applied in the month after an outage | wrong, contingent |
| 498 | other | immediately deliver any payment received | wrong, contingent |
| 463 | cat 3 | reimburse costs if material | borderline, conditional rather than dated, accept |
| 195 | cat 3 | notice after cure | correct |
| 106 | cat 3 | 30 days after Landlord's demand | correct |
| 430 | other | within 5 Business Days before each payment due date | arguably relative to a recurring date; accept |

Result: 16 of 20 correct or accepted, 4 wrong. All 4 errors sit in "other timing" and should be contingent. No error crossed into cat 1 or cat 2, which are the buckets that drive the yield. So the contingent estimate is a slight undercount. If 0 to half of the 58 "other timing" rows are really contingent (the 4 sampled other-timing rows were 3 contingent, but the wider sample of 14 mostly showed vague covenants), the range is 214 to about 245. Separately, 4 of the 18 cat 1 hits (22%) are false positives, already removed from the yield above.

## Yield estimate

| Phase | What becomes `scheduled` | Obligations | Share of 525 |
|---|---|---:|---:|
| 1. Bind defined dates | 62, 65, 159 (CC 2011 Commencement Date and Effective Date); 236, 238, 239 (Carbonite Target Commencement and Outside Completion Dates); 514 (1A Expansion Date); 519 (3A Amended Surrender Date) | 8 | 1.5% |
| 2. Recurring schedules | 20 CC 2011 rent rows, 1 CC 2012 lead-in, 4 Endurance rows; rule #68 supplies the day of month | 25 (+1 rule) | 4.8% (5.0%) |
| Total scheduled | | 33 to 34 | 6.3% to 6.5% |
| Contingent, classified with cited trigger | | about 214 to 245 | 41% to 47% |
| `unresolved` (a defined date exists but does not bind) | Carbonite Commencement Date, CC 2011 Deadline Date: none of these have a date to bind. The class would be near empty after Phase 1 | about 0 to 5 | under 1% |
| No timing or vague timing, correctly undated | | 205 + the rest of 58 | about 45% |

Caveats on the totals:

- Phase 1's 8 depend on first creating events that do not exist (CC 2011 Commencement Date, Carbonite Target Commencement Date and Outside Completion Date). Binding only the 4 unbound events already in the table would schedule just 2 real obligations (514, 519).
- Upper bound for Phase 1: the issue counts 57 anchors the model proposed without an offset (`anchor_without_offset`). They were dropped before storage, so they are not in the 525; I cannot size them here. If many were "N days after Commencement Date" in CC 2011, Phase 1 could grow by up to tens of obligations, but only where the anchor date is concrete (CC 2011, CC 2012, Endurance, Carbonite's BLI dates).
- Carbonite (the largest document at 202 obligations) yields almost nothing: its Commencement Date is event-driven and its rent is redacted.
- Mawson, TeraWulf, and Applied Digital yield 0 scheduled rows. Mawson's Initial Term runs from a power-on date; TeraWulf and Applied Digital state no lease term.

## Risks

1. **Everything schedulable is historical.** The 33 scheduled obligations carry dates from 2011 to 2020 (CC 2011 term ends December 31, 2016). Acceptance says `upcoming_deadlines(party="landlord", as_of=..., days=90)` returns scheduled rows; with today's date it returns none. The demo needs an explicit historical `as_of` (for example 2011-01-01 to 2012-06-01 for the CC chain) and the README must say why.
2. **Business days.** About 27 obligations use "business days"; the schema stores `offset_days` as calendar days. Either exclude business-day offsets from `scheduled`, or add an explicit unit field and a calendar rule that is itself cited. Guessing a holiday calendar breaks the invariant.
3. **Defined dates that are targets, not commitments.** "Target Commencement Date" (April 1, 2014) is a concrete date, but the Commencement Date is the earlier of event-driven conditions. Do not let a target date stand in for the real anchor.
4. **Upper-bound dates.** The Suite 1.5 Expiration Date is the earlier of month 24 or earlier termination; the Term end is "approximately 72 months" with a partial-month adjustment. Schedule from the stated example only, and label as the stated term.
5. **One obligation, many periods.** CC 2012 states five dated periods in one obligation. Phase 2 extraction must emit one recurrence per row, or the schedule loses rows.
6. **Redacted rent.** Carbonite rows would schedule a date with no amount. They should stay `redacted` with the period shown, never an inferred amount.
7. **Form and blank dates.** TeraWulf is flagged `is_form` yet shows a filled Effective Date; CC 2011's signature page is blank. Confirm form handling before binding dates from a form, and do not bind to a blank signature date (Deadline Date).
8. **Heuristic precision.** Cat 1 had 22% false positives; contingent is a slight undercount. Phase 1 needs the frozen-test treatment the issue proposes, with these 18 hits and the 4 false positives as the first frozen cases.
9. **Cross-document anchors.** The CC 2012 Commencement Date is defined in the CC 2011 lease. The `visible_obligation` view already allows base-agreement events, so this is feasible, but only if the event is extracted in the base document first.
10. **Sampling.** 20 spot checks bound the error rate loosely (4 of 20 wrong, all in one direction); the per-bucket counts are good to roughly plus or minus 10 percent for the contingent and other-timing buckets, and exact for cat 1 and cat 2 because those were fully hand-classified.
