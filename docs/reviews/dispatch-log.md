# Dispatch log

Accepted base SHA per dispatch (Supervision protocol item 5). Retries start from the last pushed worker commit or this base.

| Date | Task | Branch | Model | Base SHA | Prereqs | Dispatch | Outcome |
|------|------|--------|-------|----------|---------|----------|---------|
| 2026-10-02 | Wave 0 smoke | main | Pi zai/glm-5.3 | 12a8fed | none | ctx_e48494d4193b | succeeded (reachability, freeze OK, red 6 errors) |
| 2026-10-02 | Task 1 core | wave1-t1-core | Pi zai/glm-5.3 | 12a8fed | none | ctx_d6cf8d5a5620 | succeeded |
| 2026-10-02 | Task 2 fetch | wave1-t2-fetch | Pi zai/glm-5.3 | 12a8fed | none | ctx_f791c7332b4c | succeeded, merged PR #3 (c2012bb) |
| 2026-10-02 | Task 5 ADRs | wave1-t5-adr | Pi zai/glm-5.3 | 12a8fed | none | ctx_bd45c71b4919 | succeeded |
| 2026-10-02 | Corpus scout | main (read-only) | Claude sonnet | 12a8fed | none | ctx_df3db36c0c03 | failed at agent readiness (trust prompt); released |
| 2026-10-02 | Corpus scout retry | main (read-only) | Claude sonnet | 12a8fed | none | ctx_edbeda5b343f | succeeded (14 candidates, 6 selected) |
| 2026-10-02 | Task 5 ADRs | wave1-t5-adr | Pi zai/glm-5.3 | 0b6e4fa (rebased) | none | ctx_bd45c71b4919 | succeeded, merged PR #1 (22e6d11) |
| 2026-10-02 | Task 1 core | wave1-t1-core | Pi zai/glm-5.3 | 0b6e4fa (rebased) | none | ctx_d6cf8d5a5620 | succeeded, merged PR #2 (c343a6a) |
| 2026-10-02 | Task 3 ingest | wave1-t3-ingest | Pi zai/glm-5.3 | a6bea97 | Task 1 (PR #2) | ctx_dba9009ab0f3 | succeeded, merged PR #5 (1f9553f) |
| 2026-10-02 | Task 4 ground | wave1-t4-ground | Pi zai/glm-5.3 | a6bea97 | Task 1 (PR #2) | ctx_c0013517b0b4 | succeeded, merged PR #4 (c43852a) |
| 2026-10-02 | Task 3 rev 4 | wave1-t3-ingest-rev4 | Pi zai/glm-5.3 | 5a812fc | tests rev 4 | ctx_e12b299819c4 | succeeded, merged PR #6 (ddeeec8) |
