# Wave 2: Extract, Verify, Store, Score Implementation Plan (rev 2)

> **For agentic workers:** you are a supervised Orca worker. Do only your Task. Tests under `tests/` are frozen (pinned by `tests/FROZEN.sha256`), and so are the coordinator-authored contract files `src/og/extract/types.py`, `src/og/store/schema.sql`, `src/og/store/db.py`, `prompts/extract_v1.md`, and `prompts/extract_v1.schema.json`. You write implementation code only. Use `ask` for any ambiguity. Send `worker_done` once. You never hold or read an API key, and nothing in your Task calls the network.

**Goal:** CLAUDE.md build step 5 plus the extraction half of step 11. Each pinned agreement becomes typed obligations with grounded ClauseRefs in `data/graph.db`, and extraction quality is scored against a model-drafted, human-spot-checked reference set.

**Architecture:**

```
TextDoc ──chunk──▶ Chunk[] ──Claude structured output──▶ ChunkOutcome[] (ok | refused | truncated | invalid | error)
all chunks ok? ──no──▶ log failures, keep previous snapshot, exit nonzero for this doc
           └─yes──▶ RawItem[] ──verify (deterministic)──▶ VerifiedObligation/Event/Party[] + Drop[] + FieldCorrection[]
                                  └──writer (one transaction, replaces this source's snapshot)──▶ graph.db
graph.db (visible_* views) + eval/gold/<doc>.yaml ──score──▶ eval/results/<date>-extract.json
```

- The model only proposes. `verify` decides what may be stored. Raw model output never supplies a stored field by fallback.
- Every stored value is either copied from the source slice or proven present in it by a field rule.
- The writer is the only code that sets `grounded = 1`.

**Tech Stack:** Python 3.12, uv, `anthropic` (locked), sqlite3, pyyaml, pytest, ruff. No new dependencies.

**Spec:** `CLAUDE.md`, ADR-001..007, `docs/research/2026-10-01-approach.md`, wave-1 plan and report. Advisor review: `docs/reviews/2026-10-02-astra-wave2-review.md` (resolution table at the end).

## Global Constraints

- **The invariant:** every stored obligation, event, party role, defined term, and edge has a ClauseRef whose `span_text == text[char_start:char_end]`. `grounded = 1` is set only by the writer, after `verify`, against a TextDoc whose `source_sha256` equals the sources.yaml pin. Redacted and blank terms are reported, never inferred.
- **Field rules:** a typed value (amount, currency, due date, offset days, event date, trigger, party name, role) is stored only if its evidence is in the copied quote, per Task 8. Otherwise it is null, plus a FieldCorrection record.
- **One snapshot per source:**
  - `graph.db` holds exactly one extraction snapshot per source (the latest complete one). Re-extraction replaces it in one transaction.
  - Variance and experiment samples are written to separate DB files under `eval/runs/` and never into `graph.db`.
  - Multiple prompt versions are not kept live side by side (this rev withdraws that promise).
- **Derived data is rebuilt, not migrated:** `graph.db` is fully reproducible from `data/sources.yaml` and the raw files. Schema v2 sets `PRAGMA user_version = 2`. `connect()` raises `SchemaOutdated` on an existing file with a lower version, with the message "delete data/graph.db and run make extract". Fresh files are created at v2.
- **API (coordinator-only at runtime):**
  - `OG_EXTRACT_MODEL` (default `claude-sonnet-5-5`), non-streaming `client.beta.messages.create`.
  - `output_config = {"effort": OG_EXTRACT_EFFORT (default "high"), "format": {"type": "json_schema", "schema": <frozen schema>}}`.
  - System block with `cache_control: {"type": "ephemeral"}`.
  - `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`.
  - Never `temperature`, `thinking`, `tools`, or `tool_choice`.
  - Check `stop_reason` before parsing: `refusal` and `max_tokens` responses can violate the schema.
- **Secrets:**
  - The client reads credentials from the environment only. The coordinator loads `~/.config/og/anthropic.key` into the single process that needs it.
  - Logs, cache files, fixtures, and results are written through explicit field allowlists. Never write request headers, client objects, environment dumps, or exception reprs.
  - Tests plant a sentinel key and assert it appears in no written file.
- **Tests:** offline only. They use synthetic `FakeClient` responses (labeled synthetic) or coordinator-recorded real responses under `tests/fixtures/api/`.
- **Tooling:** no ORM or agent frameworks. `uv run --locked`. Never `ruff check --fix`. No em dashes in user-facing copy.

## Review Focus

1. **Fabricated event date on a form blank** (`"Commencement Date" means [●]` with model date 2026-01-01): event stored with date null, status blank, FieldCorrection `date_not_in_quote`.
2. **A number in the quote that is not an amount** (`Tenant shall pay within 30 days` with model amount 30): amount null (no `$`/dollars evidence). `offset_days` 30 is kept only with `days` wording.
3. **One chunk refused out of five:** nothing is written, the previous snapshot stays, the failure is logged, and the CLI exits nonzero for that document.
4. **Two parties quoted from the same preamble sentence:** both kept, not collapsed.
5. **Wrong entity merge** ("Digital 55 Middlesex, LLC" vs "Digital 55 Middlesex, Inc."): these are different parties. There is no suffix stripping.

---

## Contract files (coordinator-authored before dispatch, frozen)

- **`src/og/extract/types.py`:** all shared dataclasses and exceptions below. It imports nothing from other wave-2 modules.
- **`prompts/extract_v1.md` + `prompts/extract_v1.schema.json`:** the system prompt and output schema. The schema is flat: each item has every field, `required` lists all fields, `additionalProperties: false`, and nullable enums include `null` in the enum. The coordinator validates it against the live API in C1.
- **`src/og/store/schema.sql` (v2) + `src/og/store/db.py`:** the schema changes listed under Task 9. `connect()` handles the version check.

**Shared types** (`og.extract.types`):

```python
Kind = Literal["obligation", "event", "party"]
OBL_TYPES = ("payment","delivery","sla","penalty","termination_right","guarantee","notice","insurance","other")
ROLES = ("landlord","tenant","guarantor","provider","customer","lender","other")

@dataclass(frozen=True)
class RawItem:            # exactly the schema's item fields; diagnostics only after verify
    span_text: str; segment_id: str; kind: str; type: str | None; owed_by: str | None; owed_to: str | None
    description: str | None; amount: float | None; currency: str | None; due_date: str | None
    anchor_event: str | None; offset_days: int | None; trigger: str | None; status: str | None
    name: str | None; date: str | None; role: str | None

@dataclass(frozen=True)
class Evidence:           # the copied quote, located
    segment_id: str; section_id: str | None; section_number: str | None; page: int
    char_start: int; char_end: int; span_text: str

@dataclass(frozen=True)
class VerifiedObligation:
    evidence: Evidence; type: str; status: str            # status in active|redacted|blank
    owed_by: str | None; owed_to: str | None              # verified party mention or role word (see Task 8)
    description: str                                      # model text if all its digits occur in the quote, else the quote
    amount: Decimal | None; currency: str | None; due_date: str | None
    anchor_event: str | None; offset_days: int | None; trigger: str | None

@dataclass(frozen=True)
class VerifiedEvent:     evidence: Evidence; name: str; date: str | None; status: str
@dataclass(frozen=True)
class VerifiedParty:     evidence: Evidence; name: str; role: str
@dataclass(frozen=True)
class Drop:              raw: RawItem; reason: str
@dataclass(frozen=True)
class FieldCorrection:   raw: RawItem; field: str; reason: str       # value nulled or replaced

@dataclass(frozen=True)
class VerifyResult:
    obligations: list[VerifiedObligation]; events: list[VerifiedEvent]; parties: list[VerifiedParty]
    drops: list[Drop]; corrections: list[FieldCorrection]

@dataclass(frozen=True)
class Attempt:            # one model attempt inside one API call (fallbacks produce several)
    model: str; input_tokens: int | None; output_tokens: int | None
    cache_read_tokens: int | None; cache_write_tokens: int | None; refused: bool

@dataclass(frozen=True)
class ChunkOutcome:
    chunk_id: str; status: str            # ok | refused | truncated | invalid | error
    items: list[RawItem]; attempts: list[Attempt]; latency_ms: int | None
    cache_hit: bool; request_fingerprint: str; error: str | None   # error: short code only, never a repr

@dataclass(frozen=True)
class ExtractResult:
    doc_id: str; prompt_version: str; outcomes: list[ChunkOutcome]
    @property
    def complete(self) -> bool: ...       # every expected chunk has status ok

class TruncatedResponse(Exception): ...
class BadResponse(Exception): ...
class SchemaOutdated(Exception): ...      # lives in og.store.db, re-exported here
```

## Execution topology

Same as wave 1:
- **Coordinator:** Opus.
- **Advisor:** Astra, for plan rounds and a satisfiability proof.
- **Workers:** Pi `zai/glm-5.3` on devbox worktrees under Orca supervision, with Grok as the fallback.
- **Tests:** frozen and coordinator-authored, verified red before dispatch.
- **Review and merge:** isolated-checkout review, then a PR merge.
- **Retries:** the accepted-base-SHA dispatch log and the salvage/retry rules carry over.

- **Bootstrap B2 (coordinator):** the contract files above, all wave-2 tests, and `tests/FROZEN.sha256` regenerated. Red is verified (each new test module fails on a missing module or attribute; all wave-1 tests stay green). One commit.
- **Wave 2A (parallel, from B2):** Task 6 (TOC), Task 7 (chunk/prompt/client/cache), Task 8 (verify), Task 10 (gold + scorer + score CLI), Task 13 (ADR-008).
- **Wave 2B:** Task 9 (writer) from B2. It needs only the contract files, so it can run in 2A too. Task 11 (CLI) after 7, 8, 9 merge.
- **C1** (record fixtures) after Tasks 7 and 8 merge. **C2** (reference set) runs in parallel throughout. **C3/C4** after Task 11 merges and C2 is exported.

---

### Task 6: TOC section

**Rule (in `sections.py`):**
- Each candidate section line (any of the four rev-4 patterns) is classified in one forward pass over the lines.
- A candidate is a **TOC entry** when the lines between it and the next candidate are all page references (`^\d{1,3}$` or `^[ivxlc]{1,6}$`, case-insensitive), with zero or more such lines.
- A **TOC run** is a maximal sequence of at least 3 consecutive TOC entries (only page-reference lines and an optional `TABLE OF CONTENTS`/`Page` line may sit between them).
- Each TOC run, plus an immediately preceding line matching `^(TABLE OF CONTENTS|Table of Contents|CONTENTS)$` if present, becomes one section `Section(id, None, "Table of Contents", start, end, None)`.
- Fewer than 3 consecutive entries are not a TOC; those lines stay ordinary sections.
- Section ids stay sequential.

**Files:** `src/og/ingest/sections.py` (and `__init__.py` only if section assembly needs it).

**Frozen tests:** `tests/test_ingest_toc.py`, with fixtures modeled on the Constant Contact TOC (dotted entries with page-number lines, single-level entries, a `Page` header line, a 2-entry false positive, and a body clause followed by a digit-only table cell).

**Corpus smoke (coordinator):** report the TOC sections created per document. The Constant Contact lease has exactly one TOC section, and no body clause heading is lost: every body section number from before the change is still present.

### Task 7: Chunker, prompt rendering, client, cache

**Files:** `src/og/extract/{__init__,chunk,prompt,client,cache}.py`.

- **`chunk_doc(doc, max_chars=12000) -> list[Chunk]`** (`Chunk(chunk_id, doc_id, segment_ids, text)`):
  - Segments in sections whose heading is `Table of Contents` are excluded.
  - Packing is greedy and in order. A chunk closes before the next section would push `len(text)` past `max_chars`. If a single section exceeds the cap, it is split at segment boundaries. A single segment longer than the cap is its own chunk (soft cap).
  - `text` renders each segment as `[pNNNN] <text>\n`.
  - Chunk 1 holds the opening segments. Later chunks start with a `CONTEXT (do not extract)` block: the first preamble segments up to 1500 chars, rendered `[ctx pNNNN] ...`. Context segments are never in `segment_ids` of later chunks.
  - Every non-TOC segment is in exactly one chunk. Deterministic.
- **`prompt_version() -> str`:** `"extract_v1@" + sha256(prompt bytes + schema bytes)[:8]`.
- **`build_request(chunk, *, model, effort) -> dict`:** exactly the kwargs in Global Constraints. `messages=[{"role": "user", "content": chunk.text}]`.
- **`request_fingerprint(request: dict, doc: TextDoc) -> str`:** sha256 of the canonical JSON (`sort_keys=True, separators=(",", ":")`) of the request plus `doc.source_sha256` plus `sha256(doc.to_json())`.
- **`parse_response(message) -> tuple[list[RawItem], list[Attempt]]`:**
  - Order of checks: `stop_reason == "refusal"` raises `Refused`; `max_tokens` raises `TruncatedResponse`.
  - Then take the single `text` block. Thinking and fallback blocks are ignored. No text block, or more than one, raises `BadResponse("no_text")`.
  - `json.loads` and validation run locally: every field present, types match the schema, enums valid, numbers finite, dates real calendar dates. Any failure raises `BadResponse("<code>")`.
  - Attempts come from `usage.iterations` when present (each with its model and usage), else one Attempt from top-level usage and `message.model`.
  - `Refused` is defined in `types.py` too.
- **`ResponseCache(root)`:**
  - `get(fingerprint) -> dict | None` and `put(fingerprint, payload: dict)`.
  - The path is `root/<fingerprint[:2]>/<fingerprint>.json`, written atomically (temp + `os.replace`).
  - Only validated ok outcomes are stored, with payload keys allowlisted: `items` (raw dicts), `attempts`, `prompt_version`, `doc_id`, `chunk_id`.
  - A corrupt file is treated as a miss and renamed `*.corrupt`.
- **`Extractor(client, cache, *, model, effort, no_cache=False, archive_dir=None).extract(doc) -> ExtractResult`:**
  - Per chunk: build the request, compute the fingerprint, check the cache (unless `no_cache`), else call.
  - On an exception: `Refused` → status `refused`, `TruncatedResponse` → `truncated`, `BadResponse` → `invalid`, an SDK `APIError` → `error` with `error=<class name>`.
  - Latency is measured around the call.
  - With `no_cache`, ok payloads go to `archive_dir/<attempt_id>/` (if given) and never to the canonical cache.

**Frozen tests:** `tests/test_extract_chunk.py`, `tests/test_extract_request.py`, `tests/test_extract_parse.py`, `tests/test_extract_cache.py`. FakeClient SDK-shaped messages are built from `anthropic.types` where constructible, otherwise SimpleNamespace.

### Task 8: Verify (deterministic, TDD heavy)

**Files:** `src/og/extract/verify.py`.

**`verify(doc, items) -> VerifyResult`.** Rules apply per item, in order:

1. **Kind and required fields.** Obligation needs `type` in OBL_TYPES; event needs `name`; party needs `name` and `role` in ROLES. A failure gives Drop `missing_field:<f>` or `bad_enum:<f>`. An unknown `segment_id` gives Drop `unknown_segment`.
2. **Grounding.** `ground(doc, Span(span_text, seg.char_start, seg.char_end, seg.section_id))`. A failure gives Drop `<ground reason>`.
   - On success the evidence is the copied slice. Its `segment_id` is the segment containing `char_start`.
   - If the slice does not end inside that same segment: Drop `multi_segment_evidence`.
   - If the final segment differs from the cited one: FieldCorrection(`segment_id`, `relocated`).
   - TOC-section evidence gives Drop `toc_evidence`.
3. **Status (obligation and event).**
   - `redacted` if `is_redacted(quote)`; else `blank` if `is_blank(quote)`; else `active`.
   - If the segment outside the quote contains a marker: FieldCorrection(`status`, `marker_in_segment_outside_quote`). Status is not changed.
   - The model's status, if different, gives FieldCorrection(`status`, `model_status_overridden`).
   - `superseded` is never produced by extraction (deferred to wave 3).
4. **amount** (obligations).
   - Kept only if the quote contains a money expression whose value equals it exactly (Decimal).
   - Money expressions: `\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?` (optional leading `-` or a `(`...`)` negative), or a number in that format followed by ` dollars`/` Dollars`.
   - Otherwise null plus FieldCorrection(`amount`, `amount_not_in_quote`).
   - A redaction marker does not by itself remove a separately evidenced amount (field-local rule).
5. **currency.** `USD` only if the kept amount's evidence used `$` or `dollars`, else null. The model's other value gives FieldCorrection(`currency`, ...).
6. **offset_days** (obligations).
   - Kept only if the quote contains `(\d{1,3})\s*\)?\s*(calendar\s+)?days?\b` with that integer, AND the word window (≤ 60 chars) after the match contains `after|following|from|of` (positive) or `before|prior to` (negative, stored negative).
   - `business days`, `months`, and `years` are never converted.
   - Otherwise null plus FieldCorrection. If `offset_days` is null, `anchor_event` is null (pair).
7. **anchor_event** (obligations): kept only if `offset_days` was kept AND the anchor name occurs in the quote (case-insensitive, whitespace-normalized). Else null plus FieldCorrection.
8. **due_date** (obligations) and **date** (events).
   - Kept only if the quote contains that calendar date in one of these forms: `January 5, 2026`, `Jan. 5, 2026`, `5 January 2026`, `1/5/2026`, `2026-01-05`.
   - For `due_date`, the 40 chars before the date must also contain a deadline cue: `on or before|no later than|by|until|due|prior to`.
   - Otherwise null plus FieldCorrection. A date on a `blank` event is always null.
9. **trigger:** kept only if it is a verbatim substring of the quote (whitespace-normalized compare, stored as the source substring). Else null.
10. **description:** the model text if every digit-run in it occurs in the quote; otherwise the quote, plus FieldCorrection(`description`, `number_not_in_quote`).
11. **owed_by / owed_to.**
    - Kept if the value is a role word in ROLES that appears in the agreement's text, or a party name that appears verbatim (case/space-normalized) somewhere in the agreement.
    - Otherwise null plus FieldCorrection.
    - Resolution to party rows happens in the writer.
12. **Party items.** Kept only if the quote contains the name (case/space-normalized) AND the role word (`landlord`, `tenant`, ...) occurs within the same quote. No suffix stripping and no alias inference.
13. **Duplicates.** Collapse only items whose full verified payloads are equal (same kind, evidence offsets, and every field). Distinct facts sharing a quote are all kept.

**Frozen tests:** `tests/test_verify.py`, about 60 cases: every rule, the Review Focus cases, the Astra counterexamples (`within 30 days` amount, `-$5`, `$54,000.00` vs 54000.004, `30 months`, business days, execution-date vs due-date, a nulled amount still in the description, two parties in one sentence, two payments in one paragraph, a marker outside the quote), plus a property test that every Evidence equals its doc slice.

### Task 9: Writer

**Files:** `src/og/store/writer.py`.

**Schema v2 (contract file, coordinator) adds:**
- `agreement_party.clause_ref_id` (NOT NULL; the party evidence).
- `extraction_run` columns: `textdoc_sha256`, `model_attempts_json`, `completed_at`.
- `PRAGMA user_version = 2`.
- `obligation.description` stays NOT NULL.

**`write_snapshot(con, *, source, agreement, doc, run, result: VerifyResult) -> WriteStats`.**

Preconditions (each raises `WriteRefused(code)`):
- `doc.source_sha256 == source["sha256"]`.
- The existing `source` row, if any, has the same sha256 (`source_repin`).
- Every Evidence slice equals the doc text.
- No obligation in another agreement anchors on this agreement's events (`dependents_exist`). Re-extract the lineage base-first.

Transaction (`BEGIN IMMEDIATE`; on any error, rollback and re-raise):
1. Upsert `source` and `agreement` with `ON CONFLICT DO UPDATE` (never `INSERT OR REPLACE`).
2. Delete this agreement's previous snapshot, children before parents: clause_refs of its obligations, obligations, then the events, defined_terms, and agreement_party rows of this agreement, then their clause_refs, then the old extraction_run.
3. Insert a new extraction_run.
4. **Parties:** look up the party by exact stored name, inserting it if absent. Insert `agreement_party(role, clause_ref_id)`.
5. **Events,** with clause_refs.
6. **Defined terms** (deterministic, `extract_defined_terms(doc)`: `(“Term”)`, `(the “Term”)`, `“Term” means`), with clause_refs. The first occurrence of each term wins.
7. **Obligations** with clause_refs (`grounded = 1`, section number, page).
   - `owed_by`/`owed_to` resolve to a party id only when exactly one candidate matches: the role word among this agreement's agreement_party roles, else an exact normalized name. Otherwise NULL plus a stats warning.
   - The anchor resolves to an event id only when exactly one event in this agreement has that normalized name, else exactly one in the base agreement. Otherwise null pair plus a warning.
8. Commit.

`WriteStats(obligations, events, parties, defined_terms, unresolved_parties, unresolved_anchors)`.

**Frozen tests:** `tests/test_writer.py`. Cases:
- Replace semantics (run twice gives identical counts and other agreements untouched).
- Rollback on an injected failure.
- Source repin refused.
- Dependents refused.
- Ambiguous role.
- Distinct suffix entities.
- Base-agreement anchor.
- Conflicting base events left unresolved.
- Defined terms.
- Every row visible via the `visible_*` views.
- Plus `tests/test_schema_v2.py` (version check, fresh create, outdated-file refusal, the new columns). These test the contract files, which must pass at B2.

### Task 10: Reference set, scorer, score CLI

**Files:** `src/og/eval/{__init__,gold,score,__main__}.py`.

**Gold format** (`eval/gold/<doc_id>.yaml`):
- `doc_id`, `source_sha256`, `textdoc_sha256`.
- `provenance: {drafted_by, adjudicated_by, spot_checked}`.
- `scope: full_agreement | sampled`.
- `obligations: [...]` with `segment_id, char_start, char_end, span_text, type, owed_by, owed_to, description, amount, currency, due_date, anchor_event, offset_days, trigger, status`.

**`load_gold(path, doc) -> Gold`** validates:
- doc_id, both shas, and offset bounds.
- `span_text == doc.text[s:e]`, and the span lies inside its `segment_id`.
- Enums, date and number types.
- Failure raises `ValueError(<code>)`.

**`score(gold, predicted, metric="m1") -> Score`** (`PredItem` has the gold fields plus `obligation_id`):
- **Matching:** maximum-cardinality bipartite matching over pairs with the same type and IoU ≥ 0.3. Among maximum matchings, maximize total IoU. Ties are broken by (gold index, pred index).
- **Localization:** per-type and micro P/R/F1. Macro over types present in gold. Empty-set conventions: P = 1.0 when there are no predictions and gold is empty, else 0.0.
- **Field correctness** on matched pairs: for each of `amount, currency, due_date, offset_days, anchor_event, owed_by, owed_to, status`, report `{gold_known, pred_known, both_known_equal, accuracy_on_known, coverage}`.
- Results carry `metric`, the threshold, and counts.

**`pred_from_db(con, doc_id) -> list[PredItem]`:** one item per visible obligation of the agreement (deduplicated across multiple clause_refs, earliest ref). `owed_by`/`owed_to` are returned as the role word of the resolved party.

**`python -m og.eval extract --doc <id> --db <path> [--gold <path>] [--out <path>]`** writes a results JSON containing:
- `metric`, `prompt_version`, `doc_id`, `textdoc_sha256`.
- `score`, `proposal_grounding` (verified / proposed, from the run's log), and `integrity` (count of visible obligations lacking a grounded same-agreement ref; must be 0).
- `drops_by_reason`, `corrections_by_field`.
- `cost_usd` with `cost_basis`.
- `calls` (attempt models, tokens, latency).

**Frozen tests:** `tests/test_eval_gold.py`, `tests/test_eval_score.py` (Astra's greedy counterexample, ties, empty sets, field coverage), `tests/test_eval_cli.py` (temp DB + gold, then a JSON shape check).

### Task 11: `make extract`

**Files:** `src/og/extract/__main__.py` (and a Makefile `extract` target edited by the coordinator in B2 to `uv run --locked python -m og.extract`).

**Behavior** (`python -m og.extract [--doc <id>] [--db data/graph.db] [--no-cache --runs-dir eval/runs/<stamp>]`), for each pinned source with `data/text/<id>.json`:
1. Load the TextDoc and check its pin.
2. `Extractor.extract`. If not `complete`: log every non-ok outcome, skip the write, and mark the doc failed.
3. `verify`, then `write_snapshot`.
4. Append to `logs/extract_runs.jsonl` one allowlisted record per document-run:
   - `run_id`, `doc_id`, `prompt_version`, `textdoc_sha256`, `complete`.
   - Per-chunk `{chunk_id, status, cache_hit, latency_ms, attempts}`.
   - `drops: [{reason, segment_id, span_text[:200]}]`, `corrections: [{field, reason, segment_id}]`, `stats`.
5. Processing order: base agreements first (via `amends`).
6. Exit codes: 0 when every doc completed, 3 when any failed.
7. `--no-cache --runs-dir X` writes each sample to its own DB `X/<doc>.db` and archive dir, never touching `graph.db`.
8. **Pricing:** a dated table constant `PRICES_2026_10 = {"claude-sonnet-5-5": {...}}`. An attempt on a model missing from the table gets `cost = None` and `cost_basis = "unknown_model"`.

**Frozen tests:** `tests/test_extract_cli.py`. End to end on the lease fixture with a FakeClient: complete run, a refused chunk (no write and exit 3), a re-run that replaces the snapshot, a `--no-cache` sample isolated from `graph.db`, and a sentinel key absent from every written file.

### Task 13: ADR-008

`docs/decisions/ADR-008-extraction-contract.md` covers:
- Structured outputs instead of forced tool use.
- Field-level evidence rules.
- One snapshot per source, with derived data rebuilt rather than migrated.
- The completeness gate.
- The refusal fallback and per-attempt accounting.
- The model-drafted, spot-checked reference set and its disclosure wording.

---

## Coordinator steps

- **B2:** the contract files, tests, the Makefile target, and the `.env.example` additions (`OG_EXTRACT_EFFORT`, `OG_EXTRACT_CHUNK_CHARS`). Red is verified and the freeze is regenerated.
- **C1 (needs key, after 7 and 8 merge):**
  - Call the live API on 2 chunks of `constantcontact-2012-ex101` and 1 chunk of `carbonite-2014-ex1024`.
  - Save the allowlisted payloads to `tests/fixtures/api/extract_v1/`.
  - Add frozen replay tests (`parse_response` + `verify`: every kept item grounds; the schema is accepted by the API). Record them in `test-changes.md`.
- **C2 (reference set; user decision 2026-10-02):**
  1. Astra drafts blind from the TextDoc (in progress).
  2. The coordinator validates and adjudicates, recording each change with a reason.
  3. The draft is loaded into the labeler artifact (`origin: astra-draft`).
  4. The user spot-checks about 10.
  5. Export to `eval/gold/` with provenance, after Task 6 re-ingest. Offsets are recomputed only if `textdoc_sha256` changed. A changed quote means the item is re-adjudicated, never silently moved.
  6. The README wording is "model-drafted, human-spot-checked reference set".
  7. Labels are frozen once the first scored run is recorded.
- **C3:** `make ingest && make extract` on the integration checkout. Record cost, latency, and outcomes.
- **C4:**
  - Score into `eval/results/<date>-extract.json`.
  - Variance: 5 independent `--no-cache` samples (ADR-006) on the gold doc, each scored from its own DB. Report the mean and range per metric, and label any sample that used a fallback model.
  - No prompt changes are adopted in this wave.

## Review resolution (Astra wave 2 round 1)

| # | Finding | Resolution |
|---|---------|-----------|
| 1 | Unsafe verified payload | Kind-specific Verified* types; raw output never stored; event dates, currency, trigger, and description get field rules |
| 2 | Number occurrence ≠ meaning | `$`/dollars evidence and exact Decimal for amount; `days` wording plus before/after for offsets; a deadline cue for due dates; number words cut |
| 3 | Party/anchor manufacturing | Party role cited (`agreement_party.clause_ref_id`); no suffix stripping; unique-candidate resolution or NULL; the anchor must be named in the quote |
| 4 | Multi-run isolation | One snapshot per source; experiments in separate DBs; ordered delete; repin and dependents refused; `ON CONFLICT DO UPDATE` |
| 5 | Partial or empty overwrite | Per-chunk outcomes; write only when complete; the previous snapshot is kept on any failure; failures are never cached |
| 6 | Marker handling | Field-local amount rule; status from markers in the quote; a marker outside the quote is flagged; superseded deferred |
| 7 | Migration | Derived DB rebuilt: `user_version` check with `SchemaOutdated`; contract files owned by the coordinator |
| 8 | Interfaces and DAG | Frozen `types.py` and contract files in B2; disjoint modules; C1 after 7 and 8 |
| 9 | Duplicate collapse | Only identical full payloads |
| 10 | Schema/parser | Frozen flat schema with null in enums; local validation; Attempt metadata separate from parse |
| 11 | Chunk/header/relocation | Soft cap and oversize rule; `[ctx]` context block not extractable; relocation recorded; multi-segment evidence dropped |
| 12 | TOC | Forward-pass rule with a ≥3-entry run that becomes a "Table of Contents" section, excluded from chunks; corpus-modeled fixtures |
| 13 | Cache | Fingerprint over request plus doc identity; only ok payloads cached atomically; allowlist; no-cache archive |
| 14 | Fallback accounting | Per-attempt models and usage from `usage.iterations`; dated price table; unknown = None |
| 15 | Eval honesty | Full gold validation; maximum-cardinality matching; separate localization and field metrics with coverage |
| 16 | Metrics and entrypoints | Proposal grounding vs integrity split; logs keyed by run; score CLI owned by Task 10 |
| 17 | Variance | 5 uncached samples in separate DBs, mean and range, fallback samples labeled |

## Contract details pinned by the frozen tests (rev 2.1)

Where rev 2 was silent, the frozen tests pin these choices. They are authoritative. A worker who believes one is wrong uses `ask` and does not work around it.

**Task 6 (TOC):**
- A candidate counts as a TOC entry only if at least one page-reference line follows it.
- Page references are matched case-insensitively, so roman `IV` counts.
- A `Page` line between `TABLE OF CONTENTS` and the first entry does not detach the heading; the TOC section starts at the heading line.

**Task 7 (modules and contracts):**
- **Module locations:**
  - `og.extract.chunk.chunk_doc`.
  - `og.extract.prompt.{prompt_version, build_request, request_fingerprint}`.
  - `og.extract.client.{parse_response, Extractor}`.
  - `og.extract.cache.ResponseCache`.
  - CLI entry `og.extract.__main__.main(argv: list[str] | None = None, *, client=None) -> int`. It builds a real SDK client only when `client` is None.
- `Extractor(..., max_chars=12000)` passes `max_chars` to `chunk_doc`.
- **Context block:** the leading non-TOC segments, up to 1500 chars of segment text, always at least one. Every chunk after the first starts with `CONTEXT (do not extract)` followed by `[ctx pNNNN] <text>` lines. Chunk 1 has none. The soft cap applies to the full `chunk.text`; only a single-segment chunk may exceed it.
- **System prompt:** `system[0].text` is the UTF-8 text of `prompts/extract_v1.md`.
- **`parse_response` rejects** (`BadResponse`, non-empty code; only `no_text` is pinned):
  - Extra or missing keys at the top level or in an item, or a non-list `items`.
  - Booleans as numbers, a non-int `offset_days`, NaN.
  - Bad enums, and non-ISO or non-calendar dates.
- **Attempts:** one per `usage.iterations` entry (fields `model`, `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, read with getattr). Every entry but the last has `refused=True`. Without iterations, one Attempt comes from top-level usage plus `message.model`.
- **`ResponseCache.put`:**
  - Raises `ValueError` on any payload key outside the allowlist and writes nothing.
  - Ok outcomes with empty `items` are cached; failures never are.
  - A corrupt file is renamed with a `.corrupt` suffix and treated as a miss.

**Task 8 (verify):**
- Kind, enum and required-field checks run before the unknown-segment check. A bad `kind` drops as `bad_enum:kind`.
- If either `offset_days` or `anchor_event` is nulled, both are nulled (the DB pair CHECK).
- A null model description falls back to the quote.
- Role words are matched case-insensitively. Party names are case- and space-normalized for comparison, and the model's string is stored.
- Trigger matching is case-sensitive with whitespace normalized; the stored value is the source substring.
- Every digit run in the description must occur in the quote.
- **Currency:** null when no amount is kept. `USD` (plus a correction) when the model gave another code for a `$`-evidenced amount.
- Due-date cue words match only at word boundaries.

**Task 9 (writer):**
- `source` is a sources.yaml-style dict and `agreement` a dict `{id, title, type, effective_date, base_agreement_id, is_form}`. The agreement id equals the doc_id and the source id.
- `WriteRefused` codes `pin_mismatch`, `source_repin`, `span_mismatch`, `dependents_exist` are all checked before any write.
- Party rows are global by exact name. A snapshot delete removes only `agreement_party` rows, never `party` rows.
- `unresolved_parties` counts non-null `owed_by`/`owed_to` values that do not resolve.
- `extract_defined_terms(doc) -> list[tuple[term, char_start, char_end]]`: the term is returned without quotes, and the span includes the curly quotes.
- **Stored values:**
  - `clause_ref.section` holds the section number.
  - `amount` is stored as a float.
  - `model_attempts_json` is a JSON list of attempt dicts.
- `textdoc_sha256 = sha256(doc.to_json().encode())` everywhere: writer, gold, fingerprint.

**Task 10 (eval):**
- **Locations:** `GoldItem` in `og.eval.gold`; `PredItem` in `og.eval.score` (GoldItem fields plus `obligation_id`). `load_gold` returns `.doc_id`, `.scope`, `.provenance`, `.obligations`.
- **`load_gold` error codes:**
  - `doc_id_mismatch`, `source_sha_mismatch`, `textdoc_sha_mismatch`.
  - `bad_enum:<f>`, `out_of_bounds`, `span_mismatch`, `span_outside_segment`.
  - `bad_date:due_date`, `bad_number:<f>`.
- **`score(...).as_dict()` keys:** `metric, iou_threshold, n_gold, n_pred, matches, micro, per_type, macro`. Macro averages over the types present in gold.
- **Empty sets:** P = 1.0 only when there are no predictions and gold is empty; R = 1.0 when gold is empty.
- **Field metrics:** each field also reports `both_known`. `accuracy_on_known` and `coverage` are None when their denominator is 0.
- **`pred_from_db`:** the span comes from the earliest clause_ref, roles are lowercase role words, and `segment_id` is None.
- **Score CLI:** `og.eval.__main__.main(argv) -> int`, `extract --doc --db --text --log --out [--gold]`. It reads the log record whose `run_id` matches the DB's run.

**Task 11 (log record):** each `logs/extract_runs.jsonl` record has at least these fields, a superset of what both the extract CLI tests and the eval CLI tests read:
- `run_id`, `doc_id`, `prompt_version`, `textdoc_sha256`, `complete`.
- `proposed` and `verified` (counts).
- `chunks`: `[{chunk_id, status, cache_hit, latency_ms, attempts: [{model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, refused}]}]`.
- `drops`: `[{reason, segment_id, span_text}]`.
- `corrections`: `[{field, reason, segment_id}]`.
- `stats`.
- `cost_usd` and `cost_basis`.

**CLI defaults:**
- The cache root is `data/cache/extract`.
- A pin mismatch exits 3 with no calls and no rows. An unknown `--doc` exits nonzero.
- `--no-cache --runs-dir X` writes `X/<doc_id>.db`, never creates `data/graph.db`, and writes no cache JSON.

## Rev 2.2 (Astra wave-2 round 2: 6 blockers, 2 should-fixes, all accepted)

These rules override any earlier text they conflict with.

- **R2-1, context block:**
  - Chunk 1 is packed first.
  - The context prefix is the leading primary segments of chunk 1, up to 1500 chars of segment text, always at least one when chunk 1 is non-empty.
  - Context segments are therefore never primary in a later chunk.
  - A frozen test pins the exact context ids.
- **R2-2, events:**
  - An event is kept only if its `name` occurs in the quote (case-insensitive, whitespace-normalized; a quoted defined term `“Name”` counts).
  - Its `date` is kept only if the date occurs after that name occurrence in the quote with no other quoted defined term (`“…”`) between them. Otherwise the date is null plus a FieldCorrection(`date`, `date_not_bound_to_event`).
  - A name not in the quote gives Drop `event_name_not_in_quote`.
- **R2-3, description:** the stored description is the copied quote. The model's paraphrase is never persisted, and `VerifiedObligation.description == evidence.span_text`. Two frozen description tests change (recorded in test-changes.md).
- **R2-4, parties:** a party is kept only if, in the quote, the first role word (any of ROLES as a whole word, case-insensitive) within 120 chars after the name occurrence is the claimed role. A swapped role gives Drop `role_not_bound_to_name`.
- **R2-5, deadline conflict:**
  - If `due_date` and the (`offset_days`, `anchor_event`) pair both survive, keep `due_date` and null the pair, with FieldCorrection(`offset_days`, `deadline_conflict`).
  - The verified payload therefore always satisfies the DB CHECK.
- **R2-6, token boundaries:**
  - Money tokens must be complete: `(?<![\d.,])` before and `(?![\d,]|\.\d)` after. `$5.123` supports no amount; malformed grouping such as `$1,00` supports nothing.
  - Day counts are complete 1 to 3 digit tokens not adjacent to other digits, commas or periods. `1000 days` supports no offset.
- **R2-7, lineage and samples:**
  - The writer keeps the fail-closed `dependents_exist` check.
  - Re-extracting a document that has dependents means rebuilding the whole graph: the coordinator moves `data/graph.db` aside and runs `make extract` for every document, base first, then promotes.
  - `--no-cache` samples are limited to standalone documents (no `amends`). The CLI exits 2 before any API call for an amendment sample.
- **R2-8, partial reference sets:**
  - `scope: sampled` means the reference set is not exhaustive.
  - The score CLI then reports recall and field metrics normally, but every precision value is null, and a separate `precision_lower_bound` carries the computed figure (unlabeled true obligations count as false positives).
  - `score.as_dict()` is unchanged; the CLI applies this.
  - The C2 reference set is `scope: sampled` (50 obligations, not exhaustive). The README must report it that way.
- **R2-8 detail (pinned by tests plus coordinator decision):**
  - Under `scope: sampled`, the eval output carries `score["precision_lower_bound"] = {"micro": …, "macro": …}`.
  - Every precision value and every F1 value (micro, macro, per type) is null, because F1 depends on precision.
  - Recall is unchanged. Under `full_agreement` there is no lower-bound key.

## Rev 2.3 (Astra wave-2 round 3: 2 blockers, accepted)

These rules replace the R2-2 date rule and the R2-4 party rule.

- **R3-1, event dates:**
  - The date is kept only if it is the first date in the quote after the event-name occurrence, and it lies in the same sentence.
  - A sentence ends at `.`, `;`, or `!` followed by whitespace and a capital letter. A period that ends a month abbreviation (`Jan.`, `Feb.`, …, `Sept.`) or a single capital initial does not end a sentence.
  - Otherwise the date is null plus FieldCorrection(`date`, `date_not_bound_to_event`).
  - The name-in-quote requirement (`event_name_not_in_quote`) is unchanged.
- **R3-2, party roles:** the bound role of a name occurrence (case/space-normalized) is decided by the first rule that matches:
  - (a) **Role before the name:** a role word immediately precedes the name, with only whitespace between them (`Landlord Alpha LLC`).
  - (b) **Role after the name:** a role word follows the name in the form `as ROLE`, `as the ROLE`, `(“ROLE”)`, `(the “ROLE”)`, or `(ROLE)`. The text between the name and that construction is at most 120 chars and contains neither the standalone word `and` nor `;`.
  - The party is kept only if the bound role equals the claimed role. Otherwise (including when no role is bound) Drop `role_not_bound_to_name`.
- **Frozen tests:** `tests/test_verify.py` (`test_r3_*`) and `tests/test_pipeline_regressions_r3.py`.

## Rev 2.4 (Astra wave-2 round 4: 2 blockers, accepted). Declaration grammar.

These rules replace R2-2, R3-1, R2-4, and R3-2 for event dates and party roles. They close the class rather than patch examples: unsupported layouts lose recall but never produce a term.

- **R4-1, event date.** The date is kept only if the quote contains, at the event-name occurrence:
  - `[“]Name[”]`, then whitespace;
  - then one connector: `means`, `mean`, `each means`, `each mean`, `shall mean`, `is`, or `shall be`;
  - then whitespace and a supported date form (exactly the claimed date);
  - then optional whitespace and one of `.`, `;`, or the end of the quote.

  Nothing else may come between the connector and the date (no `not`, `the`, `later of`, `date that is`), and nothing may follow the date before the terminator (`, subject to …` fails). A leading `The` before an unquoted name is allowed (`The Expiration Date shall be December 31, 2020.`).

  Otherwise the date is null, plus FieldCorrection(`date`, `date_not_bound_to_event`). The event itself is kept if its name is in the quote, and the earlier R2-2 quoted-term guard still applies. Relative, negated, conditional, and alternative dates are never computed.

- **R4-2, party role.** The claimed name must occur with word boundaries on both sides (no letter or digit adjacent). A role binds only through one of these declarations at that occurrence:
  - **(a) Role before the name:** a role word immediately before the name (whitespace only). The role word is itself preceded by the start of the quote, `between`, `by`, `and`, or a comma. The name is followed by `and`, `,`, `.`, `;`, `(`, or the end of the quote.
  - **(b) Role after the name:** the name, then optionally `,` + `a|an <descriptor of up to 80 chars without , ( ) “ ”>` + optional `,`, then `as ROLE`, `as the ROLE`, `(“ROLE”)`, `(the “ROLE”)`, or `(ROLE)`. Nothing else may come between them.

  If both (a) and (b) bind and they disagree, nothing binds. The party is kept only when exactly one role binds and it equals the claimed role. Otherwise Drop `role_not_bound_to_name`.

  Example: `Landlord Holdings LLC, as Tenant` binds the full name to tenant. The claim `Holdings LLC` as landlord is a conflict, so it is dropped.

- **Frozen tests:** `tests/test_verify.py` (`test_r4_*`) and `tests/test_pipeline_regressions_r4.py`.

## Rev 2.5 (Astra wave-2 round 5: 3 blockers, accepted) and the stop rule

These rules add to Rev 2.4 and can only make the grammar smaller.

- **R5-1, governing context from the source.**
  - For any event-date or party-role declaration, the coordinator rule takes the full source sentence that contains the matched declaration. It is taken from the cited segment's text, not from the model's quote.
  - Sentence boundaries are the R3-1 boundaries (`.`, `!`, `?` followed by whitespace and a capital letter; month abbreviations and single initials excepted). Semicolons do not end the sentence for this check.
  - If that sentence contains any governing word (whole word, case-insensitive: `not`, `no`, `never`, `false`, `unless`, `if`, `provided`, `except`, `notwithstanding`, `neither`, `nor`, `without`, `subject to`), the declaration binds nothing. An event date becomes null plus `date_not_bound_to_event`; a party gets Drop `role_not_bound_to_name`.
  - A clipped quote does not escape this check, because the context comes from the segment.
- **R5-2, whole-name fields.**
  - For declaration (b) (role after the name), the claimed name must start at a declaration boundary: the start of the sentence, or immediately after one of `between`, `by`, `and`, `with`, `from`, `to`, `designate`, `designates`, `appoint`, `appoints`, a comma, or an opening parenthesis (whitespace allowed after the token).
  - A word-bounded suffix of a longer name (`Holdings LLC` in `Silver Cloud Holdings LLC`) does not start at a boundary, so it binds nothing. The stored name is the claimed name, which then equals the whole field.
- **R5-3, finite descriptors.** The optional descriptor in declaration (b) is exactly: `,` + `a|an` + up to 4 capitalized jurisdiction words + one of `limited liability company`, `limited partnership`, `general partnership`, `real estate investment trust`, `statutory trust`, `corporation`, `partnership`, `company`, `trust` + optional `,`. Anything else between the name and `as ROLE`/`(“ROLE”)` binds nothing.
- **Frozen tests:** `tests/test_verify.py` (`test_r5_*`) and `tests/test_pipeline_regressions_r5.py`.

**Stop rule (user decision 2026-10-02).**
- After Rev 2.5, one final advisor round checks only the R5 fixes plus the real corpus (all 7 filings).
- Further synthetic adversarial phrasings become documented known limitations in ADR-008 and the README, unless the phrasing occurs in the corpus.
- The disclosure wording: date/role binding is a conservative heuristic over a closed grammar; semantic correctness of extracted terms is measured by eval, not proven.
- The quote-existence invariant (every stored term points to a verbatim source span) is unaffected and remains enforced deterministically.
