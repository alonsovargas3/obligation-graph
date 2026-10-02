# Real graph fixture (wave 4)

`real_v4.db` is the wave 3 integration graph (`data/graph.db` after the rev 2.3
change rerun, 2026-10-02), copied row for row into schema v4 by
`build_fixture.py`, plus the four cited site pins from `data/sources.yaml`.

Expected values:

| Measure | Value |
|---|---:|
| Visible obligations | 525 |
| With an effective due date | 0 |
| With `owed_to` bound | 168 |
| Landlord-payee rows | 114 |
| Visible site bindings | 4 |
| Visible party bindings | 4 |
| Fresh change runs | 4 |
| Visible change-finding refs | 56 |

`text/` holds the seven canonical TextDocs (public SEC filings). Tests copy the
db to a temp dir before use and never mutate this file.
