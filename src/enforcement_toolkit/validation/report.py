"""Run the full validation and write a plain-language report.

Outputs (in output_dir):
  data_quality_report.md   readable by a case team
  issues.json              machine-readable, for CI or downstream code
  quarantine_<dataset>.csv rows excluded from analysis, with their source line numbers
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from ..common import utc_now
from .checks import Thresholds, run_all
from .custody import CustodyEntry, CustodyLog
from .issues import Issue
from .loader import DatasetResult, load_dataset


@dataclass
class ValidationResult:
    datasets: dict[str, DatasetResult]
    issues: list[Issue]
    custody: list[CustodyEntry]
    created_at: str

    @property
    def status(self) -> str:
        if any(i.severity == "error" for i in self.issues):
            return "FAIL"
        return "PASS WITH WARNINGS" if self.issues else "PASS"

    def frames(self) -> dict[str, pd.DataFrame]:
        """Validated data, ready for analysis modules."""
        return {k: d.valid for k, d in self.datasets.items() if d.usable}


def run_validation(
    inputs: dict[str, str | Path],
    thresholds: Thresholds | None = None,
    custody_log: str | Path | None = None,
    source: str = "unspecified",
) -> ValidationResult:
    t = thresholds or Thresholds()
    custody = []
    if custody_log:
        log = CustodyLog(custody_log)
        custody = [log.register(p, source=source, note=name) for name, p in inputs.items()]

    datasets = {name: load_dataset(p, name) for name, p in inputs.items()}
    issues = [i for d in datasets.values() for i in d.issues]
    for e in custody:
        if e.changed:
            issues.append(
                Issue(
                    "custody",
                    "source_file_changed",
                    "warning",
                    1,
                    f"{e.path} changed since it was last registered (previous SHA-256 "
                    f"{e.previous_sha256[:12]}…). Confirm this was an intended new delivery.",
                )
            )
    usable = {k: d for k, d in datasets.items() if d.usable}
    issues += run_all(
        {k: d.valid for k, d in usable.items()}, t, {k: d.quarantined for k, d in usable.items()}
    )
    order = {"error": 0, "warning": 1}
    issues.sort(key=lambda i: (order[i.severity], i.dataset, i.check))
    return ValidationResult(datasets, issues, custody, utc_now())


# ---------------------------------------------------------------- rendering
def _md_table(rows: list[dict]) -> str:
    if not rows:
        return "_none_\n"
    cols = list(dict.fromkeys(k for r in rows for k in r))
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |")
    return "\n".join(out) + "\n"


def _summary_row(d: DatasetResult) -> dict:
    row = {
        "dataset": d.name,
        "raw rows": d.raw_rows,
        "valid": len(d.valid),
        "quarantined": len(d.quarantined),
    }
    date_col = next((c for c in ("date", "trade_date", "event_date") if c in d.valid), None)
    if date_col and not d.valid.empty:
        row["date range"] = f"{d.valid[date_col].min():%Y-%m-%d} → {d.valid[date_col].max():%Y-%m-%d}"
    if "ticker" in d.valid:
        row["tickers"] = d.valid["ticker"].nunique()
    if not d.usable:
        row["valid"] = "NOT USABLE"
    return row


def render_markdown(r: ValidationResult) -> str:
    n_err = sum(i.severity == "error" for i in r.issues)
    n_warn = len(r.issues) - n_err
    md = [
        "# Data Quality Report\n",
        f"**Status: {r.status}** · {n_err} error type(s), {n_warn} warning type(s) · generated {r.created_at}\n",
        "**Errors** mean rows were quarantined and left out of the analysis until resolved with the "
        "data provider or case team. **Warnings** do not block analysis but need an analyst's review.\n",
        "## Source files (chain of custody)\n",
        _md_table(
            [
                {
                    "file": e.path,
                    "sha256": f"`{e.sha256[:16]}…`",
                    "bytes": e.size_bytes,
                    "registered": e.registered_at,
                    "changed since last run": "YES" if e.changed else "no",
                }
                for e in r.custody
            ]
        ),
        "## Datasets\n",
        _md_table([_summary_row(d) for d in r.datasets.values()]),
        "## Issues found\n",
        _md_table(
            [
                {"severity": i.severity.upper(), "dataset": i.dataset, "check": i.check, "rows": i.n_rows}
                for i in r.issues
            ]
        ),
    ]
    if r.issues:
        md.append("## Details\n")
    for i in r.issues:
        md.append(f"### [{i.severity.upper()}] {i.dataset} · {i.check} ({i.n_rows})\n")
        md.append(i.description + "\n")
        if i.examples:
            md.append("Examples:\n\n" + _md_table(i.examples))
    return "\n".join(md)


def write_report(r: ValidationResult, output_dir: str | Path) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "data_quality_report.md").write_text(render_markdown(r))
    payload = {
        "status": r.status,
        "created_at": r.created_at,
        "custody": [asdict(e) for e in r.custody],
        "issues": [asdict(i) for i in r.issues],
    }
    (out / "issues.json").write_text(json.dumps(payload, indent=2, default=str))
    for name, d in r.datasets.items():
        q = out / f"quarantine_{name}.csv"
        if not d.quarantined.empty:
            d.quarantined.assign(csv_line=d.quarantined.index + 2).to_csv(q, index=False)
        elif q.exists():
            q.unlink()
    return out / "data_quality_report.md"
