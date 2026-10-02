# C13: UI browser acceptance (2026-10-02)

The coordinator drove `make ui` (`og.ui` on 127.0.0.1:8765, local `data/graph.db`, schema v4) in Chrome.

## Defect found and fixed

On first load, the obligations table was empty, with `Cannot read properties of undefined (reading 'forEach')`.

- **Cause:** `/api/agreements` returns the bare list from `og.query.list_agreements`, which is the pinned contract. The page read `out.agreements`, the MCP wrapper shape.
- **Why tests missed it:** the frozen page tests are static and do not execute the page's JavaScript.
- **Fix:** one line in `ui/index.html` that accepts the list.

## Checks after the fix

| Check | Result |
|---|---|
| Table loads | Pass. 525 rows, deterministic order, a pending note at the top, cited payer and payee names with roles. |
| Filter: agreement Carbonite + status redacted | Pass. 17 rows, each marked `[REDACTED]`, amount empty, payer and payee "unresolved". The footer reads "17 matching rows have an unresolved payer or payee". |
| Click a redacted payment row (obligation 204) | Pass. The clause panel shows the verbatim `$[***] per month for the period commencing on the Commencement Date ...`, Section 8, Page 17, chars 49862-50023, a `[REDACTED]` explanation, and agreement site 2121 South Price Road, Chandler, Arizona. |
| Change view: 3A (`endurance-2017-ex106`) | Pass. "Stored, verified report ... (no analysis performed)". The chain is base, then 1A (prior amendment), then 3A. Gate table: 4 checks ran (rules), guarantee and SLA skipped (haiku, unanimous no). |
| 3A shifted date side by side | Pass. Old clause: "scheduled to be surrendered to Landlord on June 30, 2018" (Section 1, page 1, chars 2208-2264). New clause: "expiring June 30, 2020" (chars 2775-2797). Delta 731 days. This confirms the report.py citation fix. |
| 3A price rows | Pass. `$35,596.80/month`, with context "July 1, 2018 - December 31, 2018" and no old-side quote, as stated. |
