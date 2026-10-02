# C14 timing label adjudication (2026-10-02)

The user chose model review instead of a manual spot-check.

Two independent reviews covered all 66 labels:
- **Opus 5.5:** blind to the draft. Results: 48 agree, 11 disagree, 7 borderline.
- **Astra:** in a fresh reviewer role, without its own draft or rationales. Results: 34 agree, 9 disagree, 23 borderline.

Both found no grounding defects and no incorrect scheduled date. The coordinator adjudicated as follows.

## Changed

| Item | Change | Basis |
|---|---|---|
| ref 12, 13, 17, 21, 23 ("during/throughout the Term") | reason `anchor_without_date` becomes `anchor_not_found` | Both reviewers. These describe duration, not a deadline event; the frozen grammar lists during/throughout under `anchor_not_found`. |
| ref 1 (abatement after the Deadline Date) | `recurring_schedule` becomes `conditional_or_compound` | Astra. The construction sits in the leading "In the event" clause, and conditional precedes recurring in the frozen precedence. |
| ref 9 (audit overcharge reimbursement) | `contingent` becomes `untimed` | Opus. A condition with no timing construction; contingent would imply a deadline the text does not state. |
| ref 48, 49 (Continuous/Chronic Outage termination) | `contingent` becomes `unresolved` / `cross_reference`, with trigger "by timely delivery of the ... Termination Notice to Landlord" | Both. "Timely" is defined elsewhere ("within thirty (30) days"); a leading "In the event" condition does not bind. |
| ref 18, 29 ("upon the expiration or earlier termination") | `unresolved` / `conditional_or_compound` becomes `contingent` / `eq`, term-end trigger | Opus. This is one stock term-end event, consistent with the other "Upon X, party shall" labels. |
| ref 22, 30, 46; challenge 4 (238); challenge 5 (239) | Trigger trimmed to the frozen span rule (from the construction to the first comma or semicolon) | Both. Kind and reason are unchanged. Challenge 4 previously scored a correct classifier as a miss. |

## Kept, with the gap recorded as a known limitation

These labels describe the text correctly, but the frozen grammar does not cover their wording. A classifier miss on them is an honest recall gap, not a label error.

- ref 5 ("thirtieth (30th) day"): an ordinal count.
- ref 11 ("when changes are made"): a `when` construction.
- ref 47 ("Once ..., as soon as reasonably practicable"): kept as `contingent` / `gt`. Astra preferred `anchor_not_found`; the coordinator kept the semantic label.
- ref 19 ("effective upon, written notice"): the punctuation inside the trigger is kept.
- ref 24, 25, 26, 34, 40, and challenge 13: qualitative timing, mixed units, a section-number period, daily frequency, and accrual intervals.
- Date-only anchor quotes (ref 0, 3; challenge 0 to 3): the label sits in the adjacent BLI segment. The label contract allows one segment per anchor; the paired declaration is cited in the system's own evidence.

## Result

The reference set now has 2 scheduled, 19 contingent, 16 unresolved, and 13 untimed labels. The challenge set has 16 labels. Both files validate with `og.eval.timing_gold.load_timing_gold`.

Provenance reads: drafted blind by gpt-6-astra, adjudicated by the coordinator after two independent model reviews, with 0 human spot-checks. README wording for these labels is "model-drafted, model-reviewed".
