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

## 2026-10-02: rev 2.2 (Astra wave-2 round 2)

Trigger: plan rev 2.2 (R2-1 to R2-8), from Astra's executed counterexamples in `docs/reviews/2026-10-02-astra-wave2-review.md` Round 2 section C.

Changed (old -> new assertion):
- `test_verify.py::test_description_without_numbers_kept`, renamed `test_description_is_the_quote_not_the_paraphrase`: description == model text -> description == quote == evidence.span_text (R2-3).
- `test_verify.py::test_description_with_numbers_from_quote_kept`, renamed `test_description_with_numbers_from_quote_is_still_the_quote`: description == model text -> description == quote (R2-3).
- `test_verify.py::test_nulled_amount_still_in_description_replaced_by_quote`: dropped the `(description, number_not_in_quote)` correction assertion, because R2-3 removes the digit rule. It still asserts amount null and description == quote.
- `test_verify.py` LEASE fixture: added lines `twodefs` (section 2.1) and `conflict`, `frac3`, `badgroup`, `longdays`, `cents` (section 3.1). Existing tests address segments by key, so no existing assertion changes.

Added:
- `test_verify.py`, R2-2: `test_r2_2_swapped_event_name_dropped`, `test_r2_2_event_name_as_quoted_term_kept_with_its_date`, `test_r2_2_date_not_bound_when_another_quoted_term_intervenes`, `test_r2_2_date_bound_to_the_nearest_preceding_name`.
- `test_verify.py`, R2-3: `test_waiver_paraphrase_never_stored`, `test_r2_3_description_never_carries_model_prose`.
- `test_verify.py`, R2-4: `test_r2_4_swapped_roles_dropped`, `test_r2_4_correct_roles_kept_beside_swapped`.
- `test_verify.py`, R2-5: `test_r2_5_deadline_conflict_keeps_due_date`, `test_r2_5_offset_alone_still_kept_on_conflict_line`.
- `test_verify.py`, R2-6: `test_r2_6_extra_decimal_digit_is_not_an_amount`, `test_r2_6_malformed_grouping_supports_nothing` (x3), `test_r2_6_day_count_suffix_is_not_an_offset` (x3), `test_r2_6_complete_money_token_with_cents_kept`.
- `test_extract_chunk.py`, R2-1: `test_context_ids_pinned_to_chunk_one_primary_segments`, `test_context_ids_pinned_when_chunk_one_exceeds_1500_chars`. `test_context_block_only_after_first_chunk` is unchanged.
- `test_pipeline_regressions.py` (new file; verify -> write_snapshot -> visible_obligation): `test_swapped_event_name_does_not_schedule_a_deadline`, `test_swapped_party_roles_do_not_make_landlord_the_payer`, `test_correct_party_roles_resolve_the_payer`, `test_deadline_conflict_writes_without_integrity_error`, `test_conflict_rerun_replaces_prior_snapshot`.
- `test_extract_cli.py`, R2-7: `test_no_cache_sample_of_amendment_rejected_before_any_call`.
- `test_eval_cli.py`, R2-8: `test_sampled_scope_reports_precision_only_as_lower_bound`, `test_full_agreement_scope_reports_precision`. Contract: `score.precision_lower_bound = {micro, macro, ...}`, present only for `scope: sampled`. Precision values are null under sampled; F1 is not asserted.

## 2026-10-02: rev 2.3 (Astra wave-2 round 3), additions only

Added to `tests/test_verify.py` (own R3 fixture doc; no existing assertion changed):
- `test_r3_event_date_from_a_later_sentence_is_not_bound`
- `test_r3_event_date_in_the_defining_sentence_is_kept`
- `test_r3_month_abbreviation_is_not_a_sentence_boundary`
- `test_r3_role_before_name_binds_and_next_party_role_does_not`
- `test_r3_and_is_a_party_boundary`
- `test_r3_parenthetical_roles_bind_to_their_own_names`

New `tests/test_pipeline_regressions_r3.py`, which carries the round-3 counterexamples through verify, the writer, and `visible_obligation`:
- `test_later_unrelated_date_does_not_schedule_the_deadline`
- `test_defining_date_schedules_the_deadline`
- `test_next_party_role_does_not_make_alpha_the_payer`
- `test_bound_roles_resolve_the_real_payer`

## 2026-10-02: rev 2.4 (Astra wave-2 round 4), additions only

Added to `tests/test_verify.py` (own R4 fixture doc):
- `test_r4_non_literal_event_dates_are_null` (6 cases)
- `test_r4_unquoted_name_with_shall_be_is_a_declaration`
- `test_r4_explicit_as_role_after_earlier_conjunction_binds`
- `test_r4_role_word_inside_a_company_name_is_not_a_role_prefix`
- `test_r4_role_of_another_entity_is_not_bound_across_a_verb_phrase`

New `tests/test_pipeline_regressions_r4.py`, which runs the five round-4 counterexamples through verify, the writer, and the view:
- `test_non_literal_event_date_never_schedules_a_deadline` (3 cases)
- `test_truncated_company_name_never_becomes_the_payer`
- `test_role_across_another_entity_never_becomes_the_payer`

## 2026-10-02: contract change, output schema nullable enums (C1)

`prompts/extract_v1.schema.json`: the live API (C1 recording, request `req_011CfcoE6JDYyxuTmKFM3BGT`) rejects `{"type": ["string","null"], "enum": [..., null]}` with "Enum value 'payment' does not match declared type". Nullable enums (`type`, `status`, `role`) are now `{"anyOf": [{"type": "string", "enum": [...]}, {"type": "null"}]}`. A live probe with the new form succeeded. No test assertion changed; `prompt_version` changes because the schema bytes changed. The parser's local validation is unchanged: it already accepts null for these fields.

## 2026-10-02: C1 recorded fixtures and replay test (additions only)

Added `tests/fixtures/api/extract_v1/` (3 real responses and their chunk texts, recorded with `prompt_version` extract_v1@6de99191) and `tests/test_extract_replay.py`:
- `test_fixtures_present`
- `test_recorded_response_parses` (3)
- `test_attempt_model_falls_back_to_message_model` (3): red against the merged Task 7 client. The live API returns `usage.iterations[].model = null` when no fallback ran, so the attempt model must fall back to `message.model`.
- `test_recorded_quotes_come_from_their_cited_line` (3)

## 2026-10-02: rev 2.5 (Astra wave-2 round 5), additions only

Added to `tests/test_verify.py` (own R5 fixture doc):
- `test_r5_governed_event_declarations_leave_the_date_null` (5)
- `test_r5_plain_declaration_still_binds`
- `test_r5_unsupported_party_declarations_bind_nothing` (5)
- `test_r5_whole_name_and_finite_descriptor_bind` (2)

New `tests/test_pipeline_regressions_r5.py`:
- `test_governed_event_date_never_schedules_a_deadline` (3)
- `test_unsupported_declaration_never_creates_a_visible_tenant` (3)

## 2026-10-02: rev 2.6 (Astra wave-2 round 6, real corpus), additions only

Added to `tests/test_verify.py` (own R6 fixture doc of exact real sentences from applieddigital-2026-ex101 p0005/p0032 and carbonite-2014-ex1024):
- `test_r6_partial_fields_and_operative_clauses_bind_nothing` (4)
- `test_r6_complete_corporate_fields_bind` (2)
- `test_r6_shall_mean_and_refer_to_is_a_connector`

New `tests/test_pipeline_regressions_r6.py`:
- `test_partial_field_or_clause_never_becomes_a_visible_party` (3)
- `test_complete_corporate_names_are_visible`
