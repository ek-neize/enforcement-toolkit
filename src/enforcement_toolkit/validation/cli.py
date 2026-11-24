"""Command line:
python -m enforcement_toolkit.validation.cli sample   --out data/sample
python -m enforcement_toolkit.validation.cli validate --config config/validation.yaml [--strict]
python -m enforcement_toolkit.validation.cli verify-custody --log data/custody_log.jsonl
"""

from __future__ import annotations

import argparse
import sys

import yaml

from .checks import Thresholds
from .custody import CustodyLog
from .report import run_validation, write_report
from .sample_data import make_sample_data


def cmd_sample(args) -> None:
    for name, p in make_sample_data(args.out, inject_issues=not args.clean).items():
        print(f"{name:<16}{p}")


def cmd_validate(args) -> int:
    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    result = run_validation(
        inputs=cfg["inputs"],
        thresholds=Thresholds(**cfg.get("thresholds", {})),
        custody_log=cfg.get("custody_log"),
        source=cfg.get("source", "unspecified"),
    )
    report = write_report(result, cfg["output_dir"])
    print(f"Status: {result.status}")
    for i in result.issues:
        print(f"  [{i.severity.upper():<7}] {i.dataset:<15} {i.check:<30} {i.n_rows:>4} row(s)")
    print(f"Report: {report}")
    return 1 if args.strict and result.status == "FAIL" else 0


def cmd_verify(args) -> int:
    problems = CustodyLog(args.log).verify()
    for p in problems:
        print(p)
    print("All registered files match their recorded hashes." if not problems else "CUSTODY CHECK FAILED")
    return 1 if problems else 0


def main() -> None:
    p = argparse.ArgumentParser(prog="validation")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("sample", help="Write synthetic demo data with planted problems")
    s.add_argument("--out", default="data/sample")
    s.add_argument("--clean", action="store_true", help="Generate data without planted problems")
    s.set_defaults(func=cmd_sample)

    v = sub.add_parser("validate", help="Validate datasets and write the data-quality report")
    v.add_argument("--config", default="config/validation.yaml")
    v.add_argument("--strict", action="store_true", help="Exit with code 1 if any errors are found")
    v.set_defaults(func=cmd_validate)

    c = sub.add_parser("verify-custody", help="Re-hash registered files and compare with the log")
    c.add_argument("--log", default="data/custody_log.jsonl")
    c.set_defaults(func=cmd_verify)

    args = p.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
