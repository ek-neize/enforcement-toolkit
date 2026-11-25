"""Synthetic demo data with deliberately planted problems.

All companies and people are FICTIONAL. Use this to demo the validator and
to test it; swap in real public data (prices, SEDI / Form 4, press releases)
for the portfolio version.

Planted issues (inject_issues=True)
  prices:  exact duplicate row, conflicting duplicate, high < low, missing day,
           unparseable volume, a 10x price spike (data error), zero-volume + stale run
  trades:  filing before trade, late filing, price outside daily range,
           duplicate report under a new ID, unknown ticker, weekend trade date
  events:  conflicting duplicate event_id, event too early for the price history
Also planted for Module 2 (detection):
  * ACME takeover (2024-06-17): price run-up and 3x volume beforehand; CFO and a director buy before it
  * CNDR guidance cut (2024-10-24): a VP sells 7 trading days before the drop
  * MKT is a fictional market index; stock returns follow a market model (beta x market + noise)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

START, END = "2024-01-02", "2024-12-31"
MARKET_TICKER = "MKT"  # fictional broad-market index, used as the benchmark in Module 2
TICKERS = {"ACME": (20.0, 1.2), "BRL": (55.0, 0.9), "CNDR": (8.0, 1.4)}  # start price, beta
TAKEOVER_DATE = "2024-06-17"
GUIDANCE_CUT_DATE = "2024-10-24"


def _ohlcv(rng, dates, ticker, p0, rets, vol):
    close = p0 * np.cumprod(1 + rets)
    open_ = np.r_[p0, close[:-1]] * (1 + rng.normal(0, 0.004, len(dates)))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, len(dates))))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, len(dates))))
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "ticker": ticker,
            "open": open_.round(2),
            "high": high.round(2),
            "low": low.round(2),
            "close": close.round(2),
            "volume": vol.astype(int).astype(str),
        }
    )


def _prices(rng: np.random.Generator) -> pd.DataFrame:
    dates = pd.bdate_range(START, END)
    n = len(dates)
    mkt = rng.normal(0.0003, 0.009, n)
    frames = [_ohlcv(rng, dates, MARKET_TICKER, 1000.0, mkt, rng.lognormal(16, 0.2, n))]
    for ticker, (p0, beta) in TICKERS.items():
        rets = beta * mkt + rng.normal(0, 0.015, n)  # market model: stocks move with the market
        vol = rng.lognormal(12, 0.35, n)
        if ticker == "ACME":
            t0 = dates.get_loc(pd.Timestamp(TAKEOVER_DATE))
            rets[t0 - 6 : t0] += 0.008  # quiet run-up as news leaks
            vol[t0 - 10 : t0] *= 3  # unusual volume before the announcement
            rets[t0] = 0.38  # takeover premium
            vol[t0] *= 8
        if ticker == "CNDR":
            t0 = dates.get_loc(pd.Timestamp(GUIDANCE_CUT_DATE))
            rets[t0] = -0.18  # guidance cut
            vol[t0] *= 6
        frames.append(_ohlcv(rng, dates, ticker, p0, rets, vol))
    return pd.concat(frames, ignore_index=True)


def _plant_price_issues(df: pd.DataFrame) -> pd.DataFrame:
    def row(t, d):
        return df.index[(df["ticker"] == t) & (df["date"] == d)][0]

    df = df.drop(index=row("CNDR", "2024-03-15"))  # missing day
    i = row("CNDR", "2024-05-06")
    df.loc[i, ["high", "low"]] = df.loc[i, ["low", "high"]].to_numpy().copy()  # high < low
    df.loc[row("ACME", "2024-07-22"), "volume"] = "n/a"  # unparseable
    i = row("BRL", "2024-09-10")
    for c in ("open", "high", "low", "close"):
        df.loc[i, c] = round(df.loc[i, c] * 10, 2)  # decimal-shift data error
    for d in pd.bdate_range("2024-08-05", "2024-08-12").strftime("%Y-%m-%d"):  # halt-like run
        i = row("CNDR", d)
        df.loc[i, "volume"] = "0"
        df.loc[i, ["open", "high", "low", "close"]] = 7.10
    dup = df.loc[[row("ACME", "2024-02-01")]]  # exact duplicate
    conflict = df.loc[[row("BRL", "2024-04-02")]].assign(close=lambda x: x["close"] + 1.5)  # conflicting
    return pd.concat([df, dup, conflict], ignore_index=True)


def _trades(prices: pd.DataFrame, inject: bool) -> pd.DataFrame:
    px = prices.set_index(["ticker", "date"])["close"]

    def at(t, d):
        return float(px[(t, d)])

    rows = [
        # id, name, role, ticker, trade, filing, type, shares, price
        (
            "T001",
            "Dana Whitfield",
            "CFO",
            "ACME",
            "2024-06-04",
            "2024-06-06",
            "buy",
            20000,
            at("ACME", "2024-06-04"),
        ),
        (
            "T002",
            "Marc Olsen",
            "Director",
            "ACME",
            "2024-06-11",
            "2024-06-13",
            "buy",
            15000,
            at("ACME", "2024-06-11"),
        ),
        (
            "T003",
            "Priya Raman",
            "CEO",
            "BRL",
            "2024-03-12",
            "2024-03-14",
            "sell",
            5000,
            at("BRL", "2024-03-12"),
        ),
        ("T004", "Priya Raman", "CEO", "BRL", "2024-02-01", "2024-02-02", "grant", 10000, 0.0),
        (
            "T005",
            "Leo Tremblay",
            "VP Ops",
            "CNDR",
            "2024-10-15",
            "2024-10-17",
            "sell",
            8000,
            at("CNDR", "2024-10-15"),
        ),
        (
            "T006",
            "Ana Costa",
            "Director",
            "BRL",
            "2024-11-05",
            "2024-11-07",
            "buy",
            2500,
            at("BRL", "2024-11-05"),
        ),
    ]
    if inject:
        rows += [
            (
                "T007",
                "Leo Tremblay",
                "VP Ops",
                "CNDR",
                "2024-04-10",
                "2024-04-08",
                "buy",
                1000,
                at("CNDR", "2024-04-10"),
            ),
            (
                "T008",
                "Marc Olsen",
                "Director",
                "ACME",
                "2024-06-12",
                "2024-07-02",
                "buy",
                5000,
                at("ACME", "2024-06-12"),
            ),
            (
                "T009",
                "Ana Costa",
                "Director",
                "BRL",
                "2024-05-14",
                "2024-05-15",
                "buy",
                1200,
                at("BRL", "2024-05-14") * 10,
            ),
            (
                "T010",
                "Dana Whitfield",
                "CFO",
                "ACME",
                "2024-06-04",
                "2024-06-20",
                "buy",
                20000,
                at("ACME", "2024-06-04"),
            ),
            ("T011", "Sam Reid", "Director", "ZZZZ", "2024-05-01", "2024-05-02", "buy", 300, 4.10),
            ("T012", "Leo Tremblay", "VP Ops", "CNDR", "2024-09-14", "2024-09-16", "sell", 700, 7.90),
        ]
    cols = ["trade_id", "insider_name", "insider_role", "ticker", "trade_date",
            "filing_date", "transaction_type", "shares", "price"]  # fmt: skip
    df = pd.DataFrame(rows, columns=cols)
    df["price"] = df["price"].round(2)
    return df


def _events(inject: bool) -> pd.DataFrame:
    rows = [
        ("E001", "ACME", TAKEOVER_DATE, "m_and_a", "Acme Mining agrees to be acquired at a 40% premium"),
        ("E002", "BRL", "2024-08-08", "earnings", "Boreal Resources Q2 earnings beat"),
        ("E003", "CNDR", "2024-10-24", "guidance", "Condor Tech cuts full-year guidance"),
    ]
    if inject:
        rows += [
            ("E004", "CNDR", "2024-01-10", "guidance", "Condor Tech preliminary outlook"),
            ("E002", "BRL", "2024-08-09", "earnings", "Boreal Resources Q2 earnings (corrected date?)"),
        ]
    return pd.DataFrame(rows, columns=["event_id", "ticker", "event_date", "event_type", "headline"])


def make_sample_data(out_dir: str | Path, seed: int = 7, inject_issues: bool = True) -> dict[str, Path]:
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prices = _prices(rng)
    trades = _trades(prices, inject_issues)  # built from clean prices
    if inject_issues:
        prices = _plant_price_issues(prices)
    paths = {
        "prices": out / "prices.csv",
        "insider_trades": out / "insider_trades.csv",
        "events": out / "events.csv",
    }
    prices.to_csv(paths["prices"], index=False)
    trades.to_csv(paths["insider_trades"], index=False)
    _events(inject_issues).to_csv(paths["events"], index=False)
    return paths
