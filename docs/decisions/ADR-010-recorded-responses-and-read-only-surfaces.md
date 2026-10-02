# ADR-010: Recorded responses and read-only surfaces

Status: accepted (2026-10-02)

## Context

Wave 4 publishes what waves 1 to 3 built: an MCP server for agents, a UI
page for a controller, `make eval` for the README numbers. Two new risks
come with publishing. The Definition of Done requires `make fetch ingest
extract eval` to run clean from a fresh clone and reproduce the committed
numbers, but the pipeline is metered: every extraction chunk and change
check is a model call, and the README must not depend on spending money to
be verified. And publishing invites reads from anywhere (Claude Desktop, a
browser), where a read must never become a write to `graph.db` or a bill
from a model call. Separately, the wave 4 advisor review executed the
proposed SQLite authorizer enforcement against the real graph and rejected
it (docs/reviews/2026-10-02-astra-wave4-review.md, round 2, R2-1), so the
read boundary needed a form that actually holds. This ADR records the four
decisions that close those gaps: committed recorded responses with replay
modes, read-only surfaces, citation-bearing projections, and the redaction
and deadline semantics those surfaces must honor (ADR-005, ADR-008).

## Decision

- **Recorded responses are committed, not cached.** Model responses live
  under `eval/recorded/{extract,change,gate}/`, moved out of the gitignored
  `data/cache/`, keyed by request fingerprint and sharded two hex
  characters deep. Payloads are allowlisted per kind: extract is
  `{items, attempts, prompt_version, doc_id, chunk_id}`, change is
  `{findings, attempts, prompt_version, category, request_fingerprint,
  latency_ms}`, gate is `{answer_text, stop_reason, attempts, latency_ms}`.
  No prompts, headers, or keys are stored, and a frozen test asserts the
  allowlist and the absence of `sk-ant` in every file. An
  `eval/recorded/MANIFEST.json` pins, per document, the source sha256, the
  canonical TextDoc sha256, the effective settings (model, effort,
  chunk_chars, max_tokens), every required fingerprint by kind, and a
  sha256 of each payload file; change and gate fingerprints are listed under
  the change order that produced them. The manifest is checked in and a
  frozen test requires it to list exactly the payloads on disk, so the
  fresh-clone claim is auditable rather than asserted.
- **`OG_REPLAY` selects on, strict, or off.** Default `on`: replay recorded
  responses and record misses (recording is an intentional commit step, not
  an accident of local state). `strict`: any miss raises `ReplayMiss` with
  the fingerprint before any client is constructed, nothing is written, and
  the CLIs exit 4; the gate cascade re-raises rather than fail open, a
  deliberate exception to ADR-003, because a strict run asserts that
  everything is recorded and swallowing a miss would turn an audit into a
  fabricated gate answer. `off` bypasses the recordings entirely, the same
  as `--no-cache`, and neither reads nor writes them. The fresh-clone
  acceptance (C10) runs in strict mode.
- **Clients are lazy.** The API client is constructed only when a replay
  miss actually needs it, outside strict mode. A full replay therefore
  constructs no `anthropic.Anthropic` at all: a frozen test monkeypatches
  the constructor to raise and the run still succeeds. Consequence: a fresh
  clone without an API key replays the whole corpus, rebuilds the graph,
  and reproduces the eval numbers at zero incremental cost, so the README
  claims are checkable by anyone, not only by someone holding a key.
- **The gate cache is keyed by request, change-order TextDoc, and sample
  index.** A gate sample's fingerprint is the sha256 of the full effective
  request (`model`, `system`, `messages`, `output_config`, `max_tokens`)
  plus the canonical TextDoc sha256 of the change order plus the sample
  index. No run ids enter the key, so a gated run replays exactly across
  invocations and recorded samples stay comparable. A cache hit makes no
  budget reservation and no client call, returns the recorded usage, cost,
  and latency, and is marked `cache_hit = True` on the `GateDecision`.
- **Recorded and incremental cost stay separate.** A run reports
  `cost_usd`, which always includes the recorded cost of replayed gate
  calls, and `incremental_cost_usd`, which counts only calls that were not
  cache hits; likewise `recorded_latency_ms`, the sum of the original call
  latencies (check outcomes plus classifier-tier gate decisions), and
  `replay_wall_ms`, this invocation's wall time. This extends ADR-009's
  split of recorded, counterfactual, and actual spend: a $0 incremental
  fresh-clone run still reports what the recorded calls cost when they were
  made, and the two are never added into one number.
- **Fresh-clone comparison is semantic, not byte-for-byte.** Results files
  legitimately differ by run date, run ids, pair ids, wall times, and
  incremental spend, so C10 compares
  `og.eval.all.semantic_projection(results)`, which removes, at any depth,
  the volatile keys (`date`, `run_id`, `pair_id`, `baseline_run_id`,
  `extraction_run_ids`, `incremental_usd`, `incremental_cost_usd`,
  `manifest_sha256`, and any key ending in `wall_ms`) and keeps every
  metric, count, recorded cost, and recorded latency. The projection is
  frozen and idempotent. Anything outside those keys differing between the
  committed results and a fresh-clone run is a real regression.
- **MCP and UI are read-only.** Neither surface writes `graph.db` and
  neither constructs a model client; they open fresh read-only SQLite URIs
  (`mode=ro`) per call, and the MCP server checks `user_version` itself.
  `check_change_order` is a lookup, not an analyzer: it loads the stored,
  verified ChangeReport for a pinned change order (both modes plus the gate
  summary) and reports `"stored_report": true` and
  `"analysis_performed": false`. Input matching is exact: a change-order
  id, a manifest `local_path`, a bare filename equal to a pinned
  `local_path` basename, or an existing file at an arbitrary path whose
  sha256 equals a pinned change order's source sha256. Everything else,
  including ambiguous names, returns a structured `unknown_change_order`
  error with the pipeline steps to run; a completed-but-empty or stale run
  is an error (`stale_change_run`), never a quiet empty check (ADR-009
  freshness, exposed at the edge).
- **Citation-bearing projections are the read boundary, not an
  authorizer.** The advisor review executed the proposed `sqlite3`
  authorizer rule on SQLite 3.45.1 against the real graph (round 2, R2-1)
  and found it cannot work: the callback reports inner view and CTE names
  (`anchored`, `eligible_supersedes`) and even a null-source empty-column
  read, so the literal deny rule rejected a plain
  `SELECT id FROM visible_obligation`; and the callback cannot see join
  predicates, since a correctly constrained citation join and the same join
  with `OR 1=1` on each predicate produced identical read-event sets while
  returning 4 versus 3,228 rows. Enforcement therefore moved into the
  schema (plan rev 2.1): five projections (`visible_obligation_clause`,
  `visible_party_binding`, `visible_event_binding`,
  `visible_site_binding`, `visible_change_finding_ref`) each join a
  grounded, same-agreement ClauseRef by id inside the view, one row per
  (owner, ref). Readers (`og.query`, the change report, the scorers) may
  name only `visible_obligation`, `visible_supersedes`,
  `visible_change_finding`, `fresh_change_run`, the five projections, and
  the metadata tables (`agreement`, `source`, `party`, `site`,
  `change_run_chain`, `gate_decision`), under a static `FROM`/`JOIN`
  allowlist frozen in the tests; filer and URL fields from the metadata
  tables are labeled metadata, not contractual terms, and carry no
  ClauseRef. The evidence guarantee comes from the projections
  plus behavioral revocation tests (revoke a ref, the binding disappears),
  not from a callback that cannot prove what it is asked to prove.
- **Redaction is field-level, with markers.** An obligation whose status is
  `redacted` or `blank` is returned with `marker` set (`"[REDACTED]"`,
  `"[BLANK]"`) and its verbatim quote preserved. Fields independently
  verified against the quote survive (the cited COREWEAVE guarantor on
  Applied Digital 490 and 504); amount, due date, anchor, and offset that
  are not in the quote were already nulled by verify (ADR-005, ADR-008),
  and the read API adds no value, so a redacted amount never appears as a
  number anywhere in a response.
- **Pending semantics are honest.** Every visible obligation today is
  pending: all 525 have no computable `effective_due` (the corpus carries
  relative deadlines whose anchor events carry no dates), with 168
  `owed_to` bindings and 114 landlord-payee rows. `upcoming_deadlines`
  returns `scheduled` and `pending` separately, paginates `pending`, and
  attaches a note saying pending means no computable due date, not
  overdue, and not no obligation. No date is filled or guessed. Classifying
  obligations whose due date is contingent on an event that has not
  occurred is issue #26, deferred to wave 5; this ADR does not pre-empt it.

## Consequences

Anyone can clone the repository, run the pipeline without a key, and get
the committed numbers at zero incremental cost, which makes the README's
eval and gate tables reproducible claims rather than screenshots. The cost
of that is a tracked corpus of response payloads whose shape is allowlisted
and key-free, plus the discipline that prompt or settings changes create
new fingerprints and a new recording step before the manifest passes again.
Read-only surfaces mean an agent browsing the graph can never mutate it or
spend money, and a stale or unknown change order is an explicit error
instead of an empty answer. Enforcement lives in views and a static
allowlist, so it survives SQLite planner behavior, at the price of keeping
the projection predicates (by id, grounded, same agreement) true in the
schema rather than in a reviewer's eye. Until wave 5, the pending list is
the whole corpus and says so plainly.

## Alternatives considered

- **Keep responses in the gitignored `data/cache/`:** a fresh clone would
  need a key and real spend to verify the committed numbers, breaking the
  Definition of Done.
- **Byte-for-byte fresh-clone comparison:** impossible by construction
  (run ids, dates, wall times differ); the frozen semantic projection is
  the honest equivalent.
- **Keep the SQLite authorizer:** rejected on executed evidence, not
  preference; it rejected a real visible-view query and could not
  distinguish a safe join from an unrestricted one (review round 2, R2-1).
- **`check_change_order` runs the diff on demand:** turns a read surface
  into a metered writer that needs a key inside Claude Desktop, and
  re-analysis would disagree with the committed, verified report.
- **Basename fallback for arbitrary paths:** a stray file with a familiar
  name would masquerade as a pinned change order; arbitrary paths must
  hash-match the pinned source instead.
- **Fail gates open on a strict miss:** would silently mask a recording
  gap and fabricate a skip decision, so strict mode re-raises and exits 4.
- **Fill pending due dates from context:** invents a term the system
  cannot point to; the invariant forbids it, and contingent dates are
  issue #26.
