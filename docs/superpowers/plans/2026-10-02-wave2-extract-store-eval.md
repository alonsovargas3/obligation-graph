# Wave 2: Extract, Verify, Store, Score Implementation Plan (rev 1)

> **For agentic workers:** you are a supervised Orca worker. Do only your Task. Tests under `tests/` are frozen (pinned by `tests/FROZEN.sha256`); you write implementation code only. Use your preamble's `ask` command for any ambiguity. Send `worker_done` exactly once. You never hold or read an API key. Nothing in your Task calls the network.

**Goal:** Build CLAUDE.md build step 5 plus the extraction half of step 11: each pinned agreement becomes typed obligations with grounded ClauseRefs in `data/graph.db`, and extraction quality is scored against the hand-labeled gold set.

**Architecture:**

```
TextDoc (wave 1) ──chunk──▶ prompt (segment-numbered text) ──Claude, structured output──▶ RawItem[]
RawItem[] ──verify (deterministic)──▶ VerifiedItem[] + Drop[]   (logs/dropped.jsonl)
VerifiedItem[] ──writer (one transaction per source+prompt_version)──▶ graph.db (visible_* views)
graph.db visible_obligation + eval/gold/<doc>.yaml ──score──▶ eval/results/<date>.json
```

The model only proposes. A deterministic `verify` step decides what may be stored:
- **Span check:** every quote must ground inside the cited segment's section (wave-1 `ground()`).
- **Field-level grounding (new in wave 2):** each numeric or date field the model fills must appear in the copied quote, or it is set to null and logged.
- **Marker override:** redaction and blank markers override the model's status.

The writer is the only code that sets `grounded = 1`.

**Tech Stack:** Python 3.12, uv, `anthropic` SDK (1.x, already locked), sqlite3, pyyaml, pytest, ruff. No new dependencies.

**Spec:** `CLAUDE.md`, ADR-001..007, `docs/research/2026-10-01-approach.md`, wave-1 plan and report.

## Global Constraints

- The invariant: never state a term the system cannot point to.
  - Every stored obligation, event, defined term, and edge has a ClauseRef whose `span_text` is the exact source slice `text[char_start:char_end]`.
  - `grounded = 1` is set only by the writer, after `verify` passed against a TextDoc whose `source_sha256` equals the pinned sha in `data/sources.yaml`.
- Redacted and blank terms are reported as `redacted` / `blank`, never inferred.
- **API usage (coordinator-only at runtime):**
  - Default extract model `OG_EXTRACT_MODEL=claude-sonnet-5-5`.
  - Structured outputs via `output_config.format` (json_schema). Forced `tool_choice` returns a 400 on Sonnet 5.5, so "tool-schema structured output" in CLAUDE.md is implemented as a json_schema output format (ADR-008).
  - No `temperature` or other sampling parameters (400 on Sonnet 5.5). `thinking` is omitted (adaptive). `output_config.effort` comes from `OG_EXTRACT_EFFORT`, default `high`.
  - `fallbacks: "default"` with beta `server-side-fallback-2026-07-01` via `client.beta.messages.create`. The served model is recorded per call.
  - Prompt caching on the system block.
- **Keys:** no key in code, logs, fixtures, cache files, or test output. The client reads credentials from the environment only. Recorded fixtures store the response body and usage, never request headers.
- **Offline tests:** tests use a fake client (synthetic responses, labeled synthetic) or recorded real responses (coordinator-recorded once, `tests/fixtures/api/`). `tests/conftest.py` already blocks real HTTP.
- No ORM, no LangChain/LlamaIndex/agent frameworks. `uv run --locked`. Never `ruff check --fix`. No em dashes in README or user-facing copy.

## Review Focus

1. **Quote not in the cited segment** (model cites p0042 but quotes p0043). It must ground only within the cited segment's section, else drop with reason `not_found_in_section`. It never grounds document-wide.
2. **Amount not in the quote** ("Base Rent of $54,000" vs model amount 45000). The amount is nulled and logged (`amount_not_in_quote`). The obligation survives with its quote. Number normalization covers `$54,000`, `54,000.00`, `54000`, and `fifty-four thousand (54,000)`. It does not cover arbitrary arithmetic.
3. **Redacted amount** (`$[***] per month`). Status becomes `redacted` and the amount stays null even if the model guessed one (`amount_in_redacted_clause` logged).
4. **Re-running extraction** for the same source and prompt version. The prior run's rows are replaced in one transaction, there are no duplicates, and other sources and prompt versions are untouched.
5. **Party name variants** ("Landlord", "DIGITAL 55 MIDDLESEX, LLC", "Digital 55 Middlesex, LLC (\"Landlord\")"). These resolve to the agreement's parties by role word or normalized name. Unresolvable becomes NULL plus a log entry, never a new invented party.

---

## Decisions to record (ADR-008, written by Task 13)

- Structured outputs (`output_config.format`) replace forced tool use for extraction on Sonnet 5.5.
- Field-level grounding: numbers, dates, and offsets must be textually present in the copied quote, or they are nulled and logged.
- Chunking: by section, packing consecutive sections up to `OG_EXTRACT_CHUNK_CHARS` (default 12000). A section longer than the cap is split on segment boundaries. Every chunk carries the agreement header (title, parties block) for context.
- Response cache: `data/cache/extract/<doc_id>/<prompt_version>/<chunk_id>.json` (gitignored). Re-running never re-bills an identical request.
- Refusal fallback (`fallbacks: "default"`) is on. Each extraction_run records the served model(s).

## Execution topology

Same as wave 1: Opus coordinator, Codex `gpt-6-astra` advisor (plan review rounds until agreement), Pi `zai/glm-5.3` workers on devbox worktrees under Orca supervision, Grok fallback, frozen coordinator-authored tests, isolated-checkout review, PR merges.

**Coordinator-only steps** (need the API key or the user's labels):
- C1: record real API fixtures.
- C2: export the gold set from the labeling artifact.
- C3: run `make extract` on the corpus.
- C4: run the extraction score and commit `eval/results/<date>.json`.

Waves:
- **2A (parallel):** Task 6 (ingest TOC fix), Task 7 (chunk + prompt + client), Task 8 (verify), Task 10 (gold + scorer).
- **2B (after Task 8 merges):** Task 9 (writer), then Task 11 (CLI wiring, needs 7, 8, 9).
- **C1** after Task 7 merges. **C2** whenever the user finishes labeling. **C3 + C4** after Task 11 merges.
- Task 13 (ADR-008, docs) in parallel with 2A.

---

### Task 6: Ingest TOC suppression

**Problem (wave-1 report):** table-of-contents lines (`1.1 Tenant Space` followed by a line `1`) open sections, so most clause numbers appear twice.

**Rule:** a candidate section line is a TOC entry when every following line, up to the next candidate section line, consists only of a page reference matching `^\d{1,3}$` or `^[ivxlc]{1,6}$` (case-insensitive), and there is at least one such line, or there are none at all because the next line is immediately another candidate. Also, the same section number must appear again later as a non-TOC section.
- TOC-entry lines do not open sections. They fall into the enclosing section, which is usually the preamble.
- Body headings are unaffected.

**Files:** `src/og/ingest/sections.py` only. **Frozen tests (coordinator):** `test_toc_entries_do_not_open_sections`, `test_numbered_line_followed_by_digit_body_is_not_toc_when_number_unique`.

**Acceptance:**
- Ingest tests pass.
- Corpus smoke (coordinator): constantcontact-2011-ex1041 has no duplicate section numbers, and its section count drops from 293.

### Task 7: Chunker, prompt, schema, client (no network)

**Files:** create `src/og/extract/{__init__,chunk,prompt,client,cache}.py`, `prompts/extract_v1.md` (system prompt), `prompts/extract_v1.schema.json` (output schema).

**Interfaces (produces):**
- `Chunk(chunk_id: str, doc_id: str, section_ids: list[str], segment_ids: list[str], text: str)`. `text` is a rendering where each segment is one line `[p0042] <segment text>`, prefixed by the agreement header.
- `chunk_doc(doc: TextDoc, header: str, max_chars: int = 12000) -> list[Chunk]`:
  - Deterministic.
  - Chunk ids are `c0001`… in order.
  - Every segment appears in exactly one chunk.
  - A chunk never splits a segment.
- `prompt_version() -> str`: `"extract_v1@" + sha256(system prompt bytes + schema bytes)[:8]`.
- `build_request(chunk: Chunk, *, model: str, effort: str) -> dict`: the exact kwargs passed to `client.beta.messages.create`:
  - `model`, `max_tokens=16000`.
  - `system=[{"type": "text", "text": <system prompt>, "cache_control": {"type": "ephemeral"}}]`.
  - `messages=[{"role": "user", "content": chunk.text}]`.
  - `output_config={"effort": effort, "format": {"type": "json_schema", "schema": <schema>}}`.
  - `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`.
  - No `temperature`, no `thinking`, no `tools`, no `tool_choice`.
- `RawItem` (dataclass, mirrors the schema):
  - `kind` in {obligation, event, party}, `segment_id`, `span_text`, `type` (obligation type or null), `owed_by`, `owed_to`, `description`, `amount` (number|null), `currency`, `due_date` (YYYY-MM-DD|null), `anchor_event`, `offset_days` (int|null), `trigger`, `status` in {active, redacted, blank}.
  - For `kind=event`: `name` and `date`.
  - For `kind=party`: `name` and `role`.
- `parse_response(message) -> tuple[list[RawItem], CallMeta]`:
  - Reads the first text block as JSON.
  - A response with `stop_reason == "refusal"` returns `[]` with `CallMeta.refused = True`.
  - `stop_reason == "max_tokens"` raises `TruncatedResponse`.
  - Invalid JSON raises `BadResponse`.
- `CallMeta(model_requested, model_served, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, latency_ms, refused, fallback_used)`.
- `ResponseCache(root)`: `get(doc_id, prompt_version, chunk_id) -> dict | None`, `put(...)`. Keyed also by `sha256(json.dumps(request, sort_keys=True))` so a changed request never hits a stale entry.
- `Extractor(client, cache, model, effort).extract(doc: TextDoc, header: str) -> ExtractResult(items: list[RawItem], calls: list[CallMeta])`: cache first, else call. `client` is anything with `.beta.messages.create(**kwargs)`.

**Schema rules (`extract_v1.schema.json`):**
- Top-level `{"items": [...]}`.
- Each item object lists `span_text` first, then `segment_id`, then the rest.
- All fields are `required`, with null allowed via `["string","null"]` types. `additionalProperties: false`.
- Enums for `kind`, `type`, `status`, `role`.

**System prompt content:**
- Role: precise contract analyst.
- Quote first, verbatim from one `[pNNNN]` line.
- One item per obligation.
- Party items only for parties named in the text.
- Event items only for defined anchor dates or events.
- `redacted` when the term is hidden by `[***]`-style markers, `blank` for unfilled form placeholders.
- Never infer hidden or blank values.
- Leave fields null rather than guess.
- No obligations from the table of contents.

**Frozen tests (coordinator):** `tests/test_extract_chunk.py`, `tests/test_extract_request.py`, `tests/test_extract_parse.py`. These use a `FakeClient` returning synthetic `SimpleNamespace` messages and check request kwargs exactly, parse paths (ok / refusal / max_tokens / bad JSON), cache hit/miss, and determinism.

### Task 8: Verify (deterministic, TDD heavy)

**Files:** create `src/og/extract/verify.py`.

**Interfaces:**
- `VerifiedItem(raw: RawItem, char_start: int, char_end: int, span_text: str, section_number: str | None, page: int, status: str, amount, due_date, offset_days, flags: list[str])`. `span_text` is the copied source slice.
- `Drop(raw: RawItem, reason: str, detail: dict)`.
- `verify(doc: TextDoc, items: list[RawItem]) -> tuple[list[VerifiedItem], list[Drop]]`.

**Rules, in order:**
1. **Segment check:** unknown `segment_id` → Drop `unknown_segment`.
2. **Grounding:** `ground(doc, Span(span_text, seg.char_start, seg.char_end, seg.section_id))`. A failure becomes a Drop with ground's reason. On success, `span_text = doc.text[start:end]`, and section and page come from the GroundResult.
3. **Status from markers:**
   - `is_redacted(slice)` → `redacted`.
   - Else `is_blank(slice)` → `blank`.
   - Else `active`.
   - The model's status is ignored except as a flag `status_disagrees` when it differs.
4. **amount:**
   - If status is `redacted` or `blank`: amount = null, and flag `amount_in_<status>_clause` if the model gave one.
   - Else keep it only if `amount_in_text(amount, slice)`. Otherwise null plus flag `amount_not_in_quote`.
   - `amount_in_text` extracts every number in the slice (`\d{1,3}(,\d{3})+(\.\d+)?|\d+(\.\d+)?`, commas removed) and compares numerically with tolerance 0.005.
5. **due_date** (`YYYY-MM-DD`): keep only if the slice contains the same date in one of these forms: `Month D, YYYY`, `Mon. D, YYYY`, `M/D/YYYY`, `YYYY-MM-DD`, or `D Month YYYY`. Otherwise null plus `due_date_not_in_quote`.
6. **offset_days:** keep only if the slice contains the integer as digits (word boundary), or a number word for the integers 1 to 365 that the module can spell (`thirty`, `ninety`, `one hundred twenty`…). Otherwise null plus `offset_not_in_quote`. If `offset_days` is nulled, `anchor_event` is nulled too (the pair rule).
7. **Kind-specific checks:** obligations require `type`; events require `name`; parties require `name` and `role`. A missing field is a Drop `missing_field:<name>`.
8. **Duplicates:** exact duplicates (same kind, type, char span) collapse to one, flag `duplicate_collapsed`.

**Frozen tests (coordinator):** `tests/test_verify.py`, about 40 cases: every rule, the Review Focus 1 to 3 inputs, number-word spelling, and property tests showing that every VerifiedItem's span_text equals the doc slice.

### Task 9: Store writer

**Files:** create `src/og/store/writer.py`.

**Interfaces:**
- `write_extraction(con, *, source: dict, doc: TextDoc, agreement: dict, run: RunInfo, items: list[VerifiedItem]) -> WriteStats`.
  - `source` is a sources.yaml entry.
  - `agreement` holds `{id, title, type, effective_date, base_agreement_id, is_form}`.
  - `RunInfo(prompt_version, model, calls: list[CallMeta])`.
- **Preconditions:**
  - `doc.source_sha256 == source["sha256"]`, else `ValueError("source pin mismatch")`.
  - Every item's `span_text == doc.text[char_start:char_end]`, else `ValueError`.
- **Transaction (`BEGIN IMMEDIATE`):**
  1. Upsert `source` and `agreement`.
  2. Upsert the `extraction_run` (source_id, prompt_version).
  3. Delete that run's prior obligations, their clause_refs, and that agreement's events, defined_terms, and agreement_party rows produced by the same run. Rows carry `extraction_run_id`. Schema change: add `extraction_run_id` to `event`, `defined_term`, `agreement_party`. Coordinator-authored migration in `schema.sql`, with tests.
  4. Insert parties: by name, normalized (casefold, strip punctuation and `, LLC`/`, Inc.` suffix variants for matching only; the stored name is the quote's form). Then `agreement_party(role)`.
  5. Insert events, each with its clause_ref.
  6. Insert obligations, each with its clause_ref (`grounded = 1`, section, page).
  7. Resolve `owed_by`/`owed_to`:
     - A role word (landlord, tenant, guarantor, provider, customer, lender) maps to the party holding that role in this agreement.
     - Else a normalized-name match.
     - Else NULL plus a WriteStats warning.
  8. Resolve `anchor_event` by normalized name among this agreement's and its base agreement's events. Else null the pair plus a warning.
  9. Commit.
- `WriteStats(obligations, events, parties, unresolved_parties, unresolved_anchors, replaced_rows)`.
- **Defined terms (deterministic, no model):** `extract_defined_terms(doc) -> list[(term, char_start, char_end)]` for patterns `(“Term”)`, `(the “Term”)`, and `“Term” means`. Inserted with clause_refs (span = the quoted term including quotes).

**Frozen tests (coordinator):** `tests/test_writer.py`. Covers idempotency (run twice gives identical counts, and other runs are untouched), pin mismatch, span mismatch, party resolution variants (Review Focus 5), anchor resolution through the base agreement, all writes visible through `visible_obligation`, and defined terms.

### Task 10: Gold format and scorer

**Gold format (`eval/gold/<doc_id>.yaml`):**
- Top level: `doc_id`, `source_sha256`, `labeled_by` (role, not name), `labeled_at`, `obligations: [...]`.
- Each obligation: `segment_id`, `char_start`, `char_end`, `span_text`, `type`, `owed_by`, `owed_to`, `description`, `amount`, `currency`, `due_date`, `anchor_event`, `offset_days`, `trigger`, `status`, `notes`. This is the artifact's db shape.

**Files:** create `src/og/eval/{__init__,gold,score}.py`.

**Interfaces:**
- `load_gold(path, doc: TextDoc) -> list[GoldItem]`. Validates `source_sha256 == doc.source_sha256` and every `span_text == doc.text[start:end]`, else `ValueError`. The gold set is held to the same invariant.
- `score(gold: list[GoldItem], predicted: list[PredItem]) -> Score`.
  - **Matching:** same `type`, character-span IoU ≥ 0.3, one-to-one, greedy by IoU descending with ties to the earlier gold.
  - **Output:** per-type `tp, fp, fn, precision, recall`; overall micro and macro values; field accuracy on matched pairs for `amount` (exact numeric), `due_date` (exact), `owed_by`/`owed_to` (role-normalized), and `status` (exact).
- `grounded_rate(con, doc_id)`: share of `visible_obligation` rows whose clause_refs are all grounded. Should be 1.0 by construction; reported anyway.
- `drops_count(log_path, doc_id)`.

**Frozen tests (coordinator):** `tests/test_eval_gold.py`, `tests/test_eval_score.py` (hand-built gold and predicted sets with known P/R; IoU edge cases; ties).

### Task 11: `make extract` wiring

**Files:** create `src/og/extract/__main__.py`; Makefile `extract` target, coordinator-edited to `uv run --locked python -m og.extract`.

**Behavior:**
- For each pinned source with `data/text/<id>.json`: load the TextDoc and verify its sha against the pin.
- Build the header from the preamble section's first 1500 chars.
- `Extractor.extract`, then `verify`, then `write_extraction`.
- Append drops to `logs/dropped.jsonl` (`{doc_id, prompt_version, reason, segment_id, span_text[:200], flags}`).
- Append call metadata to `logs/extract_calls.jsonl`, with no request bodies and no headers.
- Print per-document `obligations events parties drops cost_usd`.
- The agreement type, base agreement, and effective date come from new sources.yaml fields (`agreement_type`, `amends`, `effective_date`). The coordinator adds these in C0.

**Pricing table:** a constant in code (Sonnet 5.5 $2/$10 per MTok, cache read $0.20, cache write 1.25x input), labeled with its date.

**Frozen tests (coordinator):** `tests/test_extract_cli.py`, which runs the CLI end to end on the lease fixture with a FakeClient serving synthetic responses, into a temp DB. Checks counts, the drop log, and that no key-like string appears in any written file.

### Task 13: ADR-008 (docs)

`docs/decisions/ADR-008-structured-output-and-field-grounding.md`, from the Decisions section above. Same format as wave-1 ADRs.

---

## Coordinator steps

- **C0:** add `agreement_type`, `effective_date` (null where unknown), and the existing `amends` to every sources.yaml entry. Commit. Add `data/cache/` to .gitignore.
- **C1 (needs key, after Task 7 merges):**
  - Run the Extractor against 2 chunks of the Constant Contact first amendment (small, unredacted) and 1 chunk of the Carbonite lease (redactions).
  - Save the raw response JSON (body only) to `tests/fixtures/api/extract_v1/*.json`.
  - Add frozen replay tests showing that `parse_response` + `verify` on recorded responses produce items whose spans all ground.
- **C2 (reference set, user decision 2026-10-02):** the user chose a model-drafted, human-spot-checked reference set over hand labeling.
  1. Codex `gpt-6-astra` drafts 30 to 50 obligations for constantcontact-2011-ex1041. It is a different model family from the Sonnet extractor, which limits self-agreement bias. It works blind to any extraction output and writes `eval/gold/drafts/constantcontact-2011-ex1041.astra.yaml`, quoting verbatim from one segment each.
  2. The coordinator validates every quote against the TextDoc (exact substring of the cited segment) and adjudicates type, parties, amounts, and dates against the text. The coordinator records each change with a reason in the draft's `adjudication` field.
  3. The adjudicated draft is loaded into the labeler artifact (`labels` collection, `origin: astra-draft`).
  4. The user spot-checks about 10 labels there, marking each checked, editing it, or deleting it.
  5. Export to `eval/gold/constantcontact-2011-ex1041.yaml` with `provenance: {drafted_by: gpt-6-astra, adjudicated_by: coordinator, spot_checked: <n>}`.
  6. The README must call it a "model-drafted, human-spot-checked reference set", never hand-labeled gold.
  7. Labels are never edited after the first extraction run is scored. Any change after that needs a recorded reason and a re-score of every prior result.
- **C3:** `make ingest && make extract` on the integration checkout. Record cost and latency.
- **C4:**
  - Score the gold doc and write `eval/results/<date>-extract.json` (per-type P/R, field accuracy, grounded rate, drops, cost, latency, prompt_version, served model).
  - Run extraction 3 times on the gold doc for run-to-run variance (ADR-006). The cache must be bypassed with `OG_EXTRACT_NO_CACHE=1` for those runs.

## Out of scope (wave 3+)

Change-order diff, supersession edges, gates, triggers/guarantees edge extraction, MCP, UI, README numbers.
