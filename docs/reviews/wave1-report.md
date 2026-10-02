# Wave 1 report (2026-10-02)

Scope: CLAUDE.md build steps 1 to 4 (scaffold, fetch, ingest, ground) plus ADRs. Coordinator: Opus 5.5. Advisor: Codex gpt-6-astra (3 review rounds, verdict agree-to-proceed). Implementers: Pi on zai/glm-5.3, supervised through Orca on the devbox. Grok fallback was not needed.

## Outcome per task

| Task | Outcome | Merged | Worker commits | Acceptance (coordinator-run, isolated checkout) |
|------|---------|--------|----------------|-----------------------------------------------|
| 1 TextDoc + schema | succeeded | PR #2 | c343a6a | 60/60; schema identical to the reviewed reference |
| 2 Fetch | succeeded | PR #3 | 19ea12f, c2012bb | 24/24 (23 frozen + 1 recorded); 7 pins match bytes; 15 SEC requests in one coordinator-owned window |
| 3 Ingest | succeeded, one follow-up | PR #5, PR #6 | 1f9553f, ddeeec8 | 23/23 after rev 4 |
| 4 Ground + markers | succeeded | PR #4 | c43852a | 282 passed, 2 intentional skips; identical to reference |
| 5 ADRs | succeeded | PR #1 | 22e6d11 | 7 ADRs, spec-reviewed against CLAUDE.md |

All merged commits were produced by Pi zai/glm-5.3. Dispatch IDs and base SHAs are in `dispatch-log.md`.

## Integration gate (fresh clone of main at 9db496a)

- `sha256sum --check tests/FROZEN.sha256`: OK.
- `pytest`: 389 passed, 2 skipped (intentional single-character fallback cases). 391 collected test IDs are in `wave1-test-ids.txt`.
- `make lint`: clean.
- `make fetch`: idempotent, all 7 pins verified, no document downloads.
- `make ingest`: 7 documents; every output loads and validates as a TextDoc.

| Document | chars | sections | pages | segments |
|----------|------:|---------:|------:|---------:|
| terawulf-2025-ex10-1 (anchor, form) | 41316 | 15 | 19 | 149 |
| constantcontact-2011-ex1041 (base lease) | 188592 | 293 | 65 | 1017 |
| constantcontact-2012-ex101 (1st amendment) | 12591 | 14 | 10 | 114 |
| endurance-2017-ex106 (3rd amendment) | 8855 | 8 | 4 | 57 |
| carbonite-2014-ex1024 (redacted lease) | 219238 | 237 | 67 | 1275 |
| mawson-2025-ex101 (colocation) | 82489 | 101 | 33 | 346 |
| applieddigital-2026-ex101 (guaranty) | 45725 | 14 | 14 | 120 |

## What supervision caught

- Workers asked instead of working around a pre-existing lint failure: locked ruff formats code blocks in Markdown. Fixed on main (0b6e4fa).
- Corpus smoke: 4 of 7 exhibits, including the anchor, ingested as a single section, because they use single-level `1.` clause numbering, which rev 3 excluded. Mawson splits clause numbers into table cells. The coordinator added three frozen tests (red-verified) and a rule change (rev 4). The same worker implemented it, and sections now read correctly (anchor: 15 sections, "1 Definitions", "2 Confirmation Regarding ...", ...).
- One worker misreported a test count (31 vs 19) and one mislabeled expected red errors. The coordinator's own runs are the record, not worker summaries.

## Known limits carried forward

- Mawson has no section 3.4: its line does not start with a capital letter, so it stays body text by rule. Some headings are body sentences cut at the 80-character cap. Both behaviors follow the rules.
- PDF ingest is not implemented (no PDF exhibits in the corpus).
