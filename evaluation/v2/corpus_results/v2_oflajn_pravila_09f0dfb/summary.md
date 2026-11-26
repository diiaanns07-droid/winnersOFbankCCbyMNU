# Корпус evaluation/dev — v2 офлайн-правила (09f0dfb)

Кейсов 33 (не запускались 0), не измерено 0 (пропусков в счётчике 0).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 3 | 16 | 0 | 0.800 | 0.429 | 0.558 |

Чистые документы (8/8 измерено): замечаний 0, critical 0, major 0; документов с critical 0, с > 1 major 0, вердикт «нельзя» 0. Ложных тревог по счётчику: 0.

Recall по типам: boundary_conflict 0/5, event_conflict 0/5, missing_element 5/6, status_conflict 3/6, unit_mismatch 4/6.

Время 0.1 мин суммарно, вызовов 0, $0.

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status | defects | complete | 2 (0/2/0) | no/no |
| autopay.drop_promised.no_409_status | defects | complete | 1 (0/1/0) | undetermined/undetermined |
| autopay.event_conflict.insufficient_funds_credit | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| autopay.paraphrase.nfr | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| autopay.range_boundary.trigger_at_threshold | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| autopay.two_statuses.range_422 | defects | complete | 1 (0/1/0) | undetermined/undetermined |
| autopay.unit_change.limit_per_hour | defects | complete | 1 (0/1/0) | no/no |
| cardblock.base | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | defects | complete | 1 (0/1/0) | no/no |
| cardblock.drop_promised.no_last_digits | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| cardblock.event_conflict.unblock_daily_limit | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| cardblock.paraphrase.keep_authorizations | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| cardblock.range_boundary.days_400_at_30 | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| cardblock.two_statuses.reblock_200 | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| cardblock.unit_change.blocked_at_utc | defects | complete | 1 (0/1/0) | no/no |
| cashback.base | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| cashback.drop_promised.no_read_method | defects | complete | 1 (1/0/0) | undetermined/undetermined |
| cashback.event_conflict.category_effective_now | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| cashback.paraphrase.rate | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| cashback.range_boundary.cap_strict | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| cashback.two_statuses.bad_category_200 | defects | complete | 1 (0/1/0) | no/no |
| cashback.unit_change.accrued_in_tiyn | defects | complete | 1 (0/1/0) | undetermined/undetermined |
| edge.empty | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.base | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method | defects | complete | 2 (1/1/0) | no/no |
| transfer_limit.drop_promised.no_read_method | defects | complete | 1 (1/0/0) | undetermined/undetermined |
| transfer_limit.event_conflict.cancel_no_restore | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.paraphrase.new_limit | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.range_boundary.reaching_rejects | defects | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.two_statuses.range_200_error | defects | complete | 1 (0/1/0) | no/no |
| transfer_limit.unit_change.api_limit_in_tiyn | defects | complete | 1 (0/1/0) | no/no |
