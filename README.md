# Obligation Graph

Obligation Graph turns data center contracts (leases, colocation agreements, guarantees, and their amendments) into structured obligations, each tied to the exact clause it came from. Agents query it over MCP. Amendments arrive already checked against the agreement they change, with cheap decision gates choosing which expensive checks run.

The corpus is public SEC filings only.

**Walkthrough video:** https://youtu.be/GPcP4T1syMk. The same tour, step by step, is in [`docs/walkthrough.md`](docs/walkthrough.md).

## The invariant

**Never state a term the system cannot point to.**

- **Citations.** Every obligation, answer, and change-order finding carries a ClauseRef: the agreement, section, page, character offsets, and a verbatim span.
- **Grounding check.** A deterministic check confirms the span exists, character for character, in the source text. Anything that fails is dropped and logged, never shown.
- **Redacted and blank terms.** Redactions (`[***]`) are reported as redacted, and form blanks as blank, never inferred.
- **Readers.** The MCP server, the UI, and the evaluation read the graph only through views that require a grounded citation, so callers never re-implement the rule.

## Quickstart

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this repo> && cd obligation-graph
uv sync --locked
echo 'OG_EDGAR_USER_AGENT="your-name research you@example.com"' > .env   # SEC requires a contact User-Agent
make fetch ingest extract eval
```

**No API key is needed.** Every model call made to build the committed results is recorded under `eval/recorded/`. The pipeline replays those recordings, rebuilds the same graph, and reproduces `eval/results/` at zero incremental cost.

**Replay modes:**
- `OG_REPLAY=strict` makes any missing recording an error instead of a live call.
- `OG_REPLAY=off` with `ANTHROPIC_API_KEY` set re-runs the models for real.

**Other commands:**

| Command | What it does |
|---|---|
| `make test` | Runs the full test suite (offline). |
| `make mcp` | Starts the MCP server (stdio). |
| `make ui` | Serves the review page at http://127.0.0.1:8765. |
| `make readme` | Checks that the tables below match the committed results. |

## How it works

```
SEC EDGAR (SHA-256 pinned) -> ingest (text, sections, pages, paragraphs)
  -> extract (Claude proposes quotes) -> verify (deterministic) -> store (SQLite)
  -> MCP server / UI / eval   (read through grounded views only)
```

1. **Extraction is span selection, not generation.** The model cites a paragraph id and copies a quote. The stored text is the source slice, never the model's words.
2. **Verification has no model in it.** A value (an amount, a date, an offset, a party role) is kept only when its evidence is in the quoted text. Otherwise it is nulled and logged.
3. **Change orders.**
   - **What is compared:** each amendment is compared against its chain, meaning the base agreement and the earlier amendments in the corpus.
   - **Finding kinds:** supersessions, shifted dates, price changes, and potential conflicts. Each is cited on both sides.
   - **Missing documents:** when an amendment targets a document that was never filed, the finding says so instead of matching a similar-looking clause.
4. **Decision gates.** Six yes/no questions decide which focused checks run: price, dates, termination, guarantee, SLA, and parties or sites.
   - **Rules first.** Keyword and section-reference rules answer first and can only say "run it".
   - **Then a small model.** Otherwise a small model answers three times, and a check is skipped only on three unanimous "no" answers.
   - **Fail open.** Any error, timeout, or disagreement runs the check. A gate may skip work; it can never hide a finding.
   - **Ground truth.** Every change order is also checked with no gates at all, and that run is the ground truth for gate recall.

5. **Deadlines.** Each obligation's timing is classified deterministically from its own quote, with no model involved:

   | Timing | What it means |
   |---|---|
   | **Scheduled** | It has a computable deadline from a dated, cited declaration, such as "Commencement Date: January 1, 2011". |
   | **Contingent** | It is due relative to a quoted outside event, such as "within thirty (30) days after receipt of an invoice". |
   | **Unresolved** | It has timing the system cannot compute, and the reason is stated, such as business days or a redacted day count. |
   | **No stated deadline** | The quote contains no timing language. |

   A "prior to" deadline is kept as a strict before-date, never shown as a due date.

Design decisions are recorded in [`docs/decisions/`](docs/decisions/) (ADR-001 to ADR-010).

## Results

All numbers below are generated from the committed aggregate (`eval/results/*-aggregate.json`) by `python -m og.eval readme-tables`, and a test fails if they drift.

- **Extraction reference set:** 50 obligations on the 2011 Constant Contact datacenter lease. It is a model-drafted, human-spot-checked reference set: drafted blind by a second model, adjudicated by the coordinator, and spot-checked by a person.
- **Precision on the reference lease** is a lower bound, because the reference set is a sample, not every obligation.
- **Change-order references** cover the First and Third Amendments. The user checked all 12 gate labels.
- **Timing reference sets** cover 50 obligations on the base lease plus 16 cross-document challenge cases. They are model-drafted and model-reviewed: drafted blind by gpt-6-astra, reviewed independently by Claude Opus 5.5 and gpt-6-astra, and adjudicated by the coordinator. No person spot-checked them.

<!-- og:tables:start -->
### Extraction: constantcontact-2011-ex1041

Reference set: model-drafted, human-spot-checked, scope sampled. Precision is a lower bound (unlabeled predictions count as false positives).

| type | gold | pred | tp | fp | fn | recall | precision (lower bound) |
|---|---:|---:|---:|---:|---:|---:|---:|
| delivery | 4 | 13 | 3 | 10 | 1 | 75.0% | 23.1% |
| guarantee | 0 | 2 | 0 | 2 | 0 | 100.0% | 0.0% |
| insurance | 3 | 16 | 3 | 13 | 0 | 100.0% | 18.8% |
| notice | 6 | 19 | 6 | 13 | 0 | 100.0% | 31.6% |
| other | 14 | 35 | 10 | 25 | 4 | 71.4% | 28.6% |
| payment | 10 | 54 | 7 | 47 | 3 | 70.0% | 13.0% |
| penalty | 4 | 4 | 4 | 0 | 0 | 100.0% | 100.0% |
| sla | 3 | 11 | 3 | 8 | 0 | 100.0% | 27.3% |
| termination_right | 6 | 12 | 5 | 7 | 1 | 83.3% | 41.7% |
| micro | 50 | 166 | 41 | 125 | 9 | 82.0% | 24.7% |
| macro | - | - | - | - | - | 87.5% | 35.5% |

Grounding integrity (visible obligations without a grounded citation): 0

| field | coverage | accuracy on known pairs |
|---|---:|---:|
| amount | 100.0% | 100.0% |
| anchor_event | 0.0% | - |
| currency | 100.0% | 100.0% |
| due_date | - | - |
| offset_days | 0.0% | - |
| owed_by | 100.0% | 92.7% |
| owed_to | 97.6% | 92.5% |
| status | 100.0% | 100.0% |

### Historical extraction variance (wave 2, n = 3)

Source: `eval/results/2026-10-02-extract-summary.json` (committed; not this run).

| metric | mean | sd | min | max |
|---|---:|---:|---:|---:|
| n_pred | 150.333 | 11.146 | 141.000 | 166.000 |
| owed_by_accuracy_on_known | 0.951 | 0.035 | 0.925 | 1.000 |
| precision_lower_bound_micro | 0.270 | 0.016 | 0.247 | 0.284 |
| proposal_grounding | 0.944 | 0.015 | 0.931 | 0.966 |
| recall_macro | 0.839 | 0.025 | 0.821 | 0.875 |
| recall_micro | 0.807 | 0.009 | 0.800 | 0.820 |

### Grounding drops (current extraction runs)

| reason | count |
|---|---:|
| event_name_not_in_quote | 8 |
| not_found_in_section | 1 |
| role_not_bound_to_name | 19 |
| total | 28 |

### Timing

Timing reference sets: model-drafted, adjudicated, scope sampled. Labels match within the same agreement (IoU >= 0.3); metrics are scored over matched obligations only. An invented bound is a predicted date the reference set does not state.

| set | labeled | matched | missing | kind | relation | bound date | invented | trigger span | reason |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| challenge | 16 | 16 | 0 | 100.0% | 100.0% | 100.0% | 0 | 81.2% | 100.0% |
| reference | 50 | 46 | 4 | 71.7% | 72.7% | 100.0% | 0 | 45.7% | 40.0% |

### Change order: constantcontact-2012-ex101

Findings (one per kind, new segment, and old side; duplicates across categories count once):

| mode | gold | predicted | tp | fp | fn | precision | recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| ungated | 10 | 10 | 8 | 2 | 2 | 80.0% | 80.0% |
| gated | 10 | 10 | 8 | 2 | 2 | 80.0% | 80.0% |

Gated retention of ungated findings: 100.0%

Gates (a skip may only save work, never suppress a finding):

| backend | recall vs reference | miss upper 95 | precision vs reference | recall vs baseline | precision vs baseline | notes |
|---|---:|---:|---:|---:|---:|---|
| cascade | 100.0% | 0.451 | 100.0% | 100.0% | 60.0% | skipped 1 of 6 (16.7%) |
| rules | 100.0% | 0.451 | 100.0% | 100.0% | 60.0% | tier 1 |
| haiku | - | - | - | - | - | coverage 16.7%; recall null without positives |

Skipped checks:

| category | kind | reference answer | ungated findings in category |
|---|---|---|---:|
| guarantee | confirmed_safe_skip | False | 0 |

Gate disagreements with the reference: 0

| mode | recorded usd | incremental usd | recorded latency ms |
|---|---:|---:|---:|
| ungated | 0.3848 | 0.0000 | 43960 |
| gated | 0.3779 | 0.0000 | 41335 |

### Change order: endurance-2017-ex106

Findings (one per kind, new segment, and old side; duplicates across categories count once):

| mode | gold | predicted | tp | fp | fn | precision | recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| ungated | 7 | 4 | 4 | 0 | 3 | 100.0% | 57.1% |
| gated | 7 | 4 | 4 | 0 | 3 | 100.0% | 57.1% |

Gated retention of ungated findings: 100.0%

Gates (a skip may only save work, never suppress a finding):

| backend | recall vs reference | miss upper 95 | precision vs reference | recall vs baseline | precision vs baseline | notes |
|---|---:|---:|---:|---:|---:|---|
| cascade | 100.0% | 0.632 | 75.0% | 100.0% | 50.0% | skipped 2 of 6 (33.3%) |
| rules | 100.0% | 0.632 | 75.0% | 100.0% | 50.0% | tier 1 |
| haiku | - | - | - | - | - | coverage 33.3%; recall null without positives |

Skipped checks:

| category | kind | reference answer | ungated findings in category |
|---|---|---|---:|
| guarantee | confirmed_safe_skip | False | 0 |
| sla | confirmed_safe_skip | False | 0 |

Gate disagreements with the reference: 2

| mode | recorded usd | incremental usd | recorded latency ms |
|---|---:|---:|---:|
| ungated | 0.3710 | 0.0000 | 36900 |
| gated | 0.3460 | 0.0000 | 34640 |

### Cost totals (change orders)

Change orders scored: 2

| mode | recorded usd | incremental usd | recorded latency ms |
|---|---:|---:|---:|
| ungated | 0.7558 | 0.0000 | 80860 |
| gated | 0.7239 | 0.0000 | 75975 |

Generated from the pinned aggregate by `python -m og.eval readme-tables`. Edit the results file, never this block.
<!-- og:tables:end -->

## Ask it over MCP

Four read-only tools, which never write and never call a model. Every returned item carries its clause citation.

| Tool | Returns |
|---|---|
| `list_agreements()` | Agreements with cited parties and sites, plus filing metadata |
| `get_obligations(party?, site?, type?, status?, lifecycle?, agreement?, include_superseded?, limit?, offset?)` | Cited obligations. `party` matches the payee (who is owed), by role or name. |
| `upcoming_deadlines(days=90, party?, as_of?)` | Obligations due in the window, plus pending ones listed separately |
| `check_change_order(path)` | The stored, verified change report and its gate decisions. It performs no new analysis. |

**Claude Desktop config.** Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` and restart Claude Desktop:

```json
{
  "mcpServers": {
    "obligation-graph": {
      "command": "/absolute/path/to/uv",
      "args": ["--directory", "/absolute/path/to/obligation-graph", "run", "--locked", "python", "-m", "og.mcp"]
    }
  }
}
```

**Questions that work against the built graph:**

| Question | What comes back |
|---|---|
| "List the agreements in the obligation graph." | 7 agreements |
| "What does the tenant owe the landlord under the 55 Middlesex Turnpike lease?" | Cited rent and additional-rent clauses. Invoice-driven items come back as contingent deadlines, such as "within thirty (30) days after receipt of an invoice", with the trigger quoted. |
| "Check change order endurance-2017-ex106." | The Suite 409 surrender date moved from June 30, 2018 to June 30, 2020 (+731 days), three new monthly rents, and the guarantee and SLA checks skipped by the gates |
| "Show redacted payment obligations in the Carbonite lease." | Rows marked `[REDACTED]`, with no amount filled in |

## Review page

`make ui` serves one local page for a controller:
- **Left:** an obligations table, filterable by payee, site, type, and status.
- **Right:** the clicked row's clause, verbatim, with agreement, section, and page.
- **Change orders:** each one shows the old clause beside the new clause, with the gate decisions that routed it.
- **Redacted terms:** visibly marked.

## Known limitations

- **Few computable dates.** Most obligations have no computable date, so they are pending, which is not the same as overdue. Of the 525 obligations:

  | Timing | Count |
  |---|---:|
  | Scheduled | 5 |
  | Contingent on a quoted event | 132 |
  | Unresolved, with a reason | 132 |
  | No stated deadline | 256 |

  The leading unresolved reasons are a timing word with no recognizable anchor (55), recurring rent schedules (39) and business-day counts (19). The only Business Day definition in the corpus excludes public holidays, so business days stay uncomputed.
- **Timing recall is conservative.** On the base-lease reference set, the timing kind is right for 72% of matched obligations. Most misses (9 of 13) lean toward less timing: an event-relative duty reported as no stated deadline, or as unresolved. The other 4 are classified as contingent or unresolved where the reference reads them differently. No obligation was given a date the reference does not support (0 invented dates).
  - Wording outside the closed grammar is the main cause: ordinal counts ("thirtieth (30th) day"), "when changes are made", and "Once ..., as soon as reasonably practicable".
  - Recurring rent schedules are not expanded into monthly dates.
- **Party roles bind in 2 of 7 filings.** Elsewhere the payer and payee stay empty rather than guessed.
- **Missing amendment.** The Second Amendment to the Constant Contact lease and an office space rider are referenced but were never filed. Clauses they hold are reported as unresolved targets, and 3A's rent changes carry no prior rate.
- **Closed grammars.** Date and role binding, the supersession cue list, and the target grammar are conservative closed rules. A phrasing outside them is dropped and logged, never accepted unverified.
- **Small gate test set.** Gate metrics come from two related amendments with few positive cases, so the miss-rate bounds are wide. Each change-order check is a single model call.
- **Strict scoring.** Change findings are scored by exact paragraph identity, so a correct clause pair that cites a neighboring paragraph counts as a miss.

## Where this goes

The graph is semantic memory: what the contracts say now. The next layer is episodic memory: what happened.

- **Episodes.** Each change order, approval, drawdown, and dispute would be recorded as an episode: what changed, who approved it, which checks ran, and how it resolved. The supersession edges, change reports, and gate logs are the first episodes.
- **What enough episodes enable.**
  - The system could answer questions such as how the last three counterparties responded when delivery dates were pushed.
  - It could inform the next negotiation from the corpus of executed deals.
  - Gate thresholds could learn from cases where a skipped check turned out to matter.

This is a direction, not a feature of the current code.

## How it was built

- **Roles.** Claude Opus 5.5 planned and coordinated. A Codex model reviewed each plan with executed probes against the real filings, under a fixed limit of three review rounds. GLM coding agents implemented each task.
- **Tests first.** Tests were written and frozen before implementation, and every change was re-run in a clean checkout before merging.
- **Cost.** Total model spend to build the committed results was about $4.23.
- **Records.** Plans, reviews, and acceptance records are in [`docs/`](docs/).
