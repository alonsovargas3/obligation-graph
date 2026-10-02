# ADR-005: Span selection over generation

Status: accepted (2026-10-01)

## Context

Free-text description followed by quoting invites hallucinated terms, and
reported hallucination rates in legal tools are high enough that grounding
must be deterministic (ADR-002). Ingest numbers paragraphs as segments with
exact offsets, so the model can point instead of write.

## Decision

Extraction selects spans; it does not generate them:

- Prompts and tool schemas put `span_text` first, before any description, so the model commits to the quote before characterizing it. The model cites a segment ID plus a quote; the stored text is copied from the source, never taken from the model's output.
- The tool schema offers explicit `redacted` and `blank` options so hidden or unfilled terms are reported, not guessed.

Wave-2 writer contract:

- Only the store writer sets `grounded=1`, after `ground()` succeeds against the TextDoc whose `source_sha256` matches the source pin. It stores the copied slice and the derived section and page.
- Marker evidence is kept: for a clause with markers, only the fields the marker hides are left null; fields with their own support stay. Form blanks are never filled from metadata or model knowledge.

## Consequences

Grounding audits citations rather than repairing them; failures are rare and
always dropped and logged. Redacted and blank terms surface as such, keeping
the invariant intact where nothing can be pointed to. Prompt versions are
tracked per extraction run for idempotent re-extraction.

## Alternatives considered

- **Description then quote:** inverts the commitment order, invites
  paraphrase.
- **Generation with fuzzy matching:** accepts near misses (ADR-002).
- **Citations API:** cannot drive structured output, and a span is not tied
  to an obligation.
