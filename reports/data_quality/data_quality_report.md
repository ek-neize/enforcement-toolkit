# Data Quality Report

**Status: FAIL** · 7 error type(s), 10 warning type(s) · generated 2026-11-25T00:46:52+00:00

**Errors** mean rows were quarantined and left out of the analysis until resolved with the data provider or case team. **Warnings** do not block analysis but need an analyst's review.

## Source files (chain of custody)

| file | sha256 | bytes | registered | changed since last run |
|---|---|---|---|---|
| data/sample/prices.csv | `dc8a8d244886873e…` | 48424 | 2026-11-25T00:46:52+00:00 | no |
| data/sample/insider_trades.csv | `3fa3a9be49e21593…` | 880 | 2026-11-25T00:46:52+00:00 | no |
| data/sample/events.csv | `7d01d229c9318854…` | 394 | 2026-11-25T00:46:52+00:00 | no |
| data/sample/account_trades.csv | `18b836978a2f3439…` | 439 | 2026-11-25T00:46:52+00:00 | no |
| data/sample/relationships.csv | `7d4ef1e9c064fe5d…` | 577 | 2026-11-25T00:46:52+00:00 | no |

## Datasets

| dataset | raw rows | valid | quarantined | date range | tickers |
|---|---|---|---|---|---|
| prices | 1045 | 1040 | 4 | 2024-01-02 → 2024-12-31 | 4 |
| insider_trades | 12 | 11 | 1 | 2024-02-01 → 2024-11-05 | 4 |
| events | 5 | 3 | 2 | 2024-01-10 → 2024-10-24 | 2 |
| account_trades | 6 | 6 | 0 | 2024-01-15 → 2024-10-21 | 2 |
| relationships | 7 | 6 | 1 |  |  |

## Issues found

| severity | dataset | check | rows |
|---|---|---|---|
| ERROR | events | conflicting_duplicates | 2 |
| ERROR | insider_trades | filing_not_before_trade | 1 |
| ERROR | prices | conflicting_duplicates | 2 |
| ERROR | prices | high_is_daily_max | 2 |
| ERROR | prices | low_is_daily_min | 1 |
| ERROR | prices | unparseable_number | 1 |
| ERROR | relationships | not_nullable | 1 |
| WARNING | events | insufficient_price_window | 1 |
| WARNING | insider_trades | late_filings | 2 |
| WARNING | insider_trades | no_price_coverage | 2 |
| WARNING | insider_trades | possible_duplicate_reports | 2 |
| WARNING | insider_trades | price_outside_daily_range | 1 |
| WARNING | prices | exact_duplicate_rows | 1 |
| WARNING | prices | extreme_daily_returns | 2 |
| WARNING | prices | missing_trading_days | 4 |
| WARNING | prices | stale_prices | 1 |
| WARNING | prices | zero_volume_runs | 1 |

## Details

### [ERROR] events · conflicting_duplicates (2)

Several rows share the same key ['event_id'] but have different values. All of them are quarantined until the correct one is confirmed.

Examples:

| csv_line | event_id | ticker | event_date | event_type | headline |
|---|---|---|---|---|---|
| 3 | E002 | BRL | 2024-08-08 | earnings | Boreal Resources Q2 earnings beat |
| 6 | E002 | BRL | 2024-08-09 | earnings | Boreal Resources Q2 earnings (corrected date?) |

### [ERROR] insider_trades · filing_not_before_trade (1)

Row failed the rule `filing_not_before_trade`. The filing date is earlier than the trade date: one of the two dates is wrong. Rows quarantined.

Examples:

| csv_line | trade_id | insider_name | insider_role | ticker | trade_date | filing_date | transaction_type | shares | price |
|---|---|---|---|---|---|---|---|---|---|
| 8 | T007 | Leo Tremblay | VP Ops | CNDR | 2024-04-10 | 2024-04-08 | buy | 1000.0 | 6.73 |

### [ERROR] prices · conflicting_duplicates (2)

Several rows share the same key ['date', 'ticker'] but have different values. All of them are quarantined until the correct one is confirmed.

Examples:

| csv_line | date | ticker | open | high | low | close | volume |
|---|---|---|---|---|---|---|---|
| 589 | 2024-04-02 | BRL | 59.33 | 62.53 | 59.33 | 62.23 | 271635.0 |
| 1046 | 2024-04-02 | BRL | 59.33 | 62.53 | 59.33 | 63.73 | 271635.0 |

### [ERROR] prices · high_is_daily_max (2)

Row failed the rule `high_is_daily_max`. The day's high is below its open, low or close, which is impossible. Usually columns swapped or a bad tick. Rows quarantined.

Examples:

| csv_line | date | ticker | open | high | low | close | volume |
|---|---|---|---|---|---|---|---|
| 873 | 2024-05-06 | CNDR | 7.15 | 7.13 | 7.27 | 7.23 | 129284.0 |
| 1046 | 2024-04-02 | BRL | 59.33 | 62.53 | 59.33 | 63.73 | 271635.0 |

### [ERROR] prices · low_is_daily_min (1)

Row failed the rule `low_is_daily_min`. The day's low is above its open, high or close, which is impossible. Rows quarantined.

Examples:

| csv_line | date | ticker | open | high | low | close | volume |
|---|---|---|---|---|---|---|---|
| 873 | 2024-05-06 | CNDR | 7.15 | 7.13 | 7.27 | 7.23 | 129284.0 |

### [ERROR] prices · unparseable_number (1)

`volume` has values that are not valid numbers.

Examples:

| csv_line | date | ticker | open | high | low | close | volume |
|---|---|---|---|---|---|---|---|
| 407 | 2024-07-22 | ACME | 20.73 | 20.98 | 20.72 | 20.97 | n/a |

### [ERROR] relationships · not_nullable (1)

`evidence_source` failed the rule `not_nullable`. Required value is blank. Rows quarantined.

Examples:

| csv_line | source | source_type | target | target_type | relation | evidence_source |
|---|---|---|---|---|---|---|
| 8 | Sam Reid | person | Marc Olsen | person | friend_of |  |

### [WARNING] events · insufficient_price_window (1)

Price data does not cover 30 days before to 5 days after the event, so it cannot be fully analysed.

Examples:

| csv_line | event_id | ticker | event_date | prices_from | prices_to |
|---|---|---|---|---|---|
| 5 | E004 | CNDR | 2024-01-10 | 2024-01-02 | 2024-12-31 |

### [WARNING] insider_trades · late_filings (2)

Filed more than 5 calendar days after the trade. Not a data error, but late reporting is itself of enforcement interest.

Examples:

| csv_line | trade_id | insider_name | ticker | trade_date | filing_date | lag_days |
|---|---|---|---|---|---|---|
| 9 | T008 | Marc Olsen | ACME | 2024-06-12 | 2024-07-02 | 20 |
| 11 | T010 | Dana Whitfield | ACME | 2024-06-04 | 2024-06-20 | 16 |

### [WARNING] insider_trades · no_price_coverage (2)

Trades that cannot be matched to market prices, so they cannot be analysed. Check for a weekend/holiday trade date or a ticker mismatch.

Examples:

| csv_line | trade_id | ticker | trade_date | reason |
|---|---|---|---|---|
| 12 | T011 | ZZZZ | 2024-05-01 | ticker not in price file |
| 13 | T012 | CNDR | 2024-09-14 | no price row on trade date |

### [WARNING] insider_trades · possible_duplicate_reports (2)

Same insider, ticker, date, side, size and price under different trade IDs. Often an amended filing; counting both would double the position.

Examples:

| csv_line | trade_id | insider_name | insider_role | ticker | trade_date | filing_date | transaction_type | shares | price |
|---|---|---|---|---|---|---|---|---|---|
| 2 | T001 | Dana Whitfield | CFO | ACME | 2024-06-04 | 2024-06-06 | buy | 20000.0 | 16.04 |
| 11 | T010 | Dana Whitfield | CFO | ACME | 2024-06-04 | 2024-06-20 | buy | 20000.0 | 16.04 |

### [WARNING] insider_trades · price_outside_daily_range (1)

Reported trade price is outside the stock's low-high range that day. Usually a typo in the filing (e.g. wrong decimal place) or an off-market trade.

Examples:

| csv_line | trade_id | ticker | trade_date | transaction_type | price | low | high |
|---|---|---|---|---|---|---|---|
| 10 | T009 | BRL | 2024-05-14 | buy | 591.2 | 57.55 | 59.45 |

### [WARNING] prices · exact_duplicate_rows (1)

Identical rows appear more than once. Extra copies were dropped (first kept).

Examples:

| csv_line | date | ticker | open | high | low | close | volume |
|---|---|---|---|---|---|---|---|
| 1045 | 2024-02-01 | ACME | 18.41 | 18.53 | 17.88 | 18.03 | 350036.0 |

### [WARNING] prices · extreme_daily_returns (2)

Close-to-close moves larger than 50%. Could be a stock split, a data error, or a genuine price-moving event. Confirm before running event studies.

Examples:

| csv_line | ticker | date | close | prev_close | ret |
|---|---|---|---|---|---|
| 704 | BRL | 2024-09-10 | 469.4 | 45.88 | 9.231 |
| 705 | BRL | 2024-09-11 | 45.88 | 469.4 | -0.9023 |

### [WARNING] prices · missing_trading_days (4)

Gaps in the price history, measured against dates on which other tickers in the file traded. Could be a data gap or a trading halt; a halt is itself worth knowing about.

Examples:

| ticker | missing_date | reason |
|---|---|---|
| CNDR | 2024-03-15 | no row in file |
| ACME | 2024-07-22 | row quarantined (see errors) |
| BRL | 2024-04-02 | row quarantined (see errors) |
| CNDR | 2024-05-06 | row quarantined (see errors) |

### [WARNING] prices · stale_prices (1)

Close unchanged for 5+ consecutive days: the feed may be carrying forward an old price.

Examples:

| ticker | start | end | days |
|---|---|---|---|
| CNDR | 2024-08-06 | 2024-08-12 | 5 |

### [WARNING] prices · zero_volume_runs (1)

3+ consecutive days with zero volume: possible halt, delisting, or a feed that stopped updating.

Examples:

| ticker | start | end | days |
|---|---|---|---|
| CNDR | 2024-08-05 | 2024-08-12 | 6 |
