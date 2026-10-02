# ADR-004: Model defaults, env-configured

Status: accepted (2026-10-01)

## Context

Extraction needs structured output from a strong model; decision gates need
cheap, fast yes/no answers. Pinning either in code conflates model choice with
implementation, and no API key may appear in code, logs, or fixtures.

## Decision

Model selection is environment configuration with documented defaults in
`.env.example`:

- `OG_EXTRACT_MODEL` (default `claude-sonnet-5-5`) for extraction.
- `OG_GATE_MODEL` (default `claude-haiku-4-5-20251001`) for gate calls.
- `OG_JEV_ENABLED` (default `false`) gates non-default backends behind the
  same `DecisionGate` protocol.
- `ANTHROPIC_API_KEY` supplies credentials; it is never hardcoded.

Code reads the env at call time; model names live nowhere else.

## Consequences

Swapping a model is a config change, so model quality is evaluated without a
code change. Eval attributes quality to the model under test, and run-to-run
variance is measured so a bake-off win must exceed it. A bake-off is planned
across two to three Claude models for both extract and gate roles, selected by
our own eval rather than vendor claims.

## Alternatives considered

- **Hardcoded single model:** the model becomes an unstated constant.
- **No defaults:** poor fresh-clone experience; the defaults also state the
  intended cost/quality split.
- **Per-call model parameters everywhere:** configuration sprawl.
