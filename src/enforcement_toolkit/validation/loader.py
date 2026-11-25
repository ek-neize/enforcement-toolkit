"""Load one CSV, parse types, and split it into valid vs. quarantined rows.

Nothing is fixed silently. The only automatic changes are:
  * whitespace stripped from text, tickers upper-cased, transaction/event types lower-cased
  * exact duplicate rows dropped (keeping the first), reported as a warning
Everything else that is wrong is reported and the row is quarantined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from .issues import Issue, examples
from .schemas import DATE_COLS, KEYS, NUM_COLS, RULE_DESCRIPTIONS, SCHEMAS


@dataclass
class DatasetResult:
    name: str
    path: str
    raw_rows: int
    valid: pd.DataFrame
    quarantined: pd.DataFrame
    usable: bool = True  # False if the file structure is broken (e.g. missing columns)
    issues: list[Issue] = field(default_factory=list)


def _read_and_parse(path: Path, name: str) -> tuple[pd.DataFrame, list[Issue], set[tuple[str, int]]]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], skipinitialspace=True)
    df.columns = df.columns.str.strip().str.lower()
    issues: list[Issue] = []
    unparseable: set[tuple[str, int]] = set()

    for c in df.columns:
        df[c] = df[c].str.strip()
    if "ticker" in df:
        df["ticker"] = df["ticker"].str.upper()
    for c in ("transaction_type", "event_type", "side", "source_type", "target_type"):
        if c in df:
            df[c] = df[c].str.lower()

    def _flag(col: str, raw: pd.Series, parsed: pd.Series, what: str) -> None:
        bad = raw.notna() & parsed.isna()
        if bad.any():
            unparseable.update((col, i) for i in df.index[bad])
            issues.append(
                Issue(
                    name,
                    f"unparseable_{what}",
                    "error",
                    int(bad.sum()),
                    f"`{col}` has values that are not valid {what}s.",
                    examples(df.loc[bad], with_line=True),
                )
            )

    for c in DATE_COLS[name]:
        if c in df:
            parsed = pd.to_datetime(df[c], format="%Y-%m-%d", errors="coerce")
            _flag(c, df[c], parsed, "date")
            df[c] = parsed
    for c in NUM_COLS[name]:
        if c in df:
            parsed = pd.to_numeric(df[c].str.replace(",", "", regex=False), errors="coerce")
            _flag(c, df[c], parsed, "number")
            df[c] = parsed.astype("float64")
    return df, issues, unparseable


def _duplicates(df: pd.DataFrame, name: str) -> tuple[pd.DataFrame, list[Issue], set[int]]:
    issues = []
    exact = df.duplicated(keep="first")
    if exact.any():
        issues.append(
            Issue(
                name,
                "exact_duplicate_rows",
                "warning",
                int(exact.sum()),
                "Identical rows appear more than once. Extra copies were dropped (first kept).",
                examples(df[exact], with_line=True),
            )
        )
        df = df[~exact]
    key = [k for k in KEYS[name] if k in df]
    conflict = df.duplicated(subset=key, keep=False) if key else pd.Series(False, index=df.index)
    if conflict.any():
        issues.append(
            Issue(
                name,
                "conflicting_duplicates",
                "error",
                int(conflict.sum()),
                f"Several rows share the same key {key} but have different values. "
                "All of them are quarantined until the correct one is confirmed.",
                examples(df[conflict].sort_values(key), with_line=True),
            )
        )
    return df, issues, set(df.index[conflict])


def load_dataset(path: str | Path, name: str) -> DatasetResult:
    path = Path(path)
    schema = SCHEMAS[name]
    df, issues, unparseable = _read_and_parse(path, name)
    raw_rows = len(df)
    df, dup_issues, bad = _duplicates(df, name)
    issues += dup_issues

    try:
        schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        fc = exc.failure_cases
        structural = fc[fc["index"].isna()]
        if not structural.empty:
            issues.append(
                Issue(
                    name,
                    "file_structure",
                    "error",
                    raw_rows,
                    "The file does not have the expected columns or types; the dataset was not used.",
                    json_safe(structural[["column", "check", "failure_case"]]),
                )
            )
            return DatasetResult(name, str(path), raw_rows, df.iloc[0:0], df, usable=False, issues=issues)

        fc = fc.assign(index=fc["index"].astype(int))
        # Null failures on values we already reported as unparseable would be double counting.
        is_dup_null = fc.apply(
            lambda r: r["check"] == "not_nullable" and (r["column"], r["index"]) in unparseable, axis=1
        )
        fc = fc[~is_dup_null].copy()
        # Row-level rules (dataframe checks) are reported once per column by pandera: collapse them.
        row_rule = fc["schema_context"] == "DataFrameSchema"
        fc["column"] = fc["column"].where(~row_rule, None)
        for (col, check), grp in fc.groupby(["column", "check"], dropna=False, sort=True):
            rows = sorted(set(grp["index"]))
            where = f"`{col}`" if isinstance(col, str) else "Row"
            issues.append(
                Issue(
                    name,
                    str(check),
                    "error",
                    len(rows),
                    f"{where} failed the rule `{check}`. "
                    + RULE_DESCRIPTIONS.get(str(check), "")
                    + " Rows quarantined.",
                    examples(df.loc[rows], with_line=True),
                )
            )
        bad |= set(fc["index"])

    bad |= {i for _, i in unparseable}
    bad_idx = sorted(i for i in bad if i in df.index)
    quarantined = df.loc[bad_idx]
    valid = schema.validate(df.drop(index=bad_idx))
    return DatasetResult(name, str(path), raw_rows, valid, quarantined, issues=issues)


def json_safe(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if pd.isna(v) else str(v)) for k, v in r.items()} for r in df.to_dict("records")]
