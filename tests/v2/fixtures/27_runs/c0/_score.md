| Кейс | с | cr/maj/min | конфл. | найдено (! — critical) | промах |
| :--- | ---: | :--- | ---: | :--- | :--- |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status | 104.8 | 0/3/3 | 1 | unit_mismatch, missing_element |  |
| autopay.event_conflict.insufficient_funds_credit | 85.3 | 1/2/2 | 1 | event_conflict! |  |
| autopay.range_boundary.trigger_at_threshold | 83.2 | 1/3/2 | 1 | boundary_conflict! |  |
| autopay.two_statuses.range_422 | 99.2 | 1/0/5 | 1 | status_conflict! |  |
| autopay.unit_change.limit_per_hour | 71.0 | 0/3/2 | 1 | unit_mismatch |  |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | 65.3 | 1/3/2 | 2 | unit_mismatch, status_conflict! |  |
| cardblock.event_conflict.unblock_daily_limit | 68.4 | 1/3/1 | 1 | event_conflict! |  |
| cardblock.range_boundary.days_400_at_30 | 42.8 | 1/1/2 | 1 | boundary_conflict! |  |
| cardblock.two_statuses.reblock_200 | 70.0 | 1/1/2 | 1 | status_conflict! |  |
| cardblock.unit_change.blocked_at_utc | 36.3 | 0/2/1 | 2 | unit_mismatch |  |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict | 74.2 | 2/3/3 | 2 | event_conflict!, boundary_conflict! |  |
| cashback.event_conflict.category_effective_now | 63.7 | 1/3/2 | 1 | event_conflict! |  |
| cashback.range_boundary.cap_strict | 80.3 | 1/3/3 | 1 | boundary_conflict! |  |
| cashback.two_statuses.bad_category_200 | 97.9 | 1/3/3 | 1 | status_conflict! |  |
| cashback.unit_change.accrued_in_tiyn | 91.2 | 0/4/2 | 1 |  | unit_mismatch |
| official | 96.4 | 5/4/6 | 5 | К1!, К2!, К3!, К4!, С2, С5, С16, С17 | К5, С1, С3, С4, С6, С7, С8, С9, С10, С11, С12, С13, С14, С15, С18, С19, С20 |
| open2.capital | 109.2 | 3/5/4 | 5 | К1!, К2, К3!, С1, С2, С5 | К4, С3, С4 |
| open2.grace | 92.6 | 4/2/5 | 4 | К1!, К2!, К3!, С1, С2, С4 | К4, С3, С5 |
| open2.insurance | 147.7 | 3/6/6 | 3 | К1!, К3!, К4, С1, С2 | К2, С3, С4, С5 |
| open2.qr | 112.7 | 5/6/4 | 5 | К1!, К2!, К3!, К4, С1, С2 | С3, С4, С5 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method | 53.7 | 2/0/3 | 1 | status_conflict!, missing_element! |  |
| transfer_limit.event_conflict.cancel_no_restore | 101.9 | 1/2/3 | 2 | event_conflict! |  |
| transfer_limit.range_boundary.reaching_rejects | 86.4 | 1/2/3 | 1 | boundary_conflict! |  |
| transfer_limit.two_statuses.range_200_error | 92.4 | 1/1/4 | 1 | status_conflict! |  |
| transfer_limit.unit_change.api_limit_in_tiyn | 64.7 | 0/3/2 | 1 | unit_mismatch |  |

* official: К 4/5 (cr 4), С 4/20, найдено: К1!, К2!, К3!, К4!, С2, С5, С16, С17
* open2.capital: К 3/5 (cr 2), С 3/20, найдено: К1!, К2, К3!, С1, С2, С5
* open2.grace: К 3/5 (cr 3), С 3/20, найдено: К1!, К2!, К3!, С1, С2, С4
* open2.insurance: К 3/5 (cr 2), С 2/20, найдено: К1!, К3!, К4, С1, С2
* open2.qr: К 4/5 (cr 3), С 2/20, найдено: К1!, К2!, К3!, К4, С1, С2
Чистых 0: critical 0, major 0, документов с major > 1: 0. Противоречия корпуса и open2: 21/22.
