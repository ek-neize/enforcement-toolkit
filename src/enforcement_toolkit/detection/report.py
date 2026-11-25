"""Run the detection and write a plain-language report for a case team.

Outputs (in output_dir):
  detection_report.md   summary, ranked trades, a short narrative per flagged trade, charts
  event_study.csv       one row per event
  screened_trades.csv   every trade matched to an event, flagged or not, with reasons
  charts/<event>.png
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..common import utc_now
from .charts import event_chart
from .event_study import EventResult, EventStudyConfig, Panel, results_table, run_event_study
from .screening import ScreeningConfig, screen_trades


@dataclass
class DetectionResult:
    events: list[EventResult]
    event_table: pd.DataFrame
    screened: pd.DataFrame
    es_cfg: EventStudyConfig
    sc_cfg: ScreeningConfig
    created_at: str

    @property
    def flagged(self) -> pd.DataFrame:
        if self.screened.empty:
            return self.screened
        return self.screened[self.screened["flagged"]]


def run_detection(
    frames: dict[str, pd.DataFrame],
    es_cfg: EventStudyConfig | None = None,
    sc_cfg: ScreeningConfig | None = None,
) -> DetectionResult:
    """`frames` = validated data from Module 1: run_validation(...).frames()."""
    es_cfg, sc_cfg = es_cfg or EventStudyConfig(), sc_cfg or ScreeningConfig()
    panel = Panel.from_prices(frames["prices"])
    events = run_event_study(frames["events"], panel, es_cfg)
    screened = screen_trades(frames["insider_trades"], events, panel, sc_cfg, es_cfg.event_window_end)
    return DetectionResult(events, results_table(events), screened, es_cfg, sc_cfg, utc_now())


# ---------------------------------------------------------------- rendering
def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_none_\n"
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime("%Y-%m-%d")
    lines = ["| " + " | ".join(d.columns) + " |", "|" + "---|" * len(d.columns)]
    lines += [
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in d.itertuples(index=False)
    ]
    return "\n".join(lines) + "\n"


def _narrative(r: pd.Series) -> str:
    verb = "bought" if r["transaction_type"] == "buy" else "sold"
    outcome = "gain" if r["transaction_type"] == "buy" else "loss avoided"
    move = "rose" if r["event_car_pct"] > 0 else "fell"
    text = (
        f"**{r['insider_name']}** ({r['insider_role']}) {verb} {r['shares']:,} {r['ticker']} shares on "
        f"{r['trade_date']:%Y-%m-%d} at about ${r['trade_price_used']:,.2f}, "
        f'{r["trading_days_before"]} trading days before *"{r["event_headline"]}"* '
        f"({r['event_date']:%Y-%m-%d}). Adjusted for the market, the stock {move} "
        f"{abs(r['event_car_pct']):.1f}% on the news. Valued at the close on {r['exit_date']:%Y-%m-%d} "
        f"(${r['exit_price']:,.2f}), the estimated {outcome} is **${r['gain_or_loss_avoided']:,.0f}**. "
        f"The trade was filed on {r['filing_date']:%Y-%m-%d}"
        + (", after the news was public." if r["filed_after_news"] else ", before the news.")
    )
    if r["duplicate_reports"]:
        text += f" The same trade was also filed as {r['duplicate_reports']} (counted once)."
    if r["data_note"]:
        text += f" Data note: {r['data_note']}."
    reasons = "".join(f"\n  - {x}" for x in r["reasons"].split("; "))
    return f"{text}\n\n- **Score {int(r['score'])} ({r['priority']})**, made up of:{reasons}\n"


def render_markdown(res: DetectionResult, chart_paths: dict[str, str]) -> str:
    f = res.flagged
    n_high = int((f["priority"] == "High").sum()) if not f.empty else 0
    ev = res.event_table
    md = [
        "# Insider Trading Screen\n",
        f"Generated {res.created_at} · {len(ev)} events studied, "
        f"{int(ev['material'].sum()) if not ev.empty else 0} material · "
        f"{len(res.screened)} insider trades matched to events · **{len(f)} flagged ({n_high} high priority)**\n",
        "> **How to read this.** A trade is flagged when an insider traded shortly before material news "
        "**and** in the direction that would profit from it. Flags are leads for review, not findings of "
        "wrongdoing: insiders may have legitimate reasons (e.g. a pre-arranged trading plan), which only "
        "an investigation can establish.\n",
        "## Events\n",
        "How strongly each stock reacted to its news, after removing what the overall market did. "
        f"`material` means |t| ≥ {res.es_cfg.material_t}.\n",
        _md_table(ev),
        "## Flagged trades (ranked)\n",
    ]
    if f.empty:
        md.append("_No trades met the flagging criteria._\n")
    else:
        cols = ["priority", "score", "trade_id", "insider_name", "insider_role", "ticker", "transaction_type",
                "trade_date", "trading_days_before", "gain_or_loss_avoided", "filed_after_news", "event_id"]  # fmt: skip
        md.append(_md_table(f[cols].astype({"score": int, "gain_or_loss_avoided": int})))
        md.append("## Details\n")
        for event_id, grp in f.groupby("event_id", sort=False):
            md.append(f"### {event_id}: {grp.iloc[0]['event_headline']}\n")
            if event_id in chart_paths:
                md.append(f"![{event_id} chart]({chart_paths[event_id]})\n")
            for _, r in grp.iterrows():
                md.append(_narrative(r))
    not_flagged = res.screened[~res.screened["flagged"]] if not res.screened.empty else res.screened
    md += [
        "## Trades checked but not flagged\n",
        _md_table(
            not_flagged[
                [
                    "trade_id",
                    "insider_name",
                    "ticker",
                    "transaction_type",
                    "trade_date",
                    "event_id",
                    "reasons",
                ]
            ]
        )
        if not not_flagged.empty
        else "_none_\n",  # fmt: skip
        "## Method and limits\n",
        f"- Market model fitted on trading days {res.es_cfg.estimation_start} to {res.es_cfg.estimation_end} "
        f"before each event, against `{res.es_cfg.market_ticker}`. Days with returns above "
        f"{res.es_cfg.extreme_return:.0%} (likely data errors) are left out of the fit.\n",
        f"- Trades are checked if made within {res.sc_cfg.lookback_days} calendar days before the event. "
        "Grants and option exercises are excluded.\n",
        f"- Gains are estimated at the close on day +{res.es_cfg.event_window_end}. They ignore later "
        "price moves and costs, and are an indication, not a calculation of profit for legal purposes.\n",
        "- Duplicate filings of the same trade are counted once. Rows quarantined by Module 1 are never used.\n",
        "- The score weights are triage rules, set out in `METHODOLOGY.md`. They are not statistically estimated.\n",
    ]
    return "\n".join(md)


def write_detection_report(res: DetectionResult, output_dir: str | Path) -> Path:
    out = Path(output_dir)
    (out / "charts").mkdir(parents=True, exist_ok=True)
    res.event_table.to_csv(out / "event_study.csv", index=False)
    res.screened.to_csv(out / "screened_trades.csv", index=False)
    charts = {}
    for ev in res.events:
        if ev.status != "ok" or not ev.material:
            continue
        trades = (
            res.screened[res.screened["event_id"] == ev.event_id] if not res.screened.empty else res.screened
        )
        event_chart(ev, trades, out / "charts" / f"{ev.event_id}.png", res.es_cfg.event_window_end)
        charts[ev.event_id] = f"charts/{ev.event_id}.png"
    path = out / "detection_report.md"
    path.write_text(render_markdown(res, charts))
    return path
