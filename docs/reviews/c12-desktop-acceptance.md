# C12: Claude Desktop acceptance (2026-10-02)

The user ran the obligation-graph connector (MCP stdio server, `og.mcp`, configured in `claude_desktop_config.json` with `uv --directory <repo> run --locked python -m og.mcp`) in Claude Desktop on Opus 5.5 against the local `data/graph.db` (schema v4, 525 visible obligations). Desktop listed the connector with its 4 tools, each set to "Needs approval".

The screenshots are kept by the user and not committed, because they show unrelated personal workspace content.

| # | Prompt | Tool | Result |
|---|---|---|---|
| 1 | List the agreements in the obligation graph. | `list_agreements` | **Pass.** All 7 agreements with cited parties (CoreWeave guarantor / APLD ELN-02 landlord; Digital 55 Middlesex landlord / Constant Contact tenant), cited sites (55 Middlesex Turnpike for the CC lease and both amendments; 2121 South Price Road for Carbonite), and obligation counts summing to 525. Filing data was labeled as metadata. |
| 2 | What do we owe the landlord at 55 Middlesex Turnpike? | `get_obligations(party=landlord, site=55 Middlesex Turnpike, limit=500)` | **Pass.** It answered from cited clauses only: the base rent schedules, additional rent due within 30 days of invoice, and default terms. It stated that every item is pending with no calendar dates. |
| 3 | Check change order endurance-2017-ex106. | `check_change_order` | **Pass on content, fail on one citation (known bug, fix in flight).** It said "stored report, not a fresh analysis", the +731-day surrender shift (June 30, 2018 to June 30, 2020), the 3 rent amounts with no prior rent, the unresolved 2A / OS Rider / TKD Lease, and the gated guarantee and SLA skips. Claude independently flagged the date shift's old-side citation as malformed: "agreement ID shows a number". This is the `og/change/report.py` column-offset bug the Task 32 worker found. It is pinned by `tests/test_change_report_refs.py` and fixed in the Task 32 PR. **Re-run question 3 after that PR merges.** |
| 4 | Show redacted payment obligations in the Carbonite lease. | `get_obligations` | **Pass.** 14 of 58 Carbonite payment obligations are redacted; every amount was shown as `$[***]` and left empty, with the periods kept from the verbatim quotes. |

**Follow-ups:**
- **Repeated rent figures.** Claude Desktop questioned the identical CC 2011 Schedules B and C for months 37 to 72 ($48,189.26 / $49,634.94 / $51,123.99). Each figure appears twice in the filed lease text (offsets 49241/49759, 49294/49812, 49347/49865). This is the lease as written, not a duplicated extraction.
- **1A rent.** Claude Desktop reported that the 1A expansion rent amounts "weren't extracted". They exist as cited change-order price findings (5 rows), not as obligations, so `get_obligations` does not return them. The README demo should point to `check_change_order` for amendment rent.
