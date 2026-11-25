"""Who traded before the news, and how are they connected to the insiders who knew?

For each material event from Module 2:
  1. Find ACCOUNT trades in the days before it that went the profitable way
     (bought before good news / sold before bad news). Same logic as Module 2.
  2. For each one, search the relationship graph for the shortest path from the
     account to any insider of that company (max `max_hops` links). A path such as
     account -> holder -> spouse -> CFO is a possible tipping chain.
  3. Check how the flagged insiders of the same event are linked to each other.

A link is a reason to look closer, not proof that information passed along it.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import networkx as nx
import pandas as pd

from ..detection.event_study import EventResult, Panel
from .build import describe_path, label, node_id, path_evidence, social_view


@dataclass
class GraphConfig:
    max_hops: int = 4  # links between the account and an insider (company link not counted)
    lookback_days: int = 30


def screen_account_trades(
    acct: pd.DataFrame, events: list[EventResult], panel: Panel, cfg: GraphConfig, event_window_end: int = 1
) -> pd.DataFrame:
    rows = []
    for ev in events:
        if ev.status != "ok" or not ev.material:
            continue
        t0 = panel.position(ev.event_date)
        exit_date = panel.dates[t0 + event_window_end]
        exit_price = panel.close.at[exit_date, ev.ticker]
        window = acct[
            (acct["ticker"] == ev.ticker)
            & (acct["trade_date"] < ev.event_date)
            & (acct["trade_date"] >= ev.event_date - pd.Timedelta(days=cfg.lookback_days))
        ]
        for _, tr in window.iterrows():
            side = 1 if tr["side"] == "buy" else -1
            rows.append(
                {
                    "event_id": ev.event_id,
                    "ticker": ev.ticker,
                    "event_date": ev.event_date,
                    "trade_id": tr["trade_id"],
                    "account_id": tr["account_id"],
                    "account_holder": tr["account_holder"],
                    "side": tr["side"],
                    "shares": int(tr["shares"]),
                    "trade_date": tr["trade_date"],
                    "trading_days_before": t0 - panel.position(tr["trade_date"]),
                    "gain_or_loss_avoided": round(float(side * tr["shares"] * (exit_price - tr["price"])), 0),
                    "aligned_with_news": side == ev.direction,
                }
            )
    return pd.DataFrame(rows)


def link_to_insiders(
    g: nx.Graph, screened: pd.DataFrame, insider_trades: pd.DataFrame, cfg: GraphConfig
) -> pd.DataFrame:
    if screened.empty:
        return screened
    sg = social_view(g)
    out = []
    for _, r in screened.iterrows():
        row = r.to_dict()
        row.update(linked_insider="", hops=pd.NA, connection="", evidence="")
        insiders = {
            node_id("person", n)
            for n in insider_trades.loc[insider_trades["ticker"] == r["ticker"], "insider_name"]
        }
        start = node_id("account", r["account_id"])
        if r["aligned_with_news"] and start in sg:
            reach = nx.single_source_shortest_path(sg, start, cutoff=cfg.max_hops)
            hits = sorted((len(p), t) for t, p in reach.items() if t in insiders)
            if hits:
                path = reach[hits[0][1]] + [node_id("company", r["ticker"])]
                row.update(
                    linked_insider=label(hits[0][1]),
                    hops=hits[0][0] - 1,
                    connection=describe_path(g, path),
                    evidence=path_evidence(g, path),
                )
        if not r["aligned_with_news"]:
            row["status"] = "Traded against the news"
        elif row["linked_insider"]:
            row["status"] = "Linked to insider"
        else:
            row["status"] = "No known link"
        out.append(row)
    order = {"Linked to insider": 0, "No known link": 1, "Traded against the news": 2}
    df = pd.DataFrame(out)
    return df.sort_values(
        ["event_id", "status", "gain_or_loss_avoided"],
        key=lambda s: s.map(order) if s.name == "status" else s,
        ascending=[True, True, False],
    ).reset_index(drop=True)


def links_between_insiders(g: nx.Graph, flagged: pd.DataFrame, cfg: GraphConfig) -> pd.DataFrame:
    """Flagged insiders of the same event who are connected through something other than the company."""
    sg = social_view(g)
    rows = []
    for event_id, grp in flagged.groupby("event_id") if not flagged.empty else []:
        names = sorted(set(grp["insider_name"]))
        for a, b in combinations(names, 2):
            na, nb = node_id("person", a), node_id("person", b)
            try:
                path = nx.shortest_path(sg, na, nb)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
            if len(path) - 1 <= cfg.max_hops:
                rows.append(
                    {
                        "event_id": event_id,
                        "insider_a": a,
                        "insider_b": b,
                        "hops": len(path) - 1,
                        "connection": describe_path(g, path),
                        "evidence": path_evidence(g, path),
                    }
                )
    return pd.DataFrame(rows)


def event_subgraph(g: nx.Graph, event_id: str, ticker: str, accounts: pd.DataFrame,
                   flagged: pd.DataFrame, insider_links: pd.DataFrame) -> nx.Graph:  # fmt: skip
    """The nodes worth drawing for one event: the company, its flagged insiders,
    accounts that traded the profitable way, and everything on the paths between them."""
    sg = social_view(g)
    keep = {node_id("company", ticker)}
    keep |= {node_id("person", n) for n in flagged.loc[flagged["event_id"] == event_id, "insider_name"]}
    acc = (
        accounts[(accounts["event_id"] == event_id) & accounts["aligned_with_news"]]
        if not accounts.empty
        else accounts
    )
    for _, r in acc.iterrows():
        a = node_id("account", r["account_id"])
        keep.add(a)
        keep |= set(g.neighbors(a)) if a in g else set()
        if r["linked_insider"]:
            keep |= set(nx.shortest_path(sg, a, node_id("person", r["linked_insider"])))
    for _, r in (
        insider_links[insider_links["event_id"] == event_id].iterrows() if not insider_links.empty else []
    ):
        keep |= set(
            nx.shortest_path(sg, node_id("person", r["insider_a"]), node_id("person", r["insider_b"]))
        )
    return g.subgraph(n for n in keep if n in g).copy()
