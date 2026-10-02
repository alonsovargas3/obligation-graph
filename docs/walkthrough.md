# Two-minute walkthrough script

Record the screen at 1440 px wide. Have Claude Desktop (with the obligation-graph connector) and `make ui` open.

| Time | Show | Say |
|---|---|---|
| 0:00 to 0:15 | README top | "Obligation Graph turns public data center contracts into obligations that each point to the exact clause they came from. Rule one: never state a term the system cannot point to." |
| 0:15 to 0:40 | Review page, filter Carbonite and redacted, click the first payment row | "Every row is a quoted clause with its section, page and character range. Redacted amounts stay redacted. The system never guesses a number." |
| 0:40 to 1:10 | Review page, change order 3A | "Amendments are checked against the agreement they change. The Third Amendment moves the Suite 409 surrender date from June 30, 2018 to June 30, 2020, cited on both sides. Its rents are new amounts, with no prior rate, because the amendment they replace was never filed." |
| 1:10 to 1:30 | Same view, gate table | "Six yes or no gates decide which expensive checks run. Here guarantee and SLA were skipped on three unanimous answers. A separate run with every check confirms nothing was missed." |
| 1:30 to 1:50 | Claude Desktop: "What do we owe the landlord at 55 Middlesex Turnpike?" | "Agents ask the same graph over MCP. The answer comes back with clauses, and it says plainly that none of these has a computable due date yet." |
| 1:50 to 2:00 | README results table | "Every number here is generated from committed results, and a fresh clone reproduces them without an API key." |
