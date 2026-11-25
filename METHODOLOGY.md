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

## Module 2: Insider-trading screen

### Question
Did any insider trade shortly before material company news, in the direction that would
profit from it?

### Step 1: How big was the news? (market-model event study)
A stock moves partly because the whole market moves. To isolate the effect of the company's own
news, we first learn the stock's normal relationship with the market, then measure the gap.

1. **Day 0** is the event date, or the next trading day if the event fell on a non-trading day.
2. **Estimation window:** trading days −120 to −11. Fit by ordinary least squares:
   `R_stock = α + β × R_market + error`. β says how much the stock usually moves when the market
   moves 1%. σ is the standard deviation of the errors, which is the stock's normal day-to-day noise.
   Days with a return above 50% (likely data errors, flagged in Module 1) are left out.
   At least 60 usable days are required. Otherwise the event is reported as "insufficient history"
   rather than estimated.
3. **Abnormal return** on each day: `AR = R_stock − (α + β × R_market)`.
4. **CAR** (cumulative abnormal return) is the sum of the AR values over a window:
   - event window [0, +1]: the size of the news
   - pre-event window [−10, −1]: early price movement (a possible information leak)
5. **t-statistic:** `t = CAR / (σ × √days)`. The event is **material** if |t| ≥ 2, which means a move
   that large would happen by chance only about 5% of the time.
6. **Abnormal volume:** z-score of log(volume) against the estimation window. Zero-volume days
   (halts) are left out of the baseline.

**Benchmark:** `MKT` in the sample data. For real data, use a broad index ETF for the stock's
market, for example a TSX index ETF for Canadian stocks.

### Step 2: Which trades to look at
- Only **buys and sells**. Grants and option exercises are not discretionary trading decisions in
  the same way.
- Made within **30 calendar days before** the event, in the same company.
- **Duplicate filings** of the same trade (flagged in Module 1) are counted once. The earliest filing is
  kept and the other IDs are listed.
- If the reported price is outside the day's low–high range (a likely filing typo), the day's close
  is used and a note is added.

### Step 3: Flag
A trade is **flagged** if the event was material **and** the trade direction matched the news:
a buy before good news, or a sell before bad news. Trades that went against the news are listed
but not flagged.

### Step 4: Score (triage, not statistics)
| Factor | Points |
|---|---|
| Trading days before the news: ≤5 / ≤10 / more | 25 / 15 / 5 |
| Size of news: \|t\| ≥ 4 / ≥ 2 | 20 / 10 |
| Gain or loss avoided: ≥ $100k / ≥ $25k / > 0 | 20 / 10 / 5 |
| Trade not reported until after the news was public | 15 |
| Filed late (over 5 days) | 5 |
| No other trades in this stock by this insider in the previous 180 days | 10 |
| Unusual market volume before the news (z ≥ 2) | 10 |

The score is capped at 100. **High** ≥ 60, **Medium** ≥ 35, **Low** below that. The weights are
judgment calls that set the order of review. They are not estimated from data, and they are meant
to be challenged and tuned with the case team.

**Gain or loss avoided** = shares × (close on day +1 − trade price) for buys, and the reverse for
sells. It is an indication only. It ignores later price moves and costs, and it is not a
calculation of profit for legal purposes.

### Known limitations
- A flag is a **lead**. Legitimate explanations, such as a pre-arranged trading plan, prior
  public information or personal liquidity needs, can only be established by investigation.
- It only sees insiders who **reported** their trades. Tipping friends or family, or trading
  through other accounts, needs account-level data, which Module 3 (entity graph) is meant to link.
- Overlapping events for the same stock, or very thin trading, weaken the market model.
- Sample data is synthetic. The numbers show the method, not real cases.

### Reproduce
```bash
python -m enforcement_toolkit.validation.cli sample --out data/sample
python -m enforcement_toolkit.detection.cli --config config/detection.yaml
```

---

## Module 4: LLM document review
See `README.md` → design choices. A fuller write-up will follow once the evaluation is done.
