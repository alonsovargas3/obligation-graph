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
| 2026-10-02 | Wave 2 Task 6 TOC | wave2-t6-toc | Pi zai/glm-5.3 | df000bd | B2 | ctx_3e24be08acdd | running |
| 2026-10-02 | Wave 2 Task 9 writer | wave2-t9-writer | Pi zai/glm-5.3 | df000bd | B2 | ctx_32d0edc8a3f2 | running |
| 2026-10-02 | Wave 2 Task 13 ADR-008 | wave2-t13-adr | Pi zai/glm-5.3 | df000bd | B2 | ctx_87c1bc3a7169 | running |
| 2026-10-02 | Wave 2 Task 13 follow-up | wave2-t13-adr | Pi zai/glm-5.3 | 11605d2 | review | ctx_2c8202f3887a | succeeded, merged PR #7 (807d99c) |
| 2026-10-02 | Wave 2 Task 6 TOC | wave2-t6-toc | Pi zai/glm-5.3 | df000bd | B2 | ctx_3e24be08acdd | succeeded, merged PR #8 (ec732bf) |
| 2026-10-02 | Wave 2 Task 7 client | wave2-t7-client | Pi zai/glm-5.3 | 4bcd002 | rev 2.2 | ctx_580f7aea6580 | running |
| 2026-10-02 | Wave 2 Task 10 eval | wave2-t10-eval | Pi zai/glm-5.3 | 4bcd002 | rev 2.2 | ctx_1b740b0b9007 | running |
| 2026-10-02 | Wave 2 Task 8 verify | wave2-t8-verify | Pi zai/glm-5.3 | a6015e0 | rev 2.3 | ctx_105864b3508e | running |

## Wave 3A (2026-10-02), accepted base 999136e

Pi zai/glm-5.3 workers on devbox worktrees `obligation-graph-wave3-<n>`: t14-rules, t15-haiku, t16-client, t17-verify, t18-writer, t20-eval, t21-adr.
Wave 3B: t19-cli dispatched from e4a9d9e (Tasks 14-18, 21 merged).

## Wave 4A (2026-10-02), accepted base 2987d96

Pi zai/glm-5.3 workers: t30-query, t33-replay, t34-eval, t35-adr.
