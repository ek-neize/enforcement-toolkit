"""Completeness and integrity checks that run AFTER the schema checks, on valid rows.

These produce WARNINGS: the data may still be usable, but an analyst must look
before relying on it. Each check says what it found and why it matters.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .issues import Issue, examples


@dataclass
class Thresholds:
    extreme_return: float = 0.50  # |daily close-to-close return| above this is flagged
    zero_volume_run: int = 3  # this many consecutive zero-volume days
    stale_price_run: int = 5  # this many consecutive unchanged closes
    max_filing_lag_days: int = 5  # calendar days (Canada/SEDI: 5; US Form 4: 2 business days)
    price_range_tolerance: float = 0.01  # allow 1% outside the day's low-high range
    event_lookback_days: int = 30  # price history needed before an event
    event_lookahead_days: int = 5  # and after it


def _runs(df: pd.DataFrame, cond: pd.Series, min_len: int) -> pd.DataFrame:
    """Runs of consecutive True values per ticker, at least min_len long."""
    rows = []
    d = df.assign(_c=cond.to_numpy())
    for ticker, g in d.groupby("ticker", sort=True):
        block = (g["_c"] != g["_c"].shift()).cumsum()
        for _, b in g[g["_c"]].groupby(block[g["_c"]]):
            if len(b) >= min_len:
                rows.append(
                    {"ticker": ticker, "start": b["date"].min(), "end": b["date"].max(), "days": len(b)}
                )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- prices
def missing_trading_days(prices: pd.DataFrame, quarantined: pd.DataFrame | None = None) -> list[Issue]:
    """Uses the union of dates seen across all tickers as the market calendar:
    if other stocks traded that day, this one should have a row too."""
    if prices.empty:
        return []
    if prices["ticker"].nunique() >= 2:
        calendar = pd.DatetimeIndex(sorted(prices["date"].unique()))
        basis = "dates on which other tickers in the file traded"
    else:
        calendar = pd.bdate_range(prices["date"].min(), prices["date"].max())
        basis = "weekdays (holidays will appear as false alarms)"
    rows = []
    for ticker, g in prices.groupby("ticker", sort=True):
        expected = calendar[(calendar >= g["date"].min()) & (calendar <= g["date"].max())]
        for day in expected.difference(pd.DatetimeIndex(g["date"])):
            rows.append({"ticker": ticker, "missing_date": day})
    if not rows:
        return []
    found = pd.DataFrame(rows)
    q = set()
    if quarantined is not None and not quarantined.empty:
        q = set(zip(quarantined["ticker"], quarantined["date"], strict=True))
    found["reason"] = [
        "row quarantined (see errors)" if (t, d) in q else "no row in file"
        for t, d in zip(found["ticker"], found["missing_date"], strict=True)
    ]
    found = found.sort_values(["reason", "ticker", "missing_date"])
    return [
        Issue(
            "prices",
            "missing_trading_days",
            "warning",
            len(found),
            f"Gaps in the price history, measured against {basis}. "
            "Could be a data gap or a trading halt; a halt is itself worth knowing about.",
            examples(found, 10),
        )
    ]


def extreme_returns(prices: pd.DataFrame, t: Thresholds) -> list[Issue]:
    if prices.empty:
        return []
    p = prices.sort_values(["ticker", "date"])
    prev = p.groupby("ticker")["close"].shift()
    ret = p["close"] / prev - 1
    hit = ret.abs() > t.extreme_return
    if not hit.any():
        return []
    found = p.loc[hit, ["ticker", "date", "close"]].assign(prev_close=prev[hit], ret=ret[hit].round(4))
    return [
        Issue(
            "prices",
            "extreme_daily_returns",
            "warning",
            int(hit.sum()),
            f"Close-to-close moves larger than {t.extreme_return:.0%}. Could be a stock split, "
            "a data error, or a genuine price-moving event. Confirm before running event studies.",
            examples(found, 10, with_line=True),
        )
    ]


def zero_volume_runs(prices: pd.DataFrame, t: Thresholds) -> list[Issue]:
    if prices.empty:
        return []
    p = prices.sort_values(["ticker", "date"])
    found = _runs(p, p["volume"] == 0, t.zero_volume_run)
    if found.empty:
        return []
    return [
        Issue(
            "prices",
            "zero_volume_runs",
            "warning",
            len(found),
            f"{t.zero_volume_run}+ consecutive days with zero volume: possible halt, "
            "delisting, or a feed that stopped updating.",
            examples(found),
        )
    ]


def stale_prices(prices: pd.DataFrame, t: Thresholds) -> list[Issue]:
    if prices.empty:
        return []
    p = prices.sort_values(["ticker", "date"])
    unchanged = p.groupby("ticker")["close"].diff() == 0
    found = _runs(p, unchanged, t.stale_price_run)
    if found.empty:
        return []
    return [
        Issue(
            "prices",
            "stale_prices",
            "warning",
            len(found),
            f"Close unchanged for {t.stale_price_run}+ consecutive days: the feed may be carrying "
            "forward an old price.",
            examples(found),
        )
    ]


# ---------------------------------------------------------------- insider trades
def late_filings(trades: pd.DataFrame, t: Thresholds) -> list[Issue]:
    if trades.empty:
        return []
    lag = (trades["filing_date"] - trades["trade_date"]).dt.days
    hit = lag > t.max_filing_lag_days
    if not hit.any():
        return []
    cols = ["trade_id", "insider_name", "ticker", "trade_date", "filing_date"]
    return [
        Issue(
            "insider_trades",
            "late_filings",
            "warning",
            int(hit.sum()),
            f"Filed more than {t.max_filing_lag_days} calendar days after the trade. "
            "Not a data error, but late reporting is itself of enforcement interest.",
            examples(trades.loc[hit, cols].assign(lag_days=lag[hit]), 10, with_line=True),
        )
    ]


def trade_price_vs_market(trades: pd.DataFrame, prices: pd.DataFrame, t: Thresholds) -> list[Issue]:
    """Reported trade price outside that day's low-high range, and trades with no price data."""
    if trades.empty:
        return []
    issues = []
    market = prices[["ticker", "date", "low", "high"]].rename(columns={"date": "trade_date"})
    m = trades.reset_index().merge(market, on=["ticker", "trade_date"], how="left").set_index("index")

    no_cover = m["low"].isna()
    if no_cover.any():
        known = set(prices["ticker"])
        reason = m.loc[no_cover, "ticker"].map(
            lambda x: "ticker not in price file" if x not in known else "no price row on trade date"
        )
        cols = ["trade_id", "ticker", "trade_date"]
        issues.append(
            Issue(
                "insider_trades",
                "no_price_coverage",
                "warning",
                int(no_cover.sum()),
                "Trades that cannot be matched to market prices, so they cannot be analysed. "
                "Check for a weekend/holiday trade date or a ticker mismatch.",
                examples(m.loc[no_cover, cols].assign(reason=reason), with_line=True),
            )
        )

    market_trade = ~m["transaction_type"].isin(["grant", "exercise"])  # off-market prices are normal there
    tol = t.price_range_tolerance
    outside = (
        ~no_cover
        & market_trade
        & ((m["price"] < m["low"] * (1 - tol)) | (m["price"] > m["high"] * (1 + tol)))
    )
    if outside.any():
        cols = ["trade_id", "ticker", "trade_date", "transaction_type", "price", "low", "high"]
        issues.append(
            Issue(
                "insider_trades",
                "price_outside_daily_range",
                "warning",
                int(outside.sum()),
                "Reported trade price is outside the stock's low-high range that day. "
                "Usually a typo in the filing (e.g. wrong decimal place) or an off-market trade.",
                examples(m.loc[outside, cols], with_line=True),
            )
        )
    return issues


def duplicate_trade_reports(trades: pd.DataFrame) -> list[Issue]:
    if trades.empty:
        return []
    key = ["insider_name", "ticker", "trade_date", "transaction_type", "shares", "price"]
    dup = trades.duplicated(subset=key, keep=False)
    if not dup.any():
        return []
    return [
        Issue(
            "insider_trades",
            "possible_duplicate_reports",
            "warning",
            int(dup.sum()),
            "Same insider, ticker, date, side, size and price under different trade IDs. "
            "Often an amended filing; counting both would double the position.",
            examples(trades[dup].sort_values(key), with_line=True),
        )
    ]


# ---------------------------------------------------------------- events
def event_window_coverage(events: pd.DataFrame, prices: pd.DataFrame, t: Thresholds) -> list[Issue]:
    if events.empty:
        return []
    span = prices.groupby("ticker")["date"].agg(["min", "max"])
    e = events.join(span, on="ticker")
    need_start = e["event_date"] - pd.Timedelta(days=t.event_lookback_days)
    need_end = e["event_date"] + pd.Timedelta(days=t.event_lookahead_days)
    short = e["min"].isna() | (e["min"] > need_start) | (e["max"] < need_end)
    if not short.any():
        return []
    found = e.loc[short, ["event_id", "ticker", "event_date"]].assign(
        prices_from=e.loc[short, "min"], prices_to=e.loc[short, "max"]
    )
    return [
        Issue(
            "events",
            "insufficient_price_window",
            "warning",
            int(short.sum()),
            f"Price data does not cover {t.event_lookback_days} days before to "
            f"{t.event_lookahead_days} days after the event, so it cannot be fully analysed.",
            examples(found, with_line=True),
        )
    ]


def run_all(
    frames: dict[str, pd.DataFrame], t: Thresholds, quarantined: dict[str, pd.DataFrame] | None = None
) -> list[Issue]:
    p, tr, ev = frames.get("prices"), frames.get("insider_trades"), frames.get("events")
    issues: list[Issue] = []
    if p is not None:
        issues += (
            missing_trading_days(p, (quarantined or {}).get("prices"))
            + extreme_returns(p, t)
            + zero_volume_runs(p, t)
            + stale_prices(p, t)
        )
    if tr is not None:
        issues += late_filings(tr, t) + duplicate_trade_reports(tr)
        if p is not None:
            issues += trade_price_vs_market(tr, p, t)
    if ev is not None and p is not None:
        issues += event_window_coverage(ev, p, t)
    return issues
