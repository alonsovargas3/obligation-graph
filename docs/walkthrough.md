# Walkthrough

Video: https://youtu.be/GPcP4T1syMk

This guide follows the same tour as the video. It runs against a local build of the graph, so you can reproduce each step yourself.

## Documents used

The review page and the MCP tools use document IDs:

| Document | ID | Description |
|---|---|---|
| Base lease | `constantcontact-2011-ex1041` | 2011 Datacenter Lease, 55 Middlesex Turnpike, Bedford MA |
| First Amendment | `constantcontact-2012-ex101` | 2012 amendment: Suite 418A expansion, new SLA table |
| Third Amendment | `endurance-2017-ex106` | 2017 amendment: Suite 409 extended two years |
| Carbonite lease | `carbonite-2014-ex1024` | 2014 Turn Key Datacenter Lease, Chandler AZ, heavily redacted |

## Setup

1. Build the graph. Follow [Quickstart](../README.md#quickstart) in the README. No API key is needed: the recorded model calls are replayed.
2. Start the review page with `make ui`, then open `http://127.0.0.1:8765`.
3. For the agent step, connect the MCP server to Claude Desktop as shown in [Ask it over MCP](../README.md#ask-it-over-mcp).

## 1. The invariant

The README states the one rule: never state a term the system cannot point to. Every obligation keeps the exact contract language that supports it.

## 2. Obligations and redacted rent

1. On the review page, the obligations table lists the 525 obligations in this build. The note above it counts the pending ones: obligations with no computable due date.
2. Set **Agreement** to `carbonite-2014-ex1024` and **Status** to `redacted`. The table shrinks to 17 rows, each with a `[REDACTED]` tag.
3. Click the second row, a payment: `$[***] per month for the period commencing on the Commencement Date ...`.
4. The **Clause** panel shows the verbatim passage, Section 8, Page 17, and the character range. The rent amount is redacted in the filing, and the system keeps it redacted instead of guessing a number.
5. The row's **Due / timing** tag reads `unresolved: recurring_schedule`: the rent repeats monthly, so no single due date is computed.

## 3. Amendments: what changed

1. Scroll to **Change orders** and choose `endurance-2017-ex106 (amends constantcontact-2011-ex1041)`, the Third Amendment.
2. The status lines show this is a stored, verified report, not a fresh analysis, and give the chain: base lease, then First Amendment, then Third Amendment.
3. **Shifted dates (1)** shows the old and new clauses side by side. The Suite 409 surrender date moves from June 30, 2018 to June 30, 2020, and both dates are quoted.
4. **Price changes (3)** shows new rents, starting with $35,596.80 per month for July through December 2018. No prior rate is shown, because the amendment that held it (the Second Amendment) was never filed. The gap is shown, not filled in.
5. **New obligations without a supersession (7)** lists the obligations the amendment introduces, each with its quoted clause.

## 4. Gates: deciding which checks to run

1. **Gate decisions (gated run)** summarizes "6 questions, 4 checks ran, 2 skipped."
2. Simple rules run first. Where they don't decide, a small model answers three times, and a check is skipped only after three unanimous "no" answers. Disagreement, an error, or a timeout runs the check.
3. For this amendment, the guarantee and SLA checks were skipped. A run with every check turned on produced the same findings.

## 5. Ask an agent

1. In Claude Desktop, open a new chat and ask: **What does the tenant owe the landlord under the 55 Middlesex Turnpike lease?**
2. The agent calls the obligation graph's `get_obligations` tool and answers with section references for each item.
3. Where the lease ties a payment to an event, the trigger is quoted, for example generator fuel due within 30 days of each invoice (§3.5.4). Where the documents give no computable date, the answer says so. Pending does not mean overdue.
4. The agent reports what the contract requires. It cannot report a current balance, because the graph does not record payments.

## 6. Reproducibility

The README's [Results](../README.md#results) tables are generated from committed evaluation results. A fresh clone replays the recorded model calls and reproduces them without an API key.

## Notes

- Selecting a change order retrieves a stored report; it does not run a new analysis.
- A skipped check was not performed. It does not mean the check ran and passed.
- Grounded citations verify that each quote appears in the source. They do not guarantee complete extraction or perfect interpretation.
- Timing across all 525 obligations: 5 have a computed date bound, 132 are contingent on a quoted event, 132 are unresolved with a reason, and 256 state no deadline.
- An agent may flag the base lease's rent table (a drop of about 60% at month 25, and two suites with identical figures from month 37) as an extraction error. Section 8 of the filed lease states exactly those figures.
- An agent may invent suite labels such as "A/B/C". The lease names them Suite 1.5, 1.5.1, 1.5.2 and 1.14A.

## Troubleshooting

- **The table is empty or shows an error:** stop `make ui`, pull `main`, and start it again.
- **Claude Desktop shows no obligation-graph tools:** quit Claude Desktop fully and reopen it. The server needs `data/graph.db` to exist.
