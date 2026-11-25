"""Network diagram for one event. Shape AND colour encode the node type, and every node
is labelled, so the chart reads without colour (and in black-and-white print)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from .build import kind, label, node_id  # noqa: E402

SURFACE, INK, INK_2, EDGE = "#fcfcfb", "#0b0b0b", "#52514e", "#a8a7a2"
STYLE = {  # validated categorical slots 1-4, fixed order
    "person": ("#2a78d6", "o", "Person"),
    "account": ("#eb6834", "D", "Account"),
    "entity": ("#1baf7a", "s", "Entity (trust, firm, fund)"),
    "company": ("#eda100", "h", "Company traded"),
}


def _crossings(edges: list[tuple[str, str]], pos: dict) -> int:
    """Number of pairs of edges that cross (shared endpoints don't count)."""

    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    n = 0
    for i, (a, b) in enumerate(edges):
        for c, d in edges[i + 1 :]:
            if {a, b} & {c, d}:
                continue
            p1, p2, p3, p4 = pos[a], pos[b], pos[c], pos[d]
            if ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4):
                n += 1
    return n


def _layout(g: nx.Graph) -> dict:
    """Deterministic layout with as few crossing lines as possible (same input -> same picture)."""
    h = nx.Graph()
    h.add_nodes_from(sorted(g.nodes))
    h.add_edges_from(sorted(tuple(sorted(e)) for e in g.edges))
    edges = list(h.edges)
    candidates = [nx.kamada_kawai_layout(h)]
    candidates += [
        nx.spring_layout(h, seed=s, k=1.2 / max(len(h), 1) ** 0.5, iterations=200) for s in range(12)
    ]
    best = min(range(len(candidates)), key=lambda i: (_crossings(edges, candidates[i]), i))
    pos = candidates[best]
    if best:  # spring layouts are not to a fixed scale; refine to even spacing, keeping the untangled shape
        pos = nx.kamada_kawai_layout(h, pos=pos)
        if _crossings(edges, pos) > _crossings(edges, candidates[best]):
            pos = candidates[best]
    return pos


def network_chart(
    sub: nx.Graph, title: str, subtitle: str, trades: pd.DataFrame, out_path: str | Path
) -> Path:
    """`trades`: rows with trader node id (`node`), `ticker`, `side`, `trade_date`, drawn as dashed edges."""
    g = nx.Graph()  # rebuild in sorted order so the picture is identical on every run
    g.add_nodes_from(sorted(sub.nodes(data=True)))
    g.add_edges_from(sorted((*sorted((u, v)), d) for u, v, d in sub.edges(data=True)))
    trade_edges = []
    for _, t in trades.iterrows():
        c = node_id("company", t["ticker"])
        if t["node"] in g and c in g:
            trade_edges.append((t["node"], c, f"{t['side']} {t['trade_date']:%m-%d}"))

    layout_graph = g.copy()
    layout_graph.add_edges_from((a, b) for a, b, _ in trade_edges)
    pos = _layout(layout_graph)

    fig, ax = plt.subplots(figsize=(11, 7.5))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.axis("off")

    nx.draw_networkx_edges(g, pos, ax=ax, edge_color=EDGE, width=1.5)
    nx.draw_networkx_edges(layout_graph, pos, edgelist=[(a, b) for a, b, _ in trade_edges], ax=ax,
                           edge_color=INK, width=1, style=(0, (4, 3)))  # fmt: skip

    labels = {}
    for u, v, d in g.edges(data=True):
        rel = d.get("role") if d["relation"] == "insider_of" else d["relation"]
        labels[(u, v)] = str(rel).replace("_", " ")
    for a, b, txt in trade_edges:
        existing = labels.get((a, b)) or labels.get((b, a))
        labels.pop((b, a), None)
        labels[(a, b)] = f"{existing} · {txt}" if existing else txt  # e.g. "CFO · buy 06-04"
    nx.draw_networkx_edge_labels(layout_graph, pos, edge_labels=labels, ax=ax, font_size=7, font_color=INK_2,
                                 rotate=False, bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 0.8})  # fmt: skip

    for k, (color, shape, _) in STYLE.items():
        nodes = [n for n in g if kind(n) == k]
        nx.draw_networkx_nodes(g, pos, nodelist=nodes, node_color=color, node_shape=shape, node_size=520,
                               edgecolors=SURFACE, linewidths=2, ax=ax)  # fmt: skip
    for n, (x, y) in pos.items():
        ax.annotate(label(n), (x, y), xytext=(0, -15), textcoords="offset points", ha="center", va="top",
                    fontsize=8.5, color=INK, fontweight="bold" if kind(n) == "company" else "normal", zorder=6,
                    bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1, "alpha": 0.9})  # fmt: skip

    handles = [Line2D([], [], marker=s, color=c, linestyle="", markersize=9, label=lab)
               for k, (c, s, lab) in STYLE.items() if any(kind(n) == k for n in g)]  # fmt: skip
    handles.append(Line2D([], [], color=INK, linestyle=(0, (4, 3)), label="Trade before the news"))
    handles.append(Line2D([], [], color=EDGE, linewidth=1.5, label="Known relationship"))
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.0),
        ncol=3,
        frameon=False,
        fontsize=8,
        labelcolor=INK_2,
    )  # below the drawing, so it can never cover a node

    ys = [y for _, y in pos.values()]
    ax.set_ylim(min(ys) - 0.15, max(ys) + 0.12)
    fig.suptitle(title, x=0.06, ha="left", color=INK, fontsize=12, fontweight="bold")
    fig.text(0.06, 0.925, subtitle, color=INK_2, fontsize=9)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)
    return out_path
