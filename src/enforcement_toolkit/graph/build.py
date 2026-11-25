"""Build the entity-relationship graph.

Nodes (id = "<type>:<name>")
  person   insiders, account holders, anyone named in relationships
  entity   trusts, companies-as-owners, funds (anything that is not a person)
  account  brokerage accounts
  company  issuers whose shares were traded (by ticker)

Edges (undirected, each keeps the direction it was recorded in as `src`)
  insider_of      person  -> company   from insider filings (with role)
  account_holder  holder  -> account   from account records
  <relation>      as recorded in relationships.csv, with its evidence_source

Trades are NOT edges in this graph: two people who both traded ACME are not
"connected" just because of that. Trades are analysed separately (analysis.py)
and only drawn on the charts.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd


def node_id(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def label(node: str) -> str:
    return node.split(":", 1)[1]


def kind(node: str) -> str:
    return node.split(":", 1)[0]


def _add_edge(g: nx.Graph, a: str, b: str, relation: str, evidence: str, **extra) -> None:
    g.add_edge(a, b, relation=relation, src=a, evidence=evidence, **extra)


def build_graph(frames: dict[str, pd.DataFrame]) -> nx.Graph:
    g = nx.Graph()
    trades = frames.get("insider_trades", pd.DataFrame())
    for (name, ticker), grp in trades.groupby(["insider_name", "ticker"]) if not trades.empty else []:
        p, c = node_id("person", name), node_id("company", ticker)
        g.add_node(p, kind="person", label=name)
        g.add_node(c, kind="company", label=ticker)
        role = grp["insider_role"].dropna().iloc[0] if grp["insider_role"].notna().any() else "insider"
        _add_edge(g, p, c, "insider_of", "insider filings", role=role)

    acct = frames.get("account_trades", pd.DataFrame())
    rel = frames.get("relationships", pd.DataFrame())
    known_entities = set(rel.loc[rel["target_type"] == "entity", "target"]) | set(
        rel.loc[rel["source_type"] == "entity", "source"]
    ) if not rel.empty else set()  # fmt: skip
    for _, r in acct.drop_duplicates(["account_id", "account_holder"]).iterrows() if not acct.empty else []:
        holder_kind = "entity" if r["account_holder"] in known_entities else "person"
        h, a = node_id(holder_kind, r["account_holder"]), node_id("account", r["account_id"])
        g.add_node(h, kind=holder_kind, label=r["account_holder"])
        g.add_node(a, kind="account", label=r["account_id"])
        _add_edge(g, h, a, "account_holder", "account records")

    for _, r in rel.iterrows() if not rel.empty else []:
        s, t = node_id(r["source_type"], r["source"]), node_id(r["target_type"], r["target"])
        g.add_node(s, kind=r["source_type"], label=r["source"])
        g.add_node(t, kind=r["target_type"], label=r["target"])
        _add_edge(g, s, t, r["relation"], r["evidence_source"])
    return g


def social_view(g: nx.Graph) -> nx.Graph:
    """The graph without company nodes, so paths can't hop through 'both linked to ACME'."""
    return g.subgraph(n for n in g if kind(n) != "company")


def describe_path(g: nx.Graph, path: list[str]) -> str:
    """Arrows keep the direction each link was recorded in:  A —[x]→ B  means "A is x B".
    'ACC-1043 ←[account holder]— Kevin Whitfield —[spouse of]→ Dana Whitfield —[CFO]→ ACME'"""
    out = [label(path[0])]
    for u, v in zip(path, path[1:], strict=False):
        d = g.edges[u, v]
        rel = str(d.get("role") if d["relation"] == "insider_of" else d["relation"]).replace("_", " ")
        out.append(f"—[{rel}]→ {label(v)}" if d["src"] == u else f"←[{rel}]— {label(v)}")
    return " ".join(out)


def path_evidence(g: nx.Graph, path: list[str]) -> str:
    return "; ".join(dict.fromkeys(g.edges[u, v]["evidence"] for u, v in zip(path, path[1:], strict=False)))


def export(g: nx.Graph, folder) -> None:
    """GraphML (opens in Gephi / yEd) plus plain CSV node and edge lists."""
    from pathlib import Path

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    clean = nx.Graph()
    for n, d in g.nodes(data=True):
        clean.add_node(n, **{k: str(v) for k, v in d.items()})
    for u, v, d in g.edges(data=True):
        clean.add_edge(u, v, **{k: str(v) for k, v in d.items()})
    nx.write_graphml(clean, folder / "graph.graphml")
    pd.DataFrame([{"id": n, **d} for n, d in g.nodes(data=True)]).to_csv(folder / "nodes.csv", index=False)
    pd.DataFrame([{"a": u, "b": v, **d} for u, v, d in g.edges(data=True)]).to_csv(
        folder / "edges.csv", index=False
    )
