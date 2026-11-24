from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

Severity = Literal["error", "warning"]


@dataclass
class Issue:
    dataset: str
    check: str
    severity: Severity
    n_rows: int
    description: str
    examples: list[dict] = field(default_factory=list)


def examples(df: pd.DataFrame, n: int = 5, with_line: bool = False) -> list[dict]:
    """First n rows as JSON-safe dicts.

    with_line=True adds `csv_line` (the row's line number in the source file) so an
    analyst can find it. Only valid when df still carries the index from loading.
    """
    if df.empty:
        return []
    out = df.head(n).copy()
    if with_line:
        out.insert(0, "csv_line", out.index + 2)  # +1 header row, +1 for 1-based lines
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records"))
