"""One chart per event: abnormal price movement (top) and abnormal volume (bottom),
with each insider trade marked. Static PNG so it can go in a printed case memo."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .event_study import EventResult  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e1"
SERIES = "#2a78d6"  # single series per panel, so one hue
EVENT_SHADE = "#f0efec"


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def event_chart(
    ev: EventResult, trades: pd.DataFrame, out_path: str | Path, event_window_end: int = 1
) -> Path:
    p = ev.path
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(9, 5.6), sharex=True, gridspec_kw={"height_ratios": [3, 2], "hspace": 0.12}
    )
    fig.patch.set_facecolor(SURFACE)
    for ax in (top, bottom):
        _style(ax)
        ax.axvspan(-0.5, event_window_end + 0.5, color=EVENT_SHADE, zorder=0)

    top.plot(p["rel_day"], 100 * p["car"], color=SERIES, linewidth=2, solid_capstyle="round")
    top.axhline(0, color=INK_2, linewidth=0.8)
    top.set_ylabel("Cumulative abnormal\nreturn (%)", color=INK_2, fontsize=9)

    bottom.bar(p["rel_day"], p["volume_z"], color=SERIES, width=0.6)
    bottom.axhline(2, color=INK_2, linewidth=0.8, linestyle=(0, (2, 2)))
    bottom.text(p["rel_day"].min(), 2.15, "unusual (z = 2)", color=INK_2, fontsize=8)
    bottom.set_ylabel("Volume vs normal\n(z-score)", color=INK_2, fontsize=9)
    bottom.set_xlabel("Trading days relative to the announcement (day 0)", color=INK_2, fontsize=9)

    # Reserve headroom above the data so labels never sit on the line.
    lo_y, hi_y = top.get_ylim()
    top.set_ylim(lo_y, hi_y + 0.45 * (hi_y - lo_y))
    label_y = top.get_ylim()[1]
    top.annotate("announcement", xy=(0, 1), xycoords=("data", "axes fraction"), xytext=(2, 3),
                 textcoords="offset points", va="bottom", fontsize=8, color=INK_2)  # fmt: skip

    rel = dict(zip(p["date"], p["rel_day"], strict=True))
    for i, (_, tr) in enumerate(trades.sort_values("trade_date").iterrows()):
        x = rel.get(tr["trade_date"])
        if x is None:
            continue
        for ax in (top, bottom):
            ax.axvline(x, color=INK, linewidth=1, linestyle=(0, (4, 3)))
        label = f"{tr['insider_name']} ({tr['insider_role']})\n{tr['transaction_type']} {tr['shares']:,}"
        top.annotate(label, xy=(x, label_y), xytext=(4, -4 - 24 * (i % 3)), textcoords="offset points",
                     va="top", fontsize=8, color=INK, zorder=5,
                     bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1.5})  # fmt: skip

    title = f"{ev.ticker}: {ev.headline or ev.event_type} ({ev.event_date:%Y-%m-%d})"
    fig.suptitle(title, x=0.125, ha="left", color=INK, fontsize=11, fontweight="bold")
    fig.text(
        0.125,
        0.925,
        f"Abnormal return over days 0 to +{event_window_end}: {100 * ev.car_event:+.1f}% "
        f"(t = {ev.t_event:.1f}). Dashed lines = insider trades.",
        color=INK_2,
        fontsize=9,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return out_path
