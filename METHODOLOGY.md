# Methodology

This document explains how each module works: what it assumes, where it can fail, and how to
reproduce its results. It is written so the analysis can be explained to a case team and
defended if challenged.

---

## Module 1: Data intake and validation

### Purpose
Make sure source data is complete and consistent **before** any analysis uses it, and keep a
record proving the data was not altered afterwards.

### Inputs
| File | Columns |
|---|---|
| `prices.csv` | date, ticker, open, high, low, close, volume |
| `insider_trades.csv` | trade_id, insider_name, insider_role, ticker, trade_date, filing_date, transaction_type, shares, price |
| `events.csv` | event_id, ticker, event_date, event_type, headline |

Dates must be `YYYY-MM-DD`. Thousands separators in numbers are accepted.

### Chain of custody
1. Each input file's SHA-256 hash, size, source description and time are appended to
   `data/custody_log.jsonl`. The log is append-only: entries are never edited or deleted.
2. If a file changes between runs, a new entry records both the new and the previous hash, and the
   report shows a warning.
3. `validation.cli verify-custody` re-hashes every registered file at any later date. A mismatch
   means the file is no longer the one the analysis was based on.

### What is changed automatically (and nothing else)
- Leading and trailing spaces are removed. Tickers are upper-cased. Transaction and event types are lower-cased.
- Exact duplicate rows are dropped, keeping the first. This is always reported.

All other problems are **reported, not fixed**. Correcting data means deciding which value is right,
and that decision belongs to the analyst and the case team, with the provider where needed.

### Errors: rows are quarantined
A quarantined row is left out of all analysis and written to `quarantine_<dataset>.csv` with its
source line number.

| Check | Rule |
|---|---|
| file_structure | Expected columns present, no unexpected columns. If this fails, the whole dataset is unusable. |
| unparseable_date / number | Value present but not a valid date or number |
| not_nullable | Required value blank |
| conflicting_duplicates | Same key (date+ticker, trade_id, event_id) with different values. **All** copies are quarantined. |
| high_is_daily_max / low_is_daily_min | High ≥ open, low, close; low ≤ open, high, close |
| prices > 0, shares > 0, price ≥ 0, whole-number volume | Basic validity |
| filing_not_before_trade | Filing date ≥ trade date |
| allowed categories | transaction_type and event_type come from a fixed list |

### Warnings: analysis continues, but an analyst must review
| Check | Default threshold | Why it matters |
|---|---|---|
| missing_trading_days | n/a | A day other tickers traded but this one has no row. Could be a data gap or a trading halt. |
| extreme_daily_returns | > 50% | Could be a split, a data error, or a real event. It would distort event studies. |
| zero_volume_runs | ≥ 3 days | Halt, delisting or a frozen feed |
| stale_prices | ≥ 5 unchanged closes | Feed carrying an old price forward |
| late_filings | > 5 calendar days | Data is fine, but late insider reporting is itself of interest |
| price_outside_daily_range | ±1% of low–high | A typo in the filing or an off-market trade. Grants and exercises are excluded. |
| possible_duplicate_reports | n/a | Same trade under two IDs, often an amendment. Counting both would double the position. |
| no_price_coverage | n/a | Trade can't be matched to prices: weekend or holiday date, or unknown ticker |
| insufficient_price_window | 30 days before, 5 after | Not enough history around an event to analyse it |

Thresholds live in `config/validation.yaml`. Every report records the values used.

### Known limitations
- The trading calendar is inferred from the dates other tickers traded. If there is only one ticker,
  weekdays are used, so holidays will appear as false gaps. Swap in an exchange calendar
  (e.g. `pandas_market_calendars`) for production use.
- The filing deadline differs by jurisdiction: Canada (SEDI) allows 5 calendar days, and the US (Form 4)
  allows 2 business days. Set it to match the data.
- Splits and dividends are not adjusted. Use adjusted prices or a corporate-actions file.

### Reproduce
```bash
python -m enforcement_toolkit.validation.cli sample --out data/sample   # synthetic data, seed 7
python -m enforcement_toolkit.validation.cli validate --config config/validation.yaml
python -m enforcement_toolkit.validation.cli verify-custody --log data/custody_log.jsonl
```

---

## Module 4: LLM document review
See `README.md` → design choices. A fuller write-up will follow once the evaluation is done.
