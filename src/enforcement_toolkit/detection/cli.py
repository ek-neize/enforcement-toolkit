"""Command line:
python -m enforcement_toolkit.detection.cli --config config/detection.yaml

Runs Module 1 validation first, then the detection on validated rows only.
"""

from __future__ import annotations

import argparse
import sys

import yaml

from ..validation import Thresholds, run_validation
from .event_study import EventStudyConfig
from .report import run_detection, write_detection_report
from .screening import ScreeningConfig


def main() -> None:
    p = argparse.ArgumentParser(prog="detection")
    p.add_argument("--config", default="config/detection.yaml")
    args = p.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    with open(cfg["validation_config"]) as f:
        vcfg = yaml.safe_load(f)

    validation = run_validation(
        inputs=vcfg["inputs"],
        thresholds=Thresholds(**vcfg.get("thresholds", {})),
        custody_log=vcfg.get("custody_log"),
        source=vcfg.get("source", "unspecified"),
    )
    print(f"Module 1 validation: {validation.status} (quarantined rows are excluded)")
    frames = validation.frames()
    missing = {"prices", "insider_trades", "events"} - frames.keys()
    if missing:
        sys.exit(f"Cannot run detection: dataset(s) not usable: {', '.join(sorted(missing))}")

    result = run_detection(
        frames, EventStudyConfig(**cfg.get("event_study", {})), ScreeningConfig(**cfg.get("screening", {}))
    )
    path = write_detection_report(result, cfg["output_dir"])

    print("\nEvents:")
    for _, e in result.event_table.iterrows():
        extra = (
            f"CAR {e['car_event_pct']:+.1f}%  t={e['t_event']:.1f}  material={e['material']}"
            if e["status"] == "ok"
            else e["status"]
        )
        print(f"  {e['event_id']}  {e['ticker']:<5} {e['event_date']:%Y-%m-%d}  {extra}")
    print("\nFlagged trades:")
    for _, r in result.flagged.iterrows():
        print(
            f"  [{r['priority']:<6} {int(r['score']):>3}] {r['trade_id']}  {r['insider_name']:<15} "
            f"{r['transaction_type']:<4} {r['ticker']:<5} {r['trade_date']:%Y-%m-%d}  "
            f"${r['gain_or_loss_avoided']:>10,.0f}"
        )
    print(f"\nReport: {path}")


if __name__ == "__main__":
    main()
