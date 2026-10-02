# Frozen test changes

Every change to a frozen test goes through the coordinator (Supervision protocol item 1). Old and new assertions are recorded here.

## 2026-10-02: ingest section rules, rev 4 (additions only)

Trigger: wave-1 corpus smoke. 4 of 7 real exhibits (including the TeraWulf anchor) number clauses as `1. Heading.` or `1.Heading`, which rev 3 excluded, so each ingested as 1 section. Mawson puts the clause number in its own table cell (`1.1 | In this Agreement...`), giving headings that start with `| `.

Added to `tests/test_ingest.py` (no existing assertion changed):
- `test_single_level_numbered_clauses`
- `test_number_like_lines_are_not_clauses`
- `test_clause_number_in_its_own_table_cell`

Red verified against the merged Task 3 implementation before dispatch. `tests/FROZEN.sha256` regenerated.

## 2026-10-02: schema v2 (wave 2 bootstrap B2)

Trigger: wave-2 plan rev 2 (Astra wave-2 finding 4/7) adds `run_id` and `textdoc_sha256` (NOT NULL) to `extraction_run`.

Changed in `tests/test_schema.py::test_extraction_run_unique_per_source_and_prompt`:
- Old: inserts `(source_id, prompt_version, model)` twice, expects IntegrityError on the second.
- New: inserts `(run_id, source_id, prompt_version, model, textdoc_sha256)` with distinct run_ids `r1`, `r2`; still expects IntegrityError from `UNIQUE(source_id, prompt_version)`. The assertion's intent is unchanged.
