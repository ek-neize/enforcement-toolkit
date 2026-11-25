"""Module 3: entity-relationship graph linking traders to insiders."""

from .analysis import GraphConfig
from .report import GraphResult, run_graph, write_graph_report

__all__ = ["GraphConfig", "GraphResult", "run_graph", "write_graph_report"]
