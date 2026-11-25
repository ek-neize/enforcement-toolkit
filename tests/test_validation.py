import json

import pandas as pd
import pytest

from enforcement_toolkit.validation import Thresholds, run_validation, write_report
from enforcement_toolkit.validation.custody import CustodyLog
from enforcement_toolkit.validation.sample_data import make_sample_data

PLANTED = {
    ("prices", "exact_duplicate_rows"),
    ("prices", "conflicting_duplicates"),
    ("prices", "high_is_daily_max"),
    ("prices", "low_is_daily_min"),
    ("prices", "unparseable_number"),
    ("prices", "missing_trading_days"),
    ("prices", "extreme_daily_returns"),
    ("prices", "zero_volume_runs"),
    ("prices", "stale_prices"),
    ("insider_trades", "filing_not_before_trade"),
    ("insider_trades", "late_filings"),
    ("insider_trades", "price_outside_daily_range"),
    ("insider_trades", "possible_duplicate_reports"),
    ("insider_trades", "no_price_coverage"),
    ("events", "conflicting_duplicates"),
    ("events", "insufficient_price_window"),
    ("relationships", "not_nullable"),
}


@pytest.fixture
def dirty(tmp_path):
    paths = make_sample_data(tmp_path / "data")
    return run_validation(paths, custody_log=tmp_path / "custody.jsonl", source="test"), tmp_path


def test_every_planted_issue_is_detected(dirty):
    result, _ = dirty
    found = {(i.dataset, i.check) for i in result.issues}
    assert PLANTED <= found, f"missed: {PLANTED - found}"
    assert result.status == "FAIL"


def test_quarantined_rows_never_reach_analysis(dirty):
    result, _ = dirty
    prices = result.frames()["prices"]
    assert (prices["high"] >= prices[["open", "low", "close"]].max(axis=1)).all()
    assert not prices.duplicated(["date", "ticker"]).any()
    assert pd.api.types.is_datetime64_any_dtype(prices["date"])
    trades = result.frames()["insider_trades"]
    assert (trades["filing_date"] >= trades["trade_date"]).all()


def test_clean_data_passes(tmp_path):
    paths = make_sample_data(tmp_path, inject_issues=False)
    result = run_validation(paths, Thresholds(event_lookback_days=0))
    assert not [i for i in result.issues if i.severity == "error"]


def test_missing_column_marks_dataset_unusable(tmp_path):
    paths = make_sample_data(tmp_path, inject_issues=False)
    df = pd.read_csv(paths["prices"]).drop(columns=["volume"])
    df.to_csv(paths["prices"], index=False)
    result = run_validation(paths)
    assert not result.datasets["prices"].usable
    assert any(i.check == "file_structure" for i in result.issues)


def test_report_files_written(dirty):
    result, tmp = dirty
    write_report(result, tmp / "out")
    payload = json.loads((tmp / "out" / "issues.json").read_text())
    assert payload["status"] == "FAIL"
    assert (tmp / "out" / "quarantine_prices.csv").exists()
    assert "Data Quality Report" in (tmp / "out" / "data_quality_report.md").read_text()


def test_custody_detects_tampering(tmp_path):
    f = tmp_path / "evidence.csv"
    f.write_text("a,b\n1,2\n")
    log = CustodyLog(tmp_path / "custody.jsonl")
    first = log.register(f, source="test")
    assert log.register(f, source="test").sha256 == first.sha256  # unchanged: no new entry
    assert len(log.entries()) == 1
    assert log.verify() == []

    f.write_text("a,b\n1,3\n")  # altered after registration
    assert log.verify()[0]["problem"] == "hash_mismatch"
    changed = log.register(f, source="test")
    assert changed.previous_sha256 == first.sha256 and len(log.entries()) == 2
