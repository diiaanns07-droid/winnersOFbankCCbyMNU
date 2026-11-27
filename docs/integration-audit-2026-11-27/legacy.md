# Оставшиеся ошибки старых тестов

Полный запуск на коде `831d82cf` в Windows с Python 3.12.14 и отдельным временным каталогом. Команда — `python -m pytest tests --ignore=tests/v2 -q`.

`41 failed, 1678 passed, 36 skipped, 2 warnings, 1 error in 392.76s (0:06:32)`

Каждый идентификатор с ошибкой сопоставлялся с отдельным запуском на исходной базе `d629aa0a` с таким же интерпретатором и зависимостями. Совпадение идентификатора указывает, что тест падал до объединения. Причина отдельной ошибки HTTP или тайм-аута могла меняться между запусками.

| Набор | Не прошло в общем запуске | Падало также на исходной базе | Предмет проверки |
|---|---:|---:|---|
| p04 | 7 | 7 | Нарезка v1 расходится между форматами. В одном договоре о границах требований ожидалось 49 элементов, получено 53. |
| p07 | 10 | 10 | Проверка происхождения замечаний, повторов и координат цитат, в том числе в PDF. |
| p09 | 8 | 8 | При сравнении редакций расходятся контрольные значения, идентификаторы и таблица исторических переходов. |
| p13 | 2 | 2 | Первый экран сохранённого отчёта v1 и воспроизведение примера. |
| p15 | 10 | 9 | Веб-сценарии ответов владельца, версия файла, код HTTP при несовпадении и завершение фонового прогона. |
| p17 | 5 | 5 | Упаковка и проверка исторического релиза, формулировка неполного вердикта и диагностика подмены. |

Для 41 из 42 неуспешных случаев тест с тем же идентификатором упал и на исходной базе.

Один оставшийся тест веб-формы прошёл отдельно на обеих ветках. В полном запуске соединение закрылось во время подготовки данных.

## Идентификаторы для воспроизведения

Для одного случая добавьте его идентификатор после `python -m pytest -q`. HTTP-сценарии могут проходить при запуске по одному.

| Случай | Результат сравнения |
|---|---|
| `tests/p04/test_p04_boundary.py::test_engine_entry_point_truncated_then_budget` | падал и на базе |
| `tests/p04/test_p04_contract.py::test_engine_runs_this_module_and_reads_warnings` | падал и на базе |
| `tests/p04/test_p04_formats.py::test_bank_document_registry_matches_across_formats` | падал и на базе |
| `tests/p04/test_p04_formats.py::test_close_conditions_each_get_own_evidence[pdf]` | падал и на базе |
| `tests/p04/test_p04_formats.py::test_close_conditions_registry_same_in_md_and_pdf` | падал и на базе |
| `tests/p04/test_p04_formats.py::test_run_review_end_to_end_close_conditions[pdf]` | падал и на базе |
| `tests/p04/test_p04_independent.py::test_cli_entry_point_reads_document_json` | падал и на базе |
| `tests/p07/test_provenance.py::test_rule_path_signed_rules_by_producing_stages` | падал и на базе |
| `tests/p07/test_provenance.py::test_trace_limit_candidate_reaches_engine_without_source` | падал и на базе |
| `tests/p07/test_provenance.py::test_verify_flags_llm_label_in_frozen_release_reports[other_topic_cashback]` | падал и на базе |
| `tests/p07/test_provenance.py::test_verify_flags_llm_label_in_frozen_release_reports[requirements]` | падал и на базе |
| `tests/p07/test_provenance.py::test_verify_flags_llm_label_in_frozen_release_reports[requirements_pdf]` | падал и на базе |
| `tests/p07/test_real_reader_cli.py::test_both_verify_entry_points_agree_on_engine_report` | падал и на базе |
| `tests/p07/test_release_repeats.py::test_control_wrong_quote_is_rejected[pdf]` | падал и на базе |
| `tests/p07/test_release_repeats.py::test_counts_and_repeats_grouped_into_places[md]` | падал и на базе |
| `tests/p07/test_release_repeats.py::test_counts_and_repeats_grouped_into_places[pdf]` | падал и на базе |
| `tests/p07/test_release_repeats.py::test_limit_same_label_in_both_cells[pdf]` | падал и на базе |
| `tests/p09/test_p09_cards_engine.py::test_cli_compare_second_edition_built_by_engine` | падал и на базе |
| `tests/p09/test_p09_cards_engine.py::test_engine_run_compare_with_canonical_reports` | падал и на базе |
| `tests/p09/test_p09_three.py::test_failed_foreign_stage_keeps_rule_proof` | падал и на базе |
| `tests/p09/test_p09_three.py::test_localized_unreadable_block_blocks_only_its_source` | падал и на базе |
| `tests/p09/test_p09_three.py::test_public_commands` | падал и на базе |
| `tests/p09/test_p09_three.py::test_three_matrix_for_the_team` | падал и на базе |
| `tests/p09/test_p09_three.py::test_v1_to_v3_direct_uses_original_ids` | падал и на базе |
| `tests/p09/test_p09_three.py::test_v2_to_v3_one_fixed_one_kept_one_new` | падал и на базе |
| `tests/p13/test_first_screen.py::test_recorded_example_reproduced_by_engine` | падал и на базе |
| `tests/p13/test_first_screen.py::test_release_report_first_screen_markup` | падал и на базе |
| `tests/p15/test_answer_versions.py::test_answer_from_other_version_starts_nothing[dev]` | падал и на базе |
| `tests/p15/test_answer_versions.py::test_answer_from_other_version_starts_nothing[shared-mock]` | падал и на базе |
| `tests/p15/test_answer_versions.py::test_conflicting_shas_and_form_answers_for_other_version` | падал и на базе |
| `tests/p15/test_answer_versions.py::test_file_without_sha_is_not_applied_and_manual_path_stays` | падал и на базе |
| `tests/p15/test_answer_versions.py::test_html13_export_multiline_accepted_for_own_version_only` | падал и на базе |
| `tests/p15/test_answer_versions.py::test_own_answer_creates_one_revision_and_repeat_returns_it[dev]` | падал и на базе |
| `tests/p15/test_answer_versions.py::test_own_answer_creates_one_revision_and_repeat_returns_it[shared-mock]` | падал и на базе |
| `tests/p15/test_answer_versions.py::test_p08_card_format_accepted` | оба одиночных запуска прошли |
| `tests/p15/test_answer_versions.py::test_published_p08_parser_agrees_where_compatible` | падал и на базе |
| `tests/p15/test_web_flow.py::test_questions_md_roundtrip_via_answers_file` | падал и на базе |
| `tests/p17/test_p17_release.py::test_full_example_two_critical_and_csv_semantics` | падал и на базе |
| `tests/p17/test_p17_release.py::test_offline_first_screen_keeps_partial_visible` | падал и на базе |
| `tests/p17/test_p17_release.py::test_one_command_passes` | падал и на базе |
| `tests/p17/test_p17_release.py::test_tampering_is_detected` | падал и на базе |
| `tests/p17/test_p17_rootcause.py::test_cli_check_exit_codes` | падал и на базе |
