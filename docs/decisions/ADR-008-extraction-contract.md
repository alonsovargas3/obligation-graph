# ADR-008: The wave-2 extraction contract

Status: accepted (2026-10-02)

## Context

Wave 2 turns model output into stored rows. The model only proposes, `verify` decides what may be stored, and the writer is the only code that sets `grounded=1`, against a TextDoc whose sha matches the sources.yaml pin (ADR-005). The open risks are the response shape, partial overwrites, silent model fallback, and an eval whose reference set is itself model-drafted.

## Decision

- **Structured outputs, not forced tool use.** Requests carry the frozen JSON schema through `output_config`; they never set `tools` or `tool_choice`. One flat response shape (all fields required, `additionalProperties: false`, null in enums) can be parsed, validated, cached, and replayed offline, and the schema is hashed with the prompt into `prompt_version`, so a schema change is a new prompt version, not silent drift.
- **Field-level evidence rules.** A typed value (amount, currency, due date, offset days, event date, trigger, party name or role) is stored only when its evidence is in the copied quote. Rev 2.2 pins the hard cases: the stored description is the quote itself, never a paraphrase; an event is kept only if its name occurs in the quote, and its date only after that name with no other quoted defined term between; a party is kept only if the first role word following the name occurrence is the claimed role; if both an absolute due date and the offset/anchor pair survive, the date wins and the pair is nulled so the row always satisfies the DB CHECK; money and day-count evidence must be complete tokens, so `$5.123` and `1000 days` support nothing. A failed rule nulls the field and records a FieldCorrection; raw model output never supplies a stored value by fallback.
- **One snapshot per source, rebuilt not migrated.** `graph.db` holds exactly the latest complete extraction per source, replaced in one transaction, children before parents; variance and experiment samples write to separate DBs under `eval/runs/`, never the live graph. The DB is reproducible from sources.yaml plus the raw files, so schema v2 refuses older files with `SchemaOutdated` ("delete data/graph.db and run make extract") instead of migrating them, and re-extracting a base agreement with dependents rebuilds the whole graph base-first.
- **Completeness gate.** A document is written only when every expected chunk returns ok. Any refused, truncated, invalid, or error chunk keeps the previous snapshot, logs the failure, and fails the run; failures are never cached.
- **Fallback with per-attempt accounting.** `stop_reason` is checked before parsing, since refusal and `max_tokens` responses violate the schema. Server-side fallback may answer on a different model, so each attempt inside a call is recorded with its model, token, and cache counts and costed from a dated price table; an unknown model gets `cost = None` with `cost_basis` "unknown_model".
- **Reference set.** Drafted blind by a model, adjudicated by the coordinator, spot-checked by a human. Scope is `sampled`, so recall and field metrics report normally while precision is reported only as a lower bound (`precision_lower_bound`), and the README calls it a "model-drafted, human-spot-checked reference set". Run-to-run variance is measured per ADR-006.

## Consequences

Every stored field traces to a quote, so readers inherit the invariant instead of re-checking it, and corrections and drops give a per-field error budget for prompt work. Rebuild-not-migrate keeps the store disposable and reproducible, at the price of re-running extraction after schema changes. Precision stays a lower bound until the reference set is exhaustive.

## Alternatives considered

- **Forced tool use:** a second response shape to parse and cache, with the schema hidden in tool definitions instead of a versioned file.
- **Store the paraphrase as description:** breaks the quote-first commitment (ADR-005).
- **Partial writes with tombstones:** a document with one failed chunk would look extracted; readers cannot tell a complete snapshot from a partial one.
- **Migrate derived data forward:** reproducibility makes migration code a liability the store does not need.
- **Hide fallback attempts:** cost and model identity per attempt would be invisible, and variance runs could not label fallback samples.
- **Hand-labeled exhaustive gold set:** not achievable in this wave; the sampled disclosure keeps the reported precision honest instead.
