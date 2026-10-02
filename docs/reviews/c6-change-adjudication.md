# C6 change-order reference adjudication (2026-10-02)

## Provenance

- **Drafts:** `eval/gold/drafts/change-*.astra.yaml`, written by gpt-6-astra blind. No checker output existed when they were written.
- **Adjudicated sets:** `eval/gold/change/*.yaml`, in the format pinned by `tests/test_eval_change.py`.

## Mechanical conversions

These were applied to every finding:
- `old_doc` is set to null for `self` origin.
- `delta` is computed for `shifted_date`.
- `currency` is set to `USD` for `price_change` (every amount quote has `$`).
- Extra draft keys are dropped: categories, context, and rationale.
- Every span was validated against the fixture text.

## Content decisions

All accepted as drafted. Each chain-origin finding was checked against its source text:

| Change order | Finding | Old side |
|---|---|---|
| 1A | p0012 | base p0451 |
| 1A | p0017 | base p0808 (Exhibit A range) |
| 1A | p0019 | base p0442 (Item 7 range) |
| 1A | p0037 | base p0893 (Table A range) |
| 1A | potential conflict p0035 | base p0721 |
| 3A | p0023 | base p0489 |

## Gate labels

| Category | 1A | 3A |
|---|---|---|
| price | yes | yes |
| dates | yes | yes |
| termination | yes | no |
| guarantee | no | no |
| sla | yes | no |
| parties_or_sites | yes | yes |

The user spot-checked all 12 gate answers on 2026-10-02 and accepted them as-is (`spot_checked: 12`). The labels are frozen before any scored run.

## Out-of-scope items

The `unrepresentable` lists in the drafts (prior rates in 2A, diagram geometry, typed capacity deltas) are known limitations, not reference findings.
