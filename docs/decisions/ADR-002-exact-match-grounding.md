# ADR-002: Exact-match grounding

Status: accepted (2026-10-01)

## Context

The invariant requires each quoted span to exist verbatim in the source text, so the model's citation is audited by a deterministic check (ADR-005 makes it an audit, not a repair). Fuzzy or embedding grounding and LLM-as-judge verification break the invariant. Real SEC exhibits contain curly quotes and non-breaking spaces, so the normalization rules must be explicit.

## Decision

`og.ground.ground()` is deterministic, whitespace-normalized exact matching only:

- Whitespace runs (NBSP and newlines included) collapse to single spaces. Quote characters are never folded: curly quotes do not match straight ones.
- The range pass searches within the claimed `[char_start, char_end]`; an explicit section ID constrains it, and matches that cross a section boundary are rejected.
- Fallback searches the same section only, nearest occurrence to the claimed start, ties to the earlier one.
- Section and page are derived from the final offsets, never taken from the model.
- Failure drops the span and appends a record with a reason to `logs/dropped.jsonl`.

## Consequences

Paraphrased or hallucinated spans fail and are never shown. Curly-vs-straight quote mismatches fail intentionally; span selection makes this rare because stored text is copied from the source. Drops are countable, feeding eval's grounding-drops metric.

## Alternatives considered

- **Fuzzy matching:** accepts near misses; a near miss is an unverified term.
- **Embedding similarity:** same failure, plus opacity.
- **LLM-as-judge verification:** nondeterministic and itself unverified.
- **Citations API as authority:** cannot combine with structured outputs, cites at sentence granularity, proves existence not support.
