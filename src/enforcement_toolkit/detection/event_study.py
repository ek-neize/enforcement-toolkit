"""Market-model event study.

Question it answers: "How unusual was this stock's behaviour around this news,
compared with what the stock normally does given what the whole market did?"

Steps for each event:
  1. Estimation window (default: trading days -120 to -11 before the event).
     Fit the market model  R_stock = alpha + beta * R_market  with ordinary least squares.
     This learns the stock's NORMAL relationship with the market.
  2. Abnormal return (AR) on each day = actual return - return the model expected.
  3. CAR = cumulative abnormal return, summed over a window.
       event window  [0, +1]   -> how big was the news?        (materiality)
       pre-event     [-10, -1] -> did the price move early?    (possible leak)
  4. t-statistic = CAR / (sigma * sqrt(days)), sigma = std. dev. of the model's
     errors in the estimation window. |t| >= 2 is roughly "unlikely to be chance" (5%).
  5. Abnormal volume: z-score of log volume against the estimation window
     (zero-volume days are left out of that baseline).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class EventStudyConfig:
    market_ticker: str = "MKT"
    estimation_start: int = -120
    estimation_end: int = -11
    min_estimation_days: int = 60
    pre_event_start: int = -10
    pre_event_end: int = -1
    event_window_end: int = 1  # event-window CAR covers days [0, event_window_end]
    chart_start: int = -20
    chart_end: int = 5
    extreme_return: float = 0.50  # days above this are left out of estimation (likely data errors)
    material_t: float = 2.0


@dataclass
class EventResult:
    event_id: str
    ticker: str
    event_date: pd.Timestamp
    event_type: str
    headline: str | None
    status: str = "ok"
    t0_date: pd.Timestamp | None = None
    n_estimation_days: int = 0
    alpha: float = np.nan
    beta: float = np.nan
    sigma: float = np.nan
    car_event: float = np.nan
    t_event: float = np.nan
    car_pre: float = np.nan
    t_pre: float = np.nan
    volume_z_pre: float = np.nan
    material: bool = False
    path: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)

    @property
    def direction(self) -> int:
        """+1 good news (price jumped), -1 bad news, 0 unknown."""
        return 0 if np.isnan(self.car_event) else int(np.sign(self.car_event))


@dataclass
class Panel:
    """Prices reshaped to one column per ticker, one row per trading day."""

    close: pd.DataFrame
    low: pd.DataFrame
    high: pd.DataFrame
    ret: pd.DataFrame
    log_volume: pd.DataFrame

    @classmethod
    def from_prices(cls, prices: pd.DataFrame) -> Panel:
        def wide(col):
            return prices.pivot(index="date", columns="ticker", values=col).sort_index()

        close = wide("close")
        return cls(
            close=close,
            low=wide("low"),
            high=wide("high"),
            ret=close.pct_change(fill_method=None),
            log_volume=np.log1p(wide("volume")),
        )

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.close.index

    def position(self, day: pd.Timestamp) -> int:
        """Index of the first trading day on or after `day`."""
        return int(self.dates.searchsorted(day))


def _window(series: pd.Series, start: int, end: int) -> pd.Series:
    return series.iloc[max(start, 0) : max(end + 1, 0)]


def study_event(event: pd.Series, panel: Panel, cfg: EventStudyConfig) -> EventResult:
    res = EventResult(
        event_id=event["event_id"],
        ticker=event["ticker"],
        event_date=event["event_date"],
        event_type=event["event_type"],
        headline=event.get("headline"),
    )
    tk, mk = res.ticker, cfg.market_ticker
    if tk not in panel.ret or mk not in panel.ret:
        res.status = f"no price data for {tk if tk not in panel.ret else mk}"
        return res
    t0 = panel.position(res.event_date)
    if t0 + cfg.event_window_end >= len(panel.dates):
        res.status = "event too close to the end of the price data"
        return res
    res.t0_date = panel.dates[t0]

    r_i, r_m = panel.ret[tk], panel.ret[mk]
    est_i = _window(r_i, t0 + cfg.estimation_start, t0 + cfg.estimation_end)
    est_m = r_m.loc[est_i.index]
    ok = (
        est_i.notna()
        & est_m.notna()
        & (est_i.abs() <= cfg.extreme_return)
        & (est_m.abs() <= cfg.extreme_return)
    )
    est_i, est_m = est_i[ok], est_m[ok]
    res.n_estimation_days = len(est_i)
    if len(est_i) < cfg.min_estimation_days:
        res.status = f"only {len(est_i)} estimation days (need {cfg.min_estimation_days})"
        return res

    # Ordinary least squares, written out so every number can be checked by hand.
    beta = float(np.cov(est_i, est_m, ddof=1)[0, 1] / np.var(est_m, ddof=1))
    alpha = float(est_i.mean() - beta * est_m.mean())
    sigma = float(np.std(est_i - (alpha + beta * est_m), ddof=2))
    res.alpha, res.beta, res.sigma = alpha, beta, sigma

    ar = r_i - (alpha + beta * r_m)

    def car(start: int, end: int) -> tuple[float, float]:
        w = _window(ar, t0 + start, t0 + end).dropna()
        total = float(w.sum())
        return total, total / (sigma * np.sqrt(len(w))) if len(w) else np.nan

    res.car_event, res.t_event = car(0, cfg.event_window_end)
    res.car_pre, res.t_pre = car(cfg.pre_event_start, cfg.pre_event_end)
    res.material = bool(abs(res.t_event) >= cfg.material_t)

    lv = panel.log_volume[tk]
    est_v = lv.loc[est_i.index]
    est_v = est_v[est_v > 0]  # zero-volume days (halts, frozen feeds) would distort "normal" volume
    vz = (lv - est_v.mean()) / est_v.std(ddof=1)
    res.volume_z_pre = float(_window(vz, t0 + cfg.pre_event_start, t0 + cfg.pre_event_end).mean())

    lo, hi = max(t0 + cfg.chart_start, 0), min(t0 + cfg.chart_end, len(panel.dates) - 1)
    idx = panel.dates[lo : hi + 1]
    res.path = pd.DataFrame(
        {
            "rel_day": np.arange(lo - t0, hi - t0 + 1),
            "date": idx,
            "ar": ar.loc[idx].to_numpy(),
            "car": ar.loc[idx].fillna(0).cumsum().to_numpy(),
            "volume_z": vz.loc[idx].to_numpy(),
        }
    )
    return res


def run_event_study(events: pd.DataFrame, panel: Panel, cfg: EventStudyConfig) -> list[EventResult]:
    return [study_event(e, panel, cfg) for _, e in events.sort_values("event_date").iterrows()]


def results_table(results: list[EventResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append(
            {
                "event_id": r.event_id,
                "ticker": r.ticker,
                "event_date": r.event_date,
                "event_type": r.event_type,
                "status": r.status,
                "beta": round(r.beta, 2),
                "car_event_pct": round(100 * r.car_event, 2),
                "t_event": round(r.t_event, 2),
                "material": r.material,
                "car_pre_event_pct": round(100 * r.car_pre, 2),
                "t_pre_event": round(r.t_pre, 2),
                "volume_z_pre_event": round(r.volume_z_pre, 2),
                "estimation_days": r.n_estimation_days,
            }
        )
    return pd.DataFrame(rows)
