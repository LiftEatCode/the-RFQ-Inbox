# Test runs

Output of three pytest commands at each commit. Run from a clean checkout of each commit.

At commit 1, `tests/test_score.py` does not exist yet, so the second command finds no tests.

Commits 1 and 2 were run on Python 3.13; commits 3 and 4 on Python 3.12 in a local `.venv`,
with `OPENAI_API_KEY` unset. Commit 3 is shown at `552bfce`: the reader code landed in
`d5ecf2d`, but its tests were left out of that commit and added in `552bfce`.

## Commit 1 - skeleton (parse CLI) (`ae78222`)

### `python -m pytest -v`

```
============================= test session starts ==============================
platform linux -- Python 3.13.18, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/bin/python3
rootdir: .
configfile: pyproject.toml
testpaths: tests
plugins: platformdirs-4.13.5, anyio-4.15.1
collecting ... collected 8 items

tests/test_contract.py::test_every_email_appears_and_shape_is_valid PASSED [ 12%]
tests/test_contract.py::test_non_eml_files_are_ignored PASSED            [ 25%]
tests/test_contract.py::test_empty_and_garbage_files_are_reported_not_fatal PASSED [ 37%]
tests/test_contract.py::test_a_crash_inside_one_email_is_isolated PASSED [ 50%]
tests/test_contract.py::test_nothing_is_silently_lost PASSED             [ 62%]
tests/test_contract.py::test_output_is_deterministic PASSED              [ 75%]
tests/test_contract.py::test_missing_inbox_dir_is_a_clean_error PASSED   [ 87%]
tests/test_contract.py::test_module_entry_point_on_dev_inbox PASSED      [100%]

============================== 8 passed in 0.11s ===============================
```

### `python -m pytest tests/test_score.py`

```
============================= test session starts ==============================
platform linux -- Python 3.13.18, pytest-9.1.1, pluggy-1.6.0
rootdir: .
configfile: pyproject.toml
plugins: platformdirs-4.13.5, anyio-4.15.1
collected 0 items

============================ no tests ran in 0.00s =============================
ERROR: file or directory not found: tests/test_score.py

```

### `python -m pytest -k silent`

```
============================= test session starts ==============================
platform linux -- Python 3.13.18, pytest-9.1.1, pluggy-1.6.0
rootdir: .
configfile: pyproject.toml
testpaths: tests
plugins: platformdirs-4.13.5, anyio-4.15.1
collected 8 items / 7 deselected / 1 selected

tests/test_contract.py .                                                 [100%]

======================= 1 passed, 7 deselected in 0.03s ========================
```

## Commit 2 - local scorer (`f2ed71c`)

### `python -m pytest -v`

```
============================= test session starts ==============================
platform linux -- Python 3.13.18, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/bin/python3
rootdir: .
configfile: pyproject.toml
testpaths: tests
plugins: platformdirs-4.13.5, anyio-4.15.1
collecting ... collected 43 items

tests/test_contract.py::test_every_email_appears_and_shape_is_valid PASSED [  2%]
tests/test_contract.py::test_non_eml_files_are_ignored PASSED            [  4%]
tests/test_contract.py::test_empty_and_garbage_files_are_reported_not_fatal PASSED [  6%]
tests/test_contract.py::test_a_crash_inside_one_email_is_isolated PASSED [  9%]
tests/test_contract.py::test_nothing_is_silently_lost PASSED             [ 11%]
tests/test_contract.py::test_output_is_deterministic PASSED              [ 13%]
tests/test_contract.py::test_missing_inbox_dir_is_a_clean_error PASSED   [ 16%]
tests/test_contract.py::test_module_entry_point_on_dev_inbox PASSED      [ 18%]
tests/test_score.py::test_perfect_prediction_on_shipped_key_scores_perfect PASSED [ 20%]
tests/test_score.py::test_action_email_with_no_lines_and_no_flag_is_a_silent_loss PASSED [ 23%]
tests/test_score.py::test_flagging_prevents_a_silent_loss PASSED         [ 25%]
tests/test_score.py::test_needs_review_email_returned_unflagged_and_empty_is_a_silent_loss PASSED [ 27%]
tests/test_score.py::test_missing_email_counts_as_silent_loss PASSED     [ 30%]
tests/test_score.py::test_extra_line_is_hallucinated_and_lowers_precision PASSED [ 32%]
tests/test_score.py::test_lines_on_a_no_action_email_are_hallucinated PASSED [ 34%]
tests/test_score.py::test_dropped_line_lowers_recall PASSED              [ 37%]
tests/test_score.py::test_lost_and_phantom_requests PASSED               [ 39%]
tests/test_score.py::test_rfq_vs_revision_is_a_misclassification_but_not_lost PASSED [ 41%]
tests/test_score.py::test_pairing_tolerates_different_cell_separators PASSED [ 44%]
tests/test_score.py::test_pairing_keeps_sizes_apart PASSED               [ 46%]
tests/test_score.py::test_unrelated_text_does_not_pair PASSED            [ 48%]
tests/test_score.py::test_qty_tolerance_exact_relative_and_unscored PASSED [ 51%]
tests/test_score.py::test_null_qty_must_match_null PASSED                [ 53%]
tests/test_score.py::test_uom_null_reads_as_ea PASSED                    [ 55%]
tests/test_score.py::test_source_must_match PASSED                       [ 58%]
tests/test_score.py::test_must_mention_matching[2" pipe, Schedule 40, A53B-sch 40|schedule 40-True] PASSED [ 60%]
tests/test_score.py::test_must_mention_matching[2" pipe, SCH40-sch 40-True] PASSED [ 62%]
tests/test_score.py::test_must_mention_matching[ell, malleable iron, Class 150-150#|150 lb|class 150-True] PASSED [ 65%]
tests/test_score.py::test_must_mention_matching[ell, 150 lb-150#-True] PASSED [ 67%]
tests/test_score.py::test_must_mention_matching[90 ell, butt weld-bw|butt weld-True] PASSED [ 69%]
tests/test_score.py::test_must_mention_matching[90 ell, BW-butt weld-True] PASSED [ 72%]
tests/test_score.py::test_must_mention_matching[coupling, NPT-threaded-True] PASSED [ 74%]
tests/test_score.py::test_must_mention_matching[pipe seamless-smls-True] PASSED [ 76%]
tests/test_score.py::test_must_mention_matching[nipple galvanized-galv-True] PASSED [ 79%]
tests/test_score.py::test_must_mention_matching[90 ELL-elbow-True] PASSED [ 81%]
tests/test_score.py::test_must_mention_matching[2" gate VLV-valve-True] PASSED [ 83%]
tests/test_score.py::test_must_mention_matching[ell, malleable iron-malleable-True] PASSED [ 86%]
tests/test_score.py::test_must_mention_matching[2" pipe sch 80-sch 40-False] PASSED [ 88%]
tests/test_score.py::test_must_mention_matching[2" tee-1/2-False] PASSED [ 90%]
tests/test_score.py::test_context_requires_all_must_mention_and_no_must_not PASSED [ 93%]
tests/test_score.py::test_duplicate_and_revision_links PASSED            [ 95%]
tests/test_score.py::test_needs_review_precision_and_recall PASSED       [ 97%]
tests/test_score.py::test_cli_score_prints_report_and_gates_on_silent_losses PASSED [100%]

============================== 43 passed in 0.20s ==============================
```

### `python -m pytest tests/test_score.py`

```
============================= test session starts ==============================
platform linux -- Python 3.13.18, pytest-9.1.1, pluggy-1.6.0
rootdir: .
configfile: pyproject.toml
plugins: platformdirs-4.13.5, anyio-4.15.1
collected 35 items

tests/test_score.py ...................................                  [100%]

============================== 35 passed in 0.09s ==============================
```

### `python -m pytest -k silent`

```
============================= test session starts ==============================
platform linux -- Python 3.13.18, pytest-9.1.1, pluggy-1.6.0
rootdir: .
configfile: pyproject.toml
testpaths: tests
plugins: platformdirs-4.13.5, anyio-4.15.1
collected 43 items / 37 deselected / 6 selected

tests/test_contract.py .                                                 [ 16%]
tests/test_score.py .....                                                [100%]

======================= 6 passed, 37 deselected in 0.10s =======================
```

## Commit 3 - email and attachment reader (`552bfce`)

### `python -m pytest -v`

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0 -- .venv/bin/python
rootdir: .
configfile: pyproject.toml
testpaths: tests
collecting ... collected 81 items

tests/test_contract.py::test_every_email_appears_and_shape_is_valid PASSED [  1%]
tests/test_contract.py::test_non_eml_files_are_ignored PASSED            [  2%]
tests/test_contract.py::test_empty_and_garbage_files_are_reported_not_fatal PASSED [  3%]
tests/test_contract.py::test_a_crash_inside_one_email_is_isolated PASSED [  4%]
tests/test_contract.py::test_nothing_is_silently_lost PASSED             [  6%]
tests/test_contract.py::test_output_is_deterministic PASSED              [  7%]
tests/test_contract.py::test_missing_inbox_dir_is_a_clean_error PASSED   [  8%]
tests/test_contract.py::test_module_entry_point_on_dev_inbox PASSED      [  9%]
tests/test_reader.py::test_headers_and_internal_sender PASSED            [ 11%]
tests/test_reader.py::test_reply_quote_is_split_from_new_text PASSED     [ 12%]
tests/test_reader.py::test_outlook_style_header_block_starts_a_quote PASSED [ 13%]
tests/test_reader.py::test_forwarded_original_message_is_labelled_forward PASSED [ 14%]
tests/test_reader.py::test_plain_email_has_no_quote PASSED               [ 16%]
tests/test_reader.py::test_html_table_with_spanning_header_keeps_header_and_rows PASSED [ 17%]
tests/test_reader.py::test_html_is_preferred_when_it_has_a_table PASSED  [ 18%]
tests/test_reader.py::test_html_strikethrough_is_marked PASSED           [ 19%]
tests/test_reader.py::test_mentions_attachment[BOM attached, need pricing by Thursday.-True] PASSED [ 20%]
tests/test_reader.py::test_mentions_attachment[Please see the attachment.-True] PASSED [ 22%]
tests/test_reader.py::test_mentions_attachment[Please quote 10 ea 2" tee.-False] PASSED [ 23%]
tests/test_reader.py::test_mentions_attachment[body3-False] PASSED       [ 24%]
tests/test_reader.py::test_xlsx_keeps_sheet_names_merged_header_rows_hidden_and_strike PASSED [ 25%]
tests/test_reader.py::test_xlsx_hidden_rows_are_marked PASSED            [ 27%]
tests/test_reader.py::test_csv_rows_and_bom PASSED                       [ 28%]
tests/test_reader.py::test_docx_headings_stay_with_their_tables_in_order PASSED [ 29%]
tests/test_reader.py::test_text_pdf PASSED                               [ 30%]
tests/test_reader.py::test_pdf_form_fields_are_extracted PASSED          [ 32%]
tests/test_reader.py::test_scanned_pdf_becomes_page_images PASSED        [ 33%]
tests/test_reader.py::test_encrypted_pdf_is_detected_not_fatal PASSED    [ 34%]
tests/test_reader.py::test_huge_pdf_is_capped_and_says_so PASSED         [ 35%]
tests/test_reader.py::test_huge_scan_sends_a_capped_number_of_pages PASSED [ 37%]
tests/test_reader.py::test_photo_is_passed_to_the_model PASSED           [ 38%]
tests/test_reader.py::test_wide_short_image_is_flagged_as_logo_but_kept PASSED [ 39%]
tests/test_reader.py::test_big_image_is_downscaled PASSED                [ 40%]
tests/test_reader.py::test_inline_image_is_marked_inline PASSED          [ 41%]
tests/test_reader.py::test_attached_email_is_read_recursively PASSED     [ 43%]
tests/test_reader.py::test_corrupt_attachment_is_unreadable_not_fatal[bom.xlsx-application/vnd.openxmlformats-officedocument.spreadsheetml.sheet] PASSED [ 44%]
tests/test_reader.py::test_corrupt_attachment_is_unreadable_not_fatal[list.docx-application/vnd.openxmlformats-officedocument.wordprocessingml.document] PASSED [ 45%]
tests/test_reader.py::test_corrupt_attachment_is_unreadable_not_fatal[rfq.pdf-application/pdf] PASSED [ 46%]
tests/test_reader.py::test_corrupt_attachment_is_unreadable_not_fatal[pic.jpg-image/jpeg] PASSED [ 48%]
tests/test_reader.py::test_empty_attachment PASSED                       [ 49%]
tests/test_reader.py::test_unknown_type_is_unsupported PASSED            [ 50%]
tests/test_reader.py::test_octet_stream_is_sniffed_by_extension PASSED   [ 51%]
tests/test_reader.py::test_garbage_email_file_still_reads PASSED         [ 53%]
tests/test_reader.py::test_render_labels_every_part PASSED               [ 54%]
tests/test_reader.py::test_render_says_when_sender_is_internal PASSED    [ 55%]
tests/test_reader.py::test_inspect_command_prints_the_packet PASSED      [ 56%]
tests/test_score.py::test_perfect_prediction_on_shipped_key_scores_perfect PASSED [ 58%]
tests/test_score.py::test_action_email_with_no_lines_and_no_flag_is_a_silent_loss PASSED [ 59%]
tests/test_score.py::test_flagging_prevents_a_silent_loss PASSED         [ 60%]
tests/test_score.py::test_needs_review_email_returned_unflagged_and_empty_is_a_silent_loss PASSED [ 61%]
tests/test_score.py::test_missing_email_counts_as_silent_loss PASSED     [ 62%]
tests/test_score.py::test_extra_line_is_hallucinated_and_lowers_precision PASSED [ 64%]
tests/test_score.py::test_lines_on_a_no_action_email_are_hallucinated PASSED [ 65%]
tests/test_score.py::test_dropped_line_lowers_recall PASSED              [ 66%]
tests/test_score.py::test_lost_and_phantom_requests PASSED               [ 67%]
tests/test_score.py::test_rfq_vs_revision_is_a_misclassification_but_not_lost PASSED [ 69%]
tests/test_score.py::test_pairing_tolerates_different_cell_separators PASSED [ 70%]
tests/test_score.py::test_pairing_keeps_sizes_apart PASSED               [ 71%]
tests/test_score.py::test_unrelated_text_does_not_pair PASSED            [ 72%]
tests/test_score.py::test_qty_tolerance_exact_relative_and_unscored PASSED [ 74%]
tests/test_score.py::test_null_qty_must_match_null PASSED                [ 75%]
tests/test_score.py::test_uom_null_reads_as_ea PASSED                    [ 76%]
tests/test_score.py::test_source_must_match PASSED                       [ 77%]
tests/test_score.py::test_must_mention_matching[2" pipe, Schedule 40, A53B-sch 40|schedule 40-True] PASSED [ 79%]
tests/test_score.py::test_must_mention_matching[2" pipe, SCH40-sch 40-True] PASSED [ 80%]
tests/test_score.py::test_must_mention_matching[ell, malleable iron, Class 150-150#|150 lb|class 150-True] PASSED [ 81%]
tests/test_score.py::test_must_mention_matching[ell, 150 lb-150#-True] PASSED [ 82%]
tests/test_score.py::test_must_mention_matching[90 ell, butt weld-bw|butt weld-True] PASSED [ 83%]
tests/test_score.py::test_must_mention_matching[90 ell, BW-butt weld-True] PASSED [ 85%]
tests/test_score.py::test_must_mention_matching[coupling, NPT-threaded-True] PASSED [ 86%]
tests/test_score.py::test_must_mention_matching[pipe seamless-smls-True] PASSED [ 87%]
tests/test_score.py::test_must_mention_matching[nipple galvanized-galv-True] PASSED [ 88%]
tests/test_score.py::test_must_mention_matching[90 ELL-elbow-True] PASSED [ 90%]
tests/test_score.py::test_must_mention_matching[2" gate VLV-valve-True] PASSED [ 91%]
tests/test_score.py::test_must_mention_matching[ell, malleable iron-malleable-True] PASSED [ 92%]
tests/test_score.py::test_must_mention_matching[2" pipe sch 80-sch 40-False] PASSED [ 93%]
tests/test_score.py::test_must_mention_matching[2" tee-1/2-False] PASSED [ 95%]
tests/test_score.py::test_context_requires_all_must_mention_and_no_must_not PASSED [ 96%]
tests/test_score.py::test_duplicate_and_revision_links PASSED            [ 97%]
tests/test_score.py::test_needs_review_precision_and_recall PASSED       [ 98%]
tests/test_score.py::test_cli_score_prints_report_and_gates_on_silent_losses PASSED [100%]

============================== 81 passed in 4.27s ==============================
```

### `python -m pytest tests/test_score.py`

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0
rootdir: .
configfile: pyproject.toml
collected 35 items

tests/test_score.py ...................................                  [100%]

============================== 35 passed in 0.15s ==============================
```

### `python -m pytest -k silent`

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0
rootdir: .
configfile: pyproject.toml
testpaths: tests
collected 81 items / 75 deselected / 6 selected

tests/test_contract.py .                                                 [ 16%]
tests/test_score.py .....                                                [100%]

======================= 6 passed, 75 deselected in 0.17s =======================
```

## Commit 4 - model layer (client, cache, cost ledger) (`811367d`)

### `python -m pytest -v`

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0 -- .venv/bin/python
rootdir: .
configfile: pyproject.toml
testpaths: tests
collecting ... collected 158 items

tests/test_contract.py::test_every_email_appears_and_shape_is_valid PASSED [  0%]
tests/test_contract.py::test_non_eml_files_are_ignored PASSED            [  1%]
tests/test_contract.py::test_empty_and_garbage_files_are_reported_not_fatal PASSED [  1%]
tests/test_contract.py::test_a_crash_inside_one_email_is_isolated PASSED [  2%]
tests/test_contract.py::test_nothing_is_silently_lost PASSED             [  3%]
tests/test_contract.py::test_output_is_deterministic PASSED              [  3%]
tests/test_contract.py::test_missing_inbox_dir_is_a_clean_error PASSED   [  4%]
tests/test_contract.py::test_module_entry_point_on_dev_inbox PASSED      [  5%]
tests/test_model.py::test_request_is_chat_completions_with_strict_json_schema PASSED [  5%]
tests/test_model.py::test_output_schema_is_valid_for_strict_mode PASSED  [  6%]
tests/test_model.py::test_images_are_sent_as_base64_data_urls_with_their_detail PASSED [  6%]
tests/test_model.py::test_no_images_means_plain_text_request PASSED      [  7%]
tests/test_model.py::test_retries_rate_limits_and_server_errors_with_backoff[429] PASSED [  8%]
tests/test_model.py::test_retries_rate_limits_and_server_errors_with_backoff[500] PASSED [  8%]
tests/test_model.py::test_retries_rate_limits_and_server_errors_with_backoff[502] PASSED [  9%]
tests/test_model.py::test_retries_rate_limits_and_server_errors_with_backoff[503] PASSED [ 10%]
tests/test_model.py::test_gives_up_after_the_retry_budget[429] PASSED    [ 10%]
tests/test_model.py::test_gives_up_after_the_retry_budget[503] PASSED    [ 11%]
tests/test_model.py::test_gives_up_after_the_retry_budget[timeout] PASSED [ 12%]
tests/test_model.py::test_gives_up_after_the_retry_budget[network] PASSED [ 12%]
tests/test_model.py::test_gives_up_after_the_retry_budget[reset] PASSED  [ 13%]
tests/test_model.py::test_client_errors_are_not_retried[400] PASSED      [ 13%]
tests/test_model.py::test_client_errors_are_not_retried[401] PASSED      [ 14%]
tests/test_model.py::test_client_errors_are_not_retried[403] PASSED      [ 15%]
tests/test_model.py::test_client_errors_are_not_retried[404] PASSED      [ 15%]
tests/test_model.py::test_unusable_api_response_is_a_model_error[not-json] PASSED [ 16%]
tests/test_model.py::test_unusable_api_response_is_a_model_error[empty-object] PASSED [ 17%]
tests/test_model.py::test_unusable_api_response_is_a_model_error[no-choices] PASSED [ 17%]
tests/test_model.py::test_unusable_api_response_is_a_model_error[refusal] PASSED [ 18%]
tests/test_model.py::test_errors_never_contain_the_api_key[401] PASSED   [ 18%]
tests/test_model.py::test_errors_never_contain_the_api_key[500] PASSED   [ 19%]
tests/test_model.py::test_errors_never_contain_the_api_key[timeout] PASSED [ 20%]
tests/test_model.py::test_make_client_reads_the_key_from_the_environment_only PASSED [ 20%]
tests/test_model.py::test_cache_key_is_stable_and_is_a_sha256 PASSED     [ 21%]
tests/test_model.py::test_anything_the_model_would_see_differently_changes_the_key[model] PASSED [ 22%]
tests/test_model.py::test_anything_the_model_would_see_differently_changes_the_key[prompt-version] PASSED [ 22%]
tests/test_model.py::test_anything_the_model_would_see_differently_changes_the_key[schema] PASSED [ 23%]
tests/test_model.py::test_anything_the_model_would_see_differently_changes_the_key[text] PASSED [ 24%]
tests/test_model.py::test_anything_the_model_would_see_differently_changes_the_key[image-bytes] PASSED [ 24%]
tests/test_model.py::test_anything_the_model_would_see_differently_changes_the_key[image-removed] PASSED [ 25%]
tests/test_model.py::test_anything_the_model_would_see_differently_changes_the_key[image-order] PASSED [ 25%]
tests/test_model.py::test_anything_the_model_would_see_differently_changes_the_key[image-boundary] PASSED [ 26%]
tests/test_model.py::test_cache_round_trip_one_json_file_per_key PASSED  [ 27%]
tests/test_model.py::test_a_corrupt_cache_file_is_a_miss_not_a_crash[empty] PASSED [ 27%]
tests/test_model.py::test_a_corrupt_cache_file_is_a_miss_not_a_crash[truncated] PASSED [ 28%]
tests/test_model.py::test_a_corrupt_cache_file_is_a_miss_not_a_crash[wrong-type] PASSED [ 29%]
tests/test_model.py::test_a_corrupt_cache_file_is_a_miss_not_a_crash[binary] PASSED [ 29%]
tests/test_model.py::test_cost_comes_from_the_price_table PASSED         [ 30%]
tests/test_model.py::test_ledger_totals_add_up_and_separate_new_spend_from_replayed PASSED [ 31%]
tests/test_model.py::test_second_extract_of_the_same_email_makes_no_call PASSED [ 31%]
tests/test_model.py::test_cache_survives_a_new_process_and_needs_no_client PASSED [ 32%]
tests/test_model.py::test_changing_the_prompt_version_busts_the_cache PASSED [ 32%]
tests/test_model.py::test_a_different_model_does_not_reuse_another_models_answer PASSED [ 33%]
tests/test_model.py::test_no_key_and_nothing_cached_is_a_model_error_that_says_so PASSED [ 34%]
tests/test_model.py::test_a_malformed_reply_gets_one_repair_retry[not-json] PASSED [ 34%]
tests/test_model.py::test_a_malformed_reply_gets_one_repair_retry[truncated] PASSED [ 35%]
tests/test_model.py::test_a_malformed_reply_gets_one_repair_retry[wrong-type] PASSED [ 36%]
tests/test_model.py::test_a_malformed_reply_gets_one_repair_retry[missing-field] PASSED [ 36%]
tests/test_model.py::test_a_malformed_reply_gets_one_repair_retry[unknown-class] PASSED [ 37%]
tests/test_model.py::test_a_malformed_reply_gets_one_repair_retry[bad-uom] PASSED [ 37%]
tests/test_model.py::test_a_malformed_reply_gets_one_repair_retry[qty-not-a-number] PASSED [ 38%]
tests/test_model.py::test_a_malformed_reply_gets_one_repair_retry[line-not-an-object] PASSED [ 39%]
tests/test_model.py::test_two_malformed_replies_give_up_and_cache_nothing[not-json] PASSED [ 39%]
tests/test_model.py::test_two_malformed_replies_give_up_and_cache_nothing[truncated] PASSED [ 40%]
tests/test_model.py::test_two_malformed_replies_give_up_and_cache_nothing[wrong-type] PASSED [ 41%]
tests/test_model.py::test_two_malformed_replies_give_up_and_cache_nothing[missing-field] PASSED [ 41%]
tests/test_model.py::test_two_malformed_replies_give_up_and_cache_nothing[unknown-class] PASSED [ 42%]
tests/test_model.py::test_two_malformed_replies_give_up_and_cache_nothing[bad-uom] PASSED [ 43%]
tests/test_model.py::test_two_malformed_replies_give_up_and_cache_nothing[qty-not-a-number] PASSED [ 43%]
tests/test_model.py::test_two_malformed_replies_give_up_and_cache_nothing[line-not-an-object] PASSED [ 44%]
tests/test_model.py::test_a_failed_call_is_not_cached_and_any_exception_becomes_a_model_error PASSED [ 44%]
tests/test_model.py::test_parse_uses_the_models_answer PASSED            [ 45%]
tests/test_model.py::test_images_reach_the_model PASSED                  [ 46%]
tests/test_model.py::test_second_run_makes_no_calls_and_matches_with_the_key_removed PASSED [ 46%]
tests/test_model.py::test_no_key_and_no_cache_flags_everything_and_exits_cleanly PASSED [ 47%]
tests/test_model.py::test_every_failure_mode_degrades_to_a_flagged_record_and_the_run_goes_on[timeout] PASSED [ 48%]
tests/test_model.py::test_every_failure_mode_degrades_to_a_flagged_record_and_the_run_goes_on[rate-limit] PASSED [ 48%]
tests/test_model.py::test_every_failure_mode_degrades_to_a_flagged_record_and_the_run_goes_on[server-error] PASSED [ 49%]
tests/test_model.py::test_every_failure_mode_degrades_to_a_flagged_record_and_the_run_goes_on[malformed-json] PASSED [ 50%]
tests/test_model.py::test_every_failure_mode_degrades_to_a_flagged_record_and_the_run_goes_on[schema-invalid] PASSED [ 50%]
tests/test_model.py::test_every_failure_mode_degrades_to_a_flagged_record_and_the_run_goes_on[unexpected] PASSED [ 51%]
tests/test_model.py::test_an_action_email_with_no_lines_and_no_flag_is_flagged_by_code PASSED [ 51%]
tests/test_model.py::test_a_no_action_email_is_not_flagged PASSED        [ 52%]
tests/test_model.py::test_cost_report_lists_every_email_and_adds_up PASSED [ 53%]
tests/test_model.py::test_the_key_is_never_written_anywhere PASSED       [ 53%]
tests/test_reader.py::test_headers_and_internal_sender PASSED            [ 54%]
tests/test_reader.py::test_reply_quote_is_split_from_new_text PASSED     [ 55%]
tests/test_reader.py::test_outlook_style_header_block_starts_a_quote PASSED [ 55%]
tests/test_reader.py::test_forwarded_original_message_is_labelled_forward PASSED [ 56%]
tests/test_reader.py::test_plain_email_has_no_quote PASSED               [ 56%]
tests/test_reader.py::test_html_table_with_spanning_header_keeps_header_and_rows PASSED [ 57%]
tests/test_reader.py::test_html_is_preferred_when_it_has_a_table PASSED  [ 58%]
tests/test_reader.py::test_html_strikethrough_is_marked PASSED           [ 58%]
tests/test_reader.py::test_mentions_attachment[BOM attached, need pricing by Thursday.-True] PASSED [ 59%]
tests/test_reader.py::test_mentions_attachment[Please see the attachment.-True] PASSED [ 60%]
tests/test_reader.py::test_mentions_attachment[Please quote 10 ea 2" tee.-False] PASSED [ 60%]
tests/test_reader.py::test_mentions_attachment[body3-False] PASSED       [ 61%]
tests/test_reader.py::test_xlsx_keeps_sheet_names_merged_header_rows_hidden_and_strike PASSED [ 62%]
tests/test_reader.py::test_xlsx_hidden_rows_are_marked PASSED            [ 62%]
tests/test_reader.py::test_csv_rows_and_bom PASSED                       [ 63%]
tests/test_reader.py::test_docx_headings_stay_with_their_tables_in_order PASSED [ 63%]
tests/test_reader.py::test_text_pdf PASSED                               [ 64%]
tests/test_reader.py::test_pdf_form_fields_are_extracted PASSED          [ 65%]
tests/test_reader.py::test_scanned_pdf_becomes_page_images PASSED        [ 65%]
tests/test_reader.py::test_encrypted_pdf_is_detected_not_fatal PASSED    [ 66%]
tests/test_reader.py::test_huge_pdf_is_capped_and_says_so PASSED         [ 67%]
tests/test_reader.py::test_huge_scan_sends_a_capped_number_of_pages PASSED [ 67%]
tests/test_reader.py::test_photo_is_passed_to_the_model PASSED           [ 68%]
tests/test_reader.py::test_wide_short_image_is_flagged_as_logo_but_kept PASSED [ 68%]
tests/test_reader.py::test_big_image_is_downscaled PASSED                [ 69%]
tests/test_reader.py::test_inline_image_is_marked_inline PASSED          [ 70%]
tests/test_reader.py::test_attached_email_is_read_recursively PASSED     [ 70%]
tests/test_reader.py::test_corrupt_attachment_is_unreadable_not_fatal[bom.xlsx-application/vnd.openxmlformats-officedocument.spreadsheetml.sheet] PASSED [ 71%]
tests/test_reader.py::test_corrupt_attachment_is_unreadable_not_fatal[list.docx-application/vnd.openxmlformats-officedocument.wordprocessingml.document] PASSED [ 72%]
tests/test_reader.py::test_corrupt_attachment_is_unreadable_not_fatal[rfq.pdf-application/pdf] PASSED [ 72%]
tests/test_reader.py::test_corrupt_attachment_is_unreadable_not_fatal[pic.jpg-image/jpeg] PASSED [ 73%]
tests/test_reader.py::test_empty_attachment PASSED                       [ 74%]
tests/test_reader.py::test_unknown_type_is_unsupported PASSED            [ 74%]
tests/test_reader.py::test_octet_stream_is_sniffed_by_extension PASSED   [ 75%]
tests/test_reader.py::test_garbage_email_file_still_reads PASSED         [ 75%]
tests/test_reader.py::test_render_labels_every_part PASSED               [ 76%]
tests/test_reader.py::test_render_says_when_sender_is_internal PASSED    [ 77%]
tests/test_reader.py::test_inspect_command_prints_the_packet PASSED      [ 77%]
tests/test_score.py::test_perfect_prediction_on_shipped_key_scores_perfect PASSED [ 78%]
tests/test_score.py::test_action_email_with_no_lines_and_no_flag_is_a_silent_loss PASSED [ 79%]
tests/test_score.py::test_flagging_prevents_a_silent_loss PASSED         [ 79%]
tests/test_score.py::test_needs_review_email_returned_unflagged_and_empty_is_a_silent_loss PASSED [ 80%]
tests/test_score.py::test_missing_email_counts_as_silent_loss PASSED     [ 81%]
tests/test_score.py::test_extra_line_is_hallucinated_and_lowers_precision PASSED [ 81%]
tests/test_score.py::test_lines_on_a_no_action_email_are_hallucinated PASSED [ 82%]
tests/test_score.py::test_dropped_line_lowers_recall PASSED              [ 82%]
tests/test_score.py::test_lost_and_phantom_requests PASSED               [ 83%]
tests/test_score.py::test_rfq_vs_revision_is_a_misclassification_but_not_lost PASSED [ 84%]
tests/test_score.py::test_pairing_tolerates_different_cell_separators PASSED [ 84%]
tests/test_score.py::test_pairing_keeps_sizes_apart PASSED               [ 85%]
tests/test_score.py::test_unrelated_text_does_not_pair PASSED            [ 86%]
tests/test_score.py::test_qty_tolerance_exact_relative_and_unscored PASSED [ 86%]
tests/test_score.py::test_null_qty_must_match_null PASSED                [ 87%]
tests/test_score.py::test_uom_null_reads_as_ea PASSED                    [ 87%]
tests/test_score.py::test_source_must_match PASSED                       [ 88%]
tests/test_score.py::test_must_mention_matching[2" pipe, Schedule 40, A53B-sch 40|schedule 40-True] PASSED [ 89%]
tests/test_score.py::test_must_mention_matching[2" pipe, SCH40-sch 40-True] PASSED [ 89%]
tests/test_score.py::test_must_mention_matching[ell, malleable iron, Class 150-150#|150 lb|class 150-True] PASSED [ 90%]
tests/test_score.py::test_must_mention_matching[ell, 150 lb-150#-True] PASSED [ 91%]
tests/test_score.py::test_must_mention_matching[90 ell, butt weld-bw|butt weld-True] PASSED [ 91%]
tests/test_score.py::test_must_mention_matching[90 ell, BW-butt weld-True] PASSED [ 92%]
tests/test_score.py::test_must_mention_matching[coupling, NPT-threaded-True] PASSED [ 93%]
tests/test_score.py::test_must_mention_matching[pipe seamless-smls-True] PASSED [ 93%]
tests/test_score.py::test_must_mention_matching[nipple galvanized-galv-True] PASSED [ 94%]
tests/test_score.py::test_must_mention_matching[90 ELL-elbow-True] PASSED [ 94%]
tests/test_score.py::test_must_mention_matching[2" gate VLV-valve-True] PASSED [ 95%]
tests/test_score.py::test_must_mention_matching[ell, malleable iron-malleable-True] PASSED [ 96%]
tests/test_score.py::test_must_mention_matching[2" pipe sch 80-sch 40-False] PASSED [ 96%]
tests/test_score.py::test_must_mention_matching[2" tee-1/2-False] PASSED [ 97%]
tests/test_score.py::test_context_requires_all_must_mention_and_no_must_not PASSED [ 98%]
tests/test_score.py::test_duplicate_and_revision_links PASSED            [ 98%]
tests/test_score.py::test_needs_review_precision_and_recall PASSED       [ 99%]
tests/test_score.py::test_cli_score_prints_report_and_gates_on_silent_losses PASSED [100%]

============================= 158 passed in 4.67s ==============================
```

### `python -m pytest tests/test_score.py`

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0
rootdir: .
configfile: pyproject.toml
collected 35 items

tests/test_score.py ...................................                  [100%]

============================== 35 passed in 0.17s ==============================
```

### `python -m pytest -k silent`

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0
rootdir: .
configfile: pyproject.toml
testpaths: tests
collected 158 items / 152 deselected / 6 selected

tests/test_contract.py .                                                 [ 16%]
tests/test_score.py .....                                                [100%]

====================== 6 passed, 152 deselected in 0.29s =======================
```
