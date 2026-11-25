"""Match insider trades to material events and rank them for review.

A trade is FLAGGED when all three hold:
  1. it was made shortly BEFORE a material event for the same company
  2. the event was material (|t| above threshold in the event study)
  3. the trade direction matched the news (bought before good news / sold before bad news)

Flagged trades get a transparent points score. Every point comes with a
plain-language reason, so an analyst can see why the trade ranks where it does,
and challenge any rule. This is TRIAGE (what to look at first), not proof of
wrongdoing: insiders may have legitimate reasons, such as pre-arranged plans.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .event_study import EventResult, Panel

MARKET_TRADES = ["buy", "sell"]  # grants and option exercises are not trading decisions in the same way
DUP_KEY = ["insider_name", "ticker", "trade_date", "transaction_type", "shares", "price"]


@dataclass
class ScreeningConfig:
    lookback_days: int = 30  # calendar days before the event to look for trades
    max_filing_lag_days: int = 5
    history_days: int = 180  # "first trade in X days" lookback
    price_range_tolerance: float = 0.01
    high_score: int = 60
    medium_score: int = 35


def collapse_duplicate_reports(trades: pd.DataFrame) -> pd.DataFrame:
    """Module 1 warned about the same trade filed under two IDs (usually an amendment).
    Keep the earliest filing, and record the other IDs so nothing disappears silently."""
    t = trades.sort_values(["filing_date", "trade_id"])
    groups = t.groupby(DUP_KEY, sort=False)["trade_id"].agg(list)
    keep = t.drop_duplicates(DUP_KEY, keep="first").copy()
    dup_of = {ids[0]: ", ".join(ids[1:]) for ids in groups if len(ids) > 1}
    keep["duplicate_reports"] = keep["trade_id"].map(dup_of).fillna("")
    return keep


def _points(row: dict, ev: EventResult, cfg: ScreeningConfig) -> tuple[int, list[str]]:
    pts, why = 0, []

    def add(n: int, reason: str) -> None:
        nonlocal pts
        pts += n
        why.append(f"+{n} {reason}")

    d = row["trading_days_before"]
    if d <= 5:
        add(25, f"traded {d} trading day(s) before the news")
    elif d <= 10:
        add(15, f"traded {d} trading days before the news")
    else:
        add(5, f"traded {d} trading days before the news")

    if abs(ev.t_event) >= 4:
        add(20, f"very large price reaction to the news (t = {ev.t_event:.1f})")
    else:
        add(10, f"significant price reaction to the news (t = {ev.t_event:.1f})")

    g = row["gain_or_loss_avoided"]
    if g >= 100_000:
        add(20, f"gain / loss avoided about ${g:,.0f}")
    elif g >= 25_000:
        add(10, f"gain / loss avoided about ${g:,.0f}")
    elif g > 0:
        add(5, f"gain / loss avoided about ${g:,.0f}")

    if row["filed_after_news"]:
        add(15, "the trade was not reported until after the news was public")
    if row["filing_lag_days"] > cfg.max_filing_lag_days:
        add(5, f"filed {row['filing_lag_days']} days after the trade (deadline {cfg.max_filing_lag_days})")
    if row["prior_trades_in_ticker"] == 0:
        add(10, f"no other trades by this insider in this stock in the previous {cfg.history_days} days")
    if ev.volume_z_pre >= 2:
        add(10, f"unusually high market volume before the news (z = {ev.volume_z_pre:.1f})")
    return min(pts, 100), why


def screen_trades(
    trades: pd.DataFrame,
    events: list[EventResult],
    panel: Panel,
    cfg: ScreeningConfig,
    event_window_end: int = 1,
) -> pd.DataFrame:
    trades = collapse_duplicate_reports(trades)
    market = trades[trades["transaction_type"].isin(MARKET_TRADES)]
    rows = []
    for ev in events:
        if ev.status != "ok":
            continue
        t0 = panel.position(ev.event_date)
        exit_date = panel.dates[t0 + event_window_end]
        exit_price = panel.close.at[exit_date, ev.ticker]
        window_start = ev.event_date - pd.Timedelta(days=cfg.lookback_days)
        cands = market[
            (market["ticker"] == ev.ticker)
            & (market["trade_date"] < ev.event_date)
            & (market["trade_date"] >= window_start)
        ]
        for _, tr in cands.iterrows():
            side = 1 if tr["transaction_type"] == "buy" else -1
            day = tr["trade_date"]
            note = ""
            price = tr["price"]
            if day in panel.dates and tr["ticker"] in panel.low:
                lo, hi = panel.low.at[day, tr["ticker"]], panel.high.at[day, tr["ticker"]]
                tol = cfg.price_range_tolerance
                if not (lo * (1 - tol) <= price <= hi * (1 + tol)):
                    note = f"reported price {price} outside the day's range; used the close instead"
                    price = panel.close.at[day, tr["ticker"]]
            gain = side * tr["shares"] * (exit_price - price)

            history = trades[
                (trades["insider_name"] == tr["insider_name"])
                & (trades["ticker"] == tr["ticker"])
                & (trades["trade_date"] < day)
                & (trades["trade_date"] >= day - pd.Timedelta(days=cfg.history_days))
            ]
            row = {
                "trade_id": tr["trade_id"],
                "insider_name": tr["insider_name"],
                "insider_role": tr["insider_role"],
                "ticker": tr["ticker"],
                "transaction_type": tr["transaction_type"],
                "shares": int(tr["shares"]),
                "trade_date": day,
                "trade_price_used": round(float(price), 2),
                "filing_date": tr["filing_date"],
                "event_id": ev.event_id,
                "event_date": ev.event_date,
                "event_headline": ev.headline,
                "event_car_pct": round(100 * ev.car_event, 2),
                "event_t": round(ev.t_event, 2),
                "trading_days_before": t0 - panel.position(day),
                "calendar_days_before": (ev.event_date - day).days,
                "exit_date": exit_date,
                "exit_price": round(float(exit_price), 2),
                "gain_or_loss_avoided": round(float(gain), 0),
                "filing_lag_days": (tr["filing_date"] - day).days,
                "filed_after_news": bool(tr["filing_date"] >= ev.event_date),
                "prior_trades_in_ticker": len(history),
                "duplicate_reports": tr["duplicate_reports"],
                "data_note": note,
                "aligned_with_news": side == ev.direction,
                "event_material": ev.material,
            }
            row["flagged"] = row["aligned_with_news"] and ev.material
            if row["flagged"]:
                row["score"], reasons = _points(row, ev, cfg)
                row["reasons"] = "; ".join(reasons)
                row["priority"] = (
                    "High"
                    if row["score"] >= cfg.high_score
                    else "Medium"
                    if row["score"] >= cfg.medium_score
                    else "Low"
                )
            else:
                row["score"], row["priority"] = np.nan, ""
                row["reasons"] = (
                    "event not material" if not ev.material else "trade direction went against the news"
                )
            rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["flagged", "score"], ascending=[False, False]).reset_index(drop=True)
