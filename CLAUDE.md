# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Obligation Graph

Turn data center contracts (leases, colocation agreements, guarantees, amendments) into structured, clause-cited obligations. Expose them to agents over MCP. Make change orders arrive already checked, with cheap decision gates deciding which expensive checks actually run.

Public portfolio project. Built from scratch on public SEC filings only. No code, data, or naming from any employer or client.

## The one invariant

**Never state a term the system cannot point to.** Every obligation, answer, and change-order finding carries a clause reference (agreement, section, page, verbatim span). A deterministic grounding check verifies each span exists verbatim in the source text. Anything that fails is dropped and logged, never shown. Redacted terms (`[***]`, `[REDACTED]`, confidential-treatment brackets) are reported as `redacted`, never inferred.

If a change makes this invariant harder to keep, the change is wrong.

## Goals

1. **Extract**: each agreement becomes typed obligations with clause references.
2. **Ask**: "What do we owe the landlord at site X in the next 90 days?" answered with clauses attached, via MCP.
3. **Check a change order**: an amendment is diffed against the base agreement: what it supersedes, shifted deadlines, price changes, and conflicts flagged for legal and finance.
4. **Gate**: bounded yes/no decisions route each change order to only the checks it needs. Report cost, latency, and gate recall with and without gating.
5. **Measure**: precision/recall against a hand-labeled gold set, published in the README.

## Non-goals

No fine-tuning. No multi-tenancy, auth, or deployment. No negotiation pricing from the corpus (README names it as the next step). No LangChain, LlamaIndex, or agent frameworks.

## Corpus (`data/raw/`, gitignored except `data/sources.yaml`)

- Anchor: TeraWulf Form 8-K (2025), Exhibit 10.1, form of Recognition Agreement among the landlord, the tenant, and the tenant's credit support provider. URL: https://www.sec.gov/Archives/edgar/data/1083301/000110465925078084/tm2523008d2_8k.htm
- 4 to 6 additional data center lease / colocation / hosting agreements from EDGAR full-text search ("colocation agreement", "critical IT load", "datacenter lease").
- At least one base agreement plus its filed amendment, used as the change-order test case.
- `data/sources.yaml` records every document: URL, filer, filing date, exhibit number, local path, sha256.
- EDGAR requires a descriptive User-Agent with contact email. Rate limit to 10 req/s or less.

Tone rule: no commentary on any party's commercial position.

## Data model (SQLite, `data/graph.db`)

Nodes:
- `Party(id, name)`; role is per agreement: `AgreementParty(agreement_id, party_id, role)`, role in {landlord, tenant, guarantor, provider, customer, lender, other}
- `Agreement(id, title, type, effective_date, source_id, base_agreement_id NULL, is_form BOOL)`; `is_form` marks "form of" exhibits, whose blanks are never filled in
- `Site(id, name, location, capacity_mw NULL)`
- `Event(id, agreement_id, name, date NULL, clause_ref_id)`: anchor events a deadline counts from ("Commencement Date", "Delivery Date")
- `DefinedTerm(id, agreement_id, term, clause_ref_id)`: feeds the deterministic gate tier and anchor-event resolution
- `Obligation(id, agreement_id, site_id NULL, type, owed_by, owed_to, description, amount NULL, currency NULL, due_date NULL, anchor_event_id NULL, offset_days NULL, trigger NULL, status)`
  - type in {payment, delivery, sla, penalty, termination_right, guarantee, notice, insurance, other}
  - status (what the document says) in {active, superseded, redacted, blank}; `blank` = an unfilled placeholder in a form (`[●]`, `[•]`, `[ ]`, `____`), reported like `redacted`, never inferred
  - relative deadlines ("30 days after the Commencement Date") store `anchor_event_id` + `offset_days`; the effective due date is computed, never guessed
  - lifecycle (derived in a view, not stored): `superseded`, `pending` (no computable due date), `scheduled`. `fulfilled` and `violated` are reserved for the episodic layer and are not implemented
- `ClauseRef(id, obligation_id NULL, agreement_id, section, page, char_start, char_end, span_text, grounded BOOL)`

Edges (every edge carries a `clause_ref_id`; an uncited edge is an unstated term):
- `supersedes(obligation_id, superseded_obligation_id, change_order_id, clause_ref_id)`
- `guarantees(guarantee_obligation_id, guaranteed_obligation_id, clause_ref_id)` (the Google backstop maps here)
- `triggers(obligation_id, triggered_by_obligation_id, kind, clause_ref_id)`; kind in {default, cross_default, step_in, condition}. These link obligations across agreements (lease default -> recognition-agreement step-in -> guarantor), the risk that per-document extraction can't see

Readers (MCP, UI, eval) query the `visible_obligation` view only: an obligation with no grounded ClauseRef is not visible. The DB enforces the invariant; callers don't re-implement it.

Migrations in `src/og/store/schema.sql`. No ORM.

## Pipeline

1. **Ingest** (`src/og/ingest/`): HTML/PDF to normalized text. Preserve section headings, page numbers, and character offsets. Output `data/text/<doc_id>.json` with `{text, sections[], pages[], segments[]}`. Segments are numbered paragraphs (`p0001`...) with offsets; extraction cites them by ID.
2. **Extract** (`src/og/extract/`): Anthropic SDK directly. Tool-schema structured output matching the Obligation + ClauseRef shape. Chunk by section. Prompt and schema live in `prompts/` as versioned files. Span selection, not generation: the model cites a segment ID plus a quote, `span_text` comes first in the tool schema (quote before description), and the stored text is copied from the source. Grounding then audits the quote (ADR-005).
3. **Ground** (`src/og/ground.py`): deterministic. Whitespace-normalized exact match of `span_text` within `[char_start, char_end]`, fall back to exact match anywhere in the same section. Fail = drop + append to `logs/dropped.jsonl` with reason. No fuzzy matching.
4. **Store** (`src/og/store/`): write nodes and edges. Idempotent per `source_id` + prompt version.
5. **Change-order diff** (`src/og/change/`): see Decision gates. Output a `ChangeReport` with supersessions, new obligations, shifted dates, price deltas, and flagged conflicts, each finding with its ClauseRefs.

## Decision gates (change orders)

A change order rarely touches everything. Ask bounded questions first, run expensive checks only where the answer warrants it.

Gate questions (each a yes/no with confidence), one per downstream check:
- touches_price: rent, fees, escalators, caps
- touches_dates: delivery, commencement, milestones, notice periods
- touches_termination: termination rights, cure periods, events of default
- touches_guarantee: guarantor, backstop, credit support
- touches_sla: uptime, power, cooling, service credits
- touches_parties_or_sites: assignment, new site, capacity change

Three-tier cascade, cheapest first:
1. **Deterministic**: which sections of the base agreement the amendment references or restates; keyword and defined-term hits. A clear hit answers yes without a model call.
2. **Classifier backend**: pluggable `DecisionGate` protocol (`src/og/gates/`). Backends: `RulesGate`, `HaikuGate` (small Claude model with enum tool schema, the default baseline), `JevGate` (TypeSafe Jev, behind an env flag). Add others only behind the same protocol.
3. **Full check**: the focused extraction and diff for that category, on the expensive model.

Rules:
- **Fail open.** Low confidence, error, timeout, or backend unavailable means run the full check. A gate may skip work. It may never suppress a finding.
- Every gate decision is logged: question, backend, answer, confidence, latency, tokens, cost.
- Run every change-order eval twice, gated and ungated. The ungated run is ground truth for gate recall.
- **Gate recall is the headline metric**, not cost saved. A missed price change is worse than any token bill. Target 100% recall on the test set; report precision and skipped-check rate alongside.

## Models (env-configured, `.env.example`)

- `OG_EXTRACT_MODEL` default `claude-sonnet-5-5`
- `OG_GATE_MODEL` default `claude-haiku-4-5-20251001`
- `OG_JEV_ENABLED` default `false`, plus whatever Jev's API needs
- `ANTHROPIC_API_KEY`. No keys in code, logs, or fixtures.

## MCP server (`src/og/mcp/server.py`)

Python MCP SDK, stdio transport. Tools:
- `list_agreements()`
- `get_obligations(party?, site?, type?, include_superseded=false)`
- `upcoming_deadlines(days=90, party?)`
- `check_change_order(path)` returns the ChangeReport plus gate log summary

Every tool response includes ClauseRefs. A README section shows the Claude Desktop config.

## UI (`ui/index.html`)

One self-contained page served by a small local server reading `graph.db`. Left: obligations table, filterable by party, site, type, status. Right: the clause, verbatim, with section and page, shown when a row is clicked. Redacted terms visibly marked. Change-order view: findings list with superseded vs new side by side. It should look obvious to a controller. No dashboards, no charts.

## Evaluation (`eval/`)

- Gold set: one full agreement hand-labeled (30 to 50 obligations) in `eval/gold/<doc_id>.yaml`, plus the change-order case labeled with expected findings and expected gate answers.
- `make eval` prints: precision/recall per obligation type, grounding drops count, change-order finding recall, gate recall/precision per backend, cost and latency gated vs ungated.
- Results written to `eval/results/<date>.json` and summarized in the README. Never edit gold labels to make a run pass.

## Repo layout

```
src/og/{ingest,extract,store,change,gates,mcp}/
src/og/ground.py
prompts/
ui/
eval/{gold,results}/
data/{raw,text}/   (gitignored) data/sources.yaml (tracked)
logs/              (gitignored)
tests/
docs/decisions/    (one ADR per meaningful choice)
```

## Conventions

- Python 3.12, `uv` for env and deps, `ruff` + `pytest`. Makefile targets: `fetch`, `ingest`, `extract`, `eval`, `mcp`, `ui`, `test`.
- Commands: `make test`; single test `uv run pytest tests/test_ground.py::test_name -x`; lint `uv run ruff check . && uv run ruff format --check .`.
- TDD for `ground.py`, the gate cascade, and the change-order diff. These are the trust-bearing parts; they get tests before code.
- Record fixtures from real API responses once; tests run offline.
- One ADR in `docs/decisions/` for each non-obvious choice (no ORM, fail-open gates, exact-match grounding, model defaults).
- Small PRs. Each one passes `make test` and `ruff`. No commit adds unverified output to README numbers.
- No em dashes in README or user-facing copy.

## Build order

**Saturday**
1. Scaffold repo, Makefile, schema, ADR-001.
2. `fetch` + `sources.yaml`; pull corpus.
3. Ingest with offsets; tests on section/page mapping.
4. `ground.py` with tests first.
5. Extraction prompt + schema; run on anchor document; store.
6. Hand-label the gold agreement (human task, runs in parallel with 3 to 5).

**Sunday**
7. Change-order diff, ungated, with tests.
8. Gate protocol, RulesGate, HaikuGate, fail-open cascade, logging. JevGate behind flag if time allows.
9. MCP server; verify in Claude Desktop.
10. UI page.
11. `make eval`, gated vs ungated.
12. README: what it does, the invariant, eval table, gate results, 2-minute walkthrough link, and a short "Where this goes" section (see below).

## README "Where this goes" (one short section, no more)

The graph is semantic memory: what the contracts say now. The next layer is episodic memory: what happened. Each change order, approval, drawdown, and dispute is recorded as an episode (what changed, who approved, which checks ran, how it resolved). The `supersedes` edges, ChangeReports, and gate logs are the first episodes. With enough of them, the system can answer "how did the last three counterparties respond when we pushed delivery dates?" and price the next negotiation from the corpus of executed deals. Gate thresholds can also learn from episodes where a skipped check turned out to matter. Describe this as a direction, not a feature. Nothing in this section may claim behavior the code does not have.

## Definition of done

- `make fetch ingest extract eval` runs clean from a fresh clone with an API key.
- Every displayed or returned obligation has a grounded ClauseRef or is marked redacted.
- Eval table and gate table in the README come from a committed results file.
- MCP tools work in Claude Desktop against the built graph.
- The change-order demo shows at least one supersession, one shifted date or price, and one gate skip that the ungated run confirms was safe.
