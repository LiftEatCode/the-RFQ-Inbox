# Test runs

Output of three pytest commands at each commit. Run from a clean checkout of each commit.

At commit 1, `tests/test_score.py` does not exist yet, so the second command finds no tests.

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

