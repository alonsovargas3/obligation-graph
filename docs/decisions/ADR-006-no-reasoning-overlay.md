# ADR-006: No reasoning overlay

Status: accepted (2026-10-01)

## Context

WFGY is a pasted prompt protocol with no baseline benchmarks, no independent
replication, and an unreleased engine. Our trust comes from deterministic
checks between steps, not from steering free-text reasoning, and an opaque
overlay adds a variable we cannot measure. Its RAG problem checklist is
reasonable, but this system has no retrieval step.

## Decision

Do not adopt a reasoning overlay. Control drift at step boundaries instead:

- Every step writes a typed artifact: text JSON after ingest, tool-call JSON
  after extract, rows after store.
- A deterministic checker gates each boundary: offset invariants after
  ingest, grounding after extract, FK and CHECK constraints at store, the
  `visible_obligation` view at read.
- Self-consistency is applied on gate calls only: three samples, and any
  disagreement fails open.
- Drift is measured: run extraction five times on the gold document, report
  run-to-run variance next to precision and recall, and adopt a prompt change
  only if it beats baseline by more than that variance.

## Consequences

Trust lives in reviewable, testable code rather than a prompt protocol's
claimed behavior. Eval carries an explicit variance number, so improvements
must clear a measured noise floor. Gate self-consistency spends tokens only
where recall is the headline metric.

## Alternatives considered

- **WFGY overlay:** an unmeasured variable wrapped around every call.
- **LLM-as-judge verification:** nondeterministic checking of deterministic
  work (rejected in ADR-002).
- **Broader self-consistency everywhere:** cost without a recall target.
