"""Run Module 3 and write its report.

Outputs (in output_dir):
  network_report.md       per event: connected traders, links between insiders, chart
  account_trades_screened.csv, insider_links.csv
  graph.graphml, nodes.csv, edges.csv   (open the .graphml in Gephi or yEd to explore)
  charts/<event>_network.png
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import pandas as pd

from ..common import utc_now
from ..detection import DetectionResult
from ..detection.event_study import Panel
from .analysis import (
    GraphConfig,
    event_subgraph,
    link_to_insiders,
    links_between_insiders,
    screen_account_trades,
)
from .build import build_graph, export, node_id
from .charts import network_chart


@dataclass
class GraphResult:
    graph: nx.Graph
    accounts: pd.DataFrame
    insider_links: pd.DataFrame
    detection: DetectionResult
    cfg: GraphConfig
    created_at: str


def run_graph(
    frames: dict[str, pd.DataFrame], detection: DetectionResult, cfg: GraphConfig | None = None
) -> GraphResult:
    cfg = cfg or GraphConfig()
    g = build_graph(frames)
    acct = frames.get("account_trades", pd.DataFrame())
    screened = pd.DataFrame()
    if not acct.empty:
        panel = Panel.from_prices(frames["prices"])
        screened = screen_account_trades(
            acct, detection.events, panel, cfg, detection.es_cfg.event_window_end
        )
        screened = link_to_insiders(g, screened, frames["insider_trades"], cfg)
    links = links_between_insiders(g, detection.flagged, cfg)
    return GraphResult(g, screened, links, detection, cfg, utc_now())


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


def _trades_to_draw(res: GraphResult, event_id: str) -> pd.DataFrame:
    rows = []
    f = res.detection.flagged
    for _, r in f[f["event_id"] == event_id].iterrows():
        rows.append({"node": node_id("person", r["insider_name"]), "ticker": r["ticker"],
                     "side": r["transaction_type"], "trade_date": r["trade_date"]})  # fmt: skip
    a = res.accounts
    if not a.empty:
        for _, r in a[(a["event_id"] == event_id) & a["aligned_with_news"]].iterrows():
            rows.append({"node": node_id("account", r["account_id"]), "ticker": r["ticker"],
                         "side": r["side"], "trade_date": r["trade_date"]})  # fmt: skip
    # one dashed line per trader: keep the earliest trade
    df = pd.DataFrame(rows)
    return df.sort_values("trade_date").drop_duplicates("node") if not df.empty else df


def write_graph_report(res: GraphResult, output_dir: str | Path) -> Path:
    out = Path(output_dir)
    (out / "charts").mkdir(parents=True, exist_ok=True)
    export(res.graph, out)
    res.accounts.to_csv(out / "account_trades_screened.csv", index=False)
    res.insider_links.to_csv(out / "insider_links.csv", index=False)

    acc = res.accounts
    n_linked = int((acc["status"] == "Linked to insider").sum()) if not acc.empty else 0
    md = [
        "# Relationship Network Report\n",
        f"Generated {res.created_at} · graph of {res.graph.number_of_nodes()} entities and "
        f"{res.graph.number_of_edges()} links · **{n_linked} account trade(s) before material news are linked "
        "to an insider of that company**\n",
        "> **How to read this.** Module 2 only sees insiders who reported their own trades. This report "
        "adds account records and known relationships (family, trusts, shared directorships), then traces "
        "whether accounts that traded profitably before the news connect to an insider. A link is a reason to "
        "look closer, not proof that information passed along it. Every link lists where it came from. "
        "Read connections left to right: `A —[x]→ B` means A is x B (e.g. Kevin —[spouse of]→ Dana).\n",
    ]
    events = res.detection.event_table
    material = events[events["material"]] if not events.empty else events
    for _, ev in material.iterrows():
        eid, tk = ev["event_id"], ev["ticker"]
        result = next(e for e in res.detection.events if e.event_id == eid)
        md.append(f"## {eid}: {result.headline} ({ev['event_date']:%Y-%m-%d})\n")

        sub = event_subgraph(res.graph, eid, tk, acc, res.detection.flagged, res.insider_links)
        if sub.number_of_nodes() > 1:
            chart = network_chart(
                sub,
                f"{tk}: who traded before “{result.headline}”",
                f"Price reaction {ev['car_event_pct']:+.1f}% (t = {ev['t_event']:.1f}). "
                "Dashed = trade made before the news; solid = known relationship.",
                _trades_to_draw(res, eid),
                out / "charts" / f"{eid}_network.png",
            )
            md.append(f"![{eid} network](charts/{chart.name})\n")

        a = acc[acc["event_id"] == eid] if not acc.empty else acc
        md.append("### Account trades before the news\n")
        if a.empty:
            md.append("_No account trades in the window._\n")
        else:
            show = a[["status", "trade_id", "account_id", "account_holder", "side", "shares", "trade_date",
                      "trading_days_before", "gain_or_loss_avoided", "connection", "evidence"]].copy()  # fmt: skip
            show["gain_or_loss_avoided"] = show["gain_or_loss_avoided"].astype(int)
            md.append(_md_table(show))
            for _, r in a[a["status"] == "Linked to insider"].iterrows():
                verb = "bought" if r["side"] == "buy" else "sold"
                md.append(
                    f"- **{r['account_holder']}** ({r['account_id']}) {verb} {r['shares']:,} {tk} shares "
                    f"{r['trading_days_before']} trading days before the news (≈ ${r['gain_or_loss_avoided']:,.0f}). "
                    f"Connection to insider **{r['linked_insider']}** in {int(r['hops'])} link(s): "
                    f"{r['connection']}. Sources: {r['evidence']}.\n"
                )
        il = (
            res.insider_links[res.insider_links["event_id"] == eid]
            if not res.insider_links.empty
            else res.insider_links
        )
        md.append("### Links between flagged insiders (other than the company itself)\n")
        if il.empty:
            md.append("_None found._\n")
        else:
            for _, r in il.iterrows():
                md.append(f"- {r['connection']} (sources: {r['evidence']})\n")

    md += [
        "## Method and limits\n",
        f"- Paths are searched up to {res.cfg.max_hops} links, excluding the company itself, so two people "
        "are never “connected” merely because both are linked to ACME.\n",
        f"- Account trades are checked if made within {res.cfg.lookback_days} calendar days before a "
        "material event (from Module 2), in the direction that would profit.\n",
        "- The graph only knows the relationships it is given. “No known link” means none was found, "
        "not that none exists.\n",
        "- Relationships without an `evidence_source` are rejected by Module 1 validation.\n",
        "- Explore the full graph: open `graph.graphml` in Gephi or yEd.\n",
    ]
    path = out / "network_report.md"
    path.write_text("\n".join(md))
    return path
