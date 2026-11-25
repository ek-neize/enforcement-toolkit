"""Command line:
python -m enforcement_toolkit.graph.cli --config config/graph.yaml

Runs Module 1 (validation) and Module 2 (detection) first, then builds the graph.
"""

from __future__ import annotations

import argparse
import sys

import yaml

from ..detection import EventStudyConfig, ScreeningConfig, run_detection
from ..validation import Thresholds, run_validation
from .analysis import GraphConfig
from .report import run_graph, write_graph_report


def main() -> None:
    p = argparse.ArgumentParser(prog="graph")
    p.add_argument("--config", default="config/graph.yaml")
    args = p.parse_args()
    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    with open(cfg["detection_config"]) as f:
        dcfg = yaml.safe_load(f)
    with open(dcfg["validation_config"]) as f:
        vcfg = yaml.safe_load(f)

    validation = run_validation(
        inputs=vcfg["inputs"],
        thresholds=Thresholds(**vcfg.get("thresholds", {})),
        custody_log=vcfg.get("custody_log"),
        source=vcfg.get("source", "unspecified"),
    )
    frames = validation.frames()
    print(f"Module 1 validation: {validation.status} (quarantined rows are excluded)")
    missing = {"prices", "insider_trades", "events"} - frames.keys()
    if missing:
        sys.exit(f"Cannot run: dataset(s) not usable: {', '.join(sorted(missing))}")

    detection = run_detection(
        frames, EventStudyConfig(**dcfg.get("event_study", {})), ScreeningConfig(**dcfg.get("screening", {}))
    )
    print(f"Module 2 detection: {len(detection.flagged)} flagged insider trade(s)")

    res = run_graph(frames, detection, GraphConfig(**cfg.get("graph", {})))
    path = write_graph_report(res, cfg["output_dir"])
    print(f"Module 3 graph: {res.graph.number_of_nodes()} nodes, {res.graph.number_of_edges()} links\n")
    if not res.accounts.empty:
        for _, r in res.accounts.iterrows():
            print(f"  [{r['status']:<24}] {r['event_id']} {r['account_id']:<9} {r['account_holder']:<22} "
                  f"{r['side']:<4} {r['trade_date']:%Y-%m-%d}  {r['connection']}")  # fmt: skip
    if not res.insider_links.empty:
        print("\nLinks between flagged insiders:")
        for _, r in res.insider_links.iterrows():
            print(f"  {r['event_id']}: {r['connection']}")
    print(f"\nReport: {path}")


if __name__ == "__main__":
    main()
