import numpy as np
import pandas as pd
import pytest

from enforcement_toolkit.detection import run_detection, write_detection_report
from enforcement_toolkit.detection.event_study import EventStudyConfig, Panel, study_event
from enforcement_toolkit.detection.screening import collapse_duplicate_reports
from enforcement_toolkit.validation import run_validation
from enforcement_toolkit.validation.sample_data import make_sample_data


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    paths = make_sample_data(tmp_path_factory.mktemp("data"))
    return run_detection(run_validation(paths).frames())


def test_planted_cases_are_flagged(result):
    f = result.flagged.set_index("trade_id")
    assert {"T001", "T002", "T008", "T005"} <= set(f.index)
    assert set(f.loc[["T001", "T002", "T008"], "priority"]) == {"High"}
    assert f.loc["T005", "transaction_type"] == "sell"  # sold before bad news


def test_innocent_trades_not_flagged(result):
    flagged = set(result.flagged["trade_id"])
    # BRL buys/sells with no material news nearby, and the grant, must not be flagged
    assert not flagged & {"T003", "T004", "T006", "T009"}


def test_duplicate_filing_counted_once(result):
    ids = set(result.screened["trade_id"])
    assert "T001" in ids and "T010" not in ids
    row = result.screened.set_index("trade_id").loc["T001"]
    assert row["duplicate_reports"] == "T010"


def test_quarantined_event_is_not_studied(result):
    assert "E002" not in set(result.event_table["event_id"])  # conflicting duplicate in Module 1


def test_short_history_is_reported_not_guessed(result):
    e4 = result.event_table.set_index("event_id").loc["E004"]
    assert e4["status"].startswith("only") and not e4["material"]


def test_market_model_recovers_known_beta():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2024-01-01", periods=200)
    mkt = rng.normal(0, 0.01, 200)
    stock = 1.5 * mkt + rng.normal(0, 0.002, 200)
    stock[150] += 0.10  # 10% abnormal jump on the event day
    rows = []
    for t, r in (("MKT", mkt), ("XYZ", stock)):
        close = 100 * np.cumprod(1 + r)
        rows.append(pd.DataFrame({"date": dates, "ticker": t, "open": close, "high": close,
                                  "low": close, "close": close, "volume": 1e6}))  # fmt: skip
    panel = Panel.from_prices(pd.concat(rows))
    ev = pd.Series({"event_id": "X", "ticker": "XYZ", "event_date": dates[150],
                    "event_type": "other", "headline": "test"})  # fmt: skip
    res = study_event(ev, panel, EventStudyConfig())
    assert res.beta == pytest.approx(1.5, abs=0.05)
    assert res.car_event == pytest.approx(0.10, abs=0.01)
    assert res.material


def test_collapse_keeps_earliest_filing():
    t = pd.DataFrame({
        "trade_id": ["B", "A"], "insider_name": ["X", "X"], "ticker": ["T", "T"],
        "trade_date": pd.to_datetime(["2024-01-02"] * 2), "transaction_type": ["buy", "buy"],
        "shares": [10.0, 10.0], "price": [1.0, 1.0],
        "filing_date": pd.to_datetime(["2024-01-20", "2024-01-04"]),
    })  # fmt: skip
    out = collapse_duplicate_reports(t)
    assert list(out["trade_id"]) == ["A"] and out.iloc[0]["duplicate_reports"] == "B"


def test_report_written(result, tmp_path):
    path = write_detection_report(result, tmp_path)
    text = path.read_text()
    assert "Dana Whitfield" in text and "not findings of" in text
    assert (tmp_path / "charts" / "E001.png").exists()
    assert (tmp_path / "screened_trades.csv").exists()
