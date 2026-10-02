# ADR-007: Data model extensions

Status: accepted (2026-10-01)

## Context

The field treats the contract as the unit of analysis, but the risk lives in the edges: a guarantee backstops a lease, a recognition agreement gives a third party step-in rights, and cross-defaults chain deals together. Per-document schemas also mis-model parties (a party is landlord in one agreement and counterparty in another), drop relative deadlines into nulls that silently fall out of `upcoming_deadlines`, and carry "form of" exhibits whose blanks look like missing data.

## Decision

Extend the core obligation model, all citation-backed:

- **Per-agreement roles:** role lives on `agreement_party`, not on `party`.
- **`blank` status:** redaction markers (`[***]`, `[REDACTED]`, confidential-treatment brackets) map to `redacted`; unfilled form placeholders (`[●]`, `[•]`, `[ ]`, `____`) map to `blank`. Both are reported, never inferred.
- **Anchor events:** an event anchors a deadline only when cited, grounded, and on the same or base agreement; the anchored due date is computed in the `visible_obligation` view.
- **Derived lifecycle:** `superseded`, `pending`, `scheduled` are computed in views, never stored; `fulfilled` and `violated` are reserved for the episodic layer and not implemented.
- **Cited edges:** `supersedes`, `guarantees`, and `triggers` (kind in default, cross_default, step_in, condition) each carry a `clause_ref_id`; an uncited edge is an unstated term. The `visible_*` views expose only grounded edges and defined terms.

## Consequences

Cross-agreement questions ("if X is breached, what is triggered, owed by
whom, by when?") are answerable with every hop cited. Relative deadlines
resolve through anchor events instead of vanishing from deadline queries. The
database, not each caller, decides what is visible.

## Alternatives considered

- **Role on the party:** wrong in any multi-agreement portfolio.
- **Stored lifecycle:** duplicates derivable state, goes stale on amendment.
- **Uncited edges:** terms the system cannot point to.
- **Per-document extraction only:** the blind spot this project fills.
