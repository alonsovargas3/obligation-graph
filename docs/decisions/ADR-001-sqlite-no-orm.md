# ADR-001: SQLite, no ORM

Status: accepted (2026-10-01)

## Context

The one invariant is that the system never states a term it cannot point to: every obligation, answer, and change-order finding carries a clause reference whose span exists verbatim in the source. The data model is a single SQLite database (`data/graph.db`) with migrations in `src/og/store/schema.sql`. Readers (MCP, UI, eval) must not be able to bypass the invariant by accident, and a local, single-writer pipeline does not need a query framework.

## Decision

Store the graph in SQLite through stdlib `sqlite3`, plain SQL only. No ORM, no query builder. The schema itself enforces the invariant:

- CHECK constraints validate types, statuses, dates, offsets, and non-empty spans with matching lengths.
- BEFORE INSERT/UPDATE triggers abort citations aimed at another agreement's rows.
- The `visible_*` views (`visible_obligation`, `visible_supersedes`, `visible_guarantees`, `visible_triggers`, `visible_defined_term`) hide anything without a grounded ClauseRef.

Readers query the `visible_*` views only. The DB enforces the invariant; callers do not re-implement it.

## Consequences

A reader bug cannot surface an uncited term. Schema review doubles as the trust review: every weakening is visible in a `schema.sql` diff. Migrations are hand-written SQL applied idempotently via `executescript`. A later ORM or query layer would open a second path around the views, so helpers must go through the same connection.

## Alternatives considered

- **ORM (e.g. SQLAlchemy):** a mapping layer between readers and the views, adding indirection without enforcement.
- **PostgreSQL:** more operational weight than a local portfolio build needs.
- **Application-level filtering:** every caller re-implements the invariant, which the spec forbids.
