"""Expected structure of each dataset (pandera). Rows that break these rules are
ERRORS: they are quarantined and excluded from analysis until resolved.

Expected CSV columns
--------------------
prices.csv          date, ticker, open, high, low, close, volume
insider_trades.csv  trade_id, insider_name, insider_role, ticker, trade_date,
                    filing_date, transaction_type, shares, price
events.csv          event_id, ticker, event_date, event_type, headline
account_trades.csv  trade_id, account_id, account_holder, ticker, trade_date, side, shares, price
                    (optional: account-level records, e.g. obtained from dealers)
relationships.csv   source, source_type, target, target_type, relation, evidence_source
                    (optional: known links between people / entities / accounts)
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

TICKER_PATTERN = r"^[A-Z0-9][A-Z0-9.\-]{0,9}$"
TRANSACTION_TYPES = ["buy", "sell", "exercise", "grant", "other"]
EVENT_TYPES = ["earnings", "m_and_a", "guidance", "regulatory", "other"]


class PriceSchema(pa.DataFrameModel):
    date: Series[pd.Timestamp]
    ticker: Series[str] = pa.Field(str_matches=TICKER_PATTERN)
    open: Series[float] = pa.Field(gt=0)
    high: Series[float] = pa.Field(gt=0)
    low: Series[float] = pa.Field(gt=0)
    close: Series[float] = pa.Field(gt=0)
    volume: Series[float] = pa.Field(ge=0)

    class Config:
        strict = True  # unexpected columns = the file format changed; stop and check
        coerce = True

    @pa.check("volume", name="volume_is_whole_number")
    def volume_is_whole_number(cls, s: Series[float]) -> Series[bool]:
        return s.isna() | (s % 1 == 0)

    @pa.dataframe_check(name="high_is_daily_max")
    def high_is_daily_max(cls, df: pd.DataFrame) -> Series[bool]:
        cols = df[["open", "high", "low", "close"]]
        return cols.isna().any(axis=1) | (df["high"] >= cols.max(axis=1))

    @pa.dataframe_check(name="low_is_daily_min")
    def low_is_daily_min(cls, df: pd.DataFrame) -> Series[bool]:
        cols = df[["open", "high", "low", "close"]]
        return cols.isna().any(axis=1) | (df["low"] <= cols.min(axis=1))


class InsiderTradeSchema(pa.DataFrameModel):
    trade_id: Series[str]
    insider_name: Series[str]
    insider_role: Series[str] = pa.Field(nullable=True)
    ticker: Series[str] = pa.Field(str_matches=TICKER_PATTERN)
    trade_date: Series[pd.Timestamp]
    filing_date: Series[pd.Timestamp]
    transaction_type: Series[str] = pa.Field(isin=TRANSACTION_TYPES)
    shares: Series[float] = pa.Field(gt=0)
    price: Series[float] = pa.Field(ge=0)  # grants can be at $0

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check(name="filing_not_before_trade")
    def filing_not_before_trade(cls, df: pd.DataFrame) -> Series[bool]:
        d = df[["trade_date", "filing_date"]]
        return d.isna().any(axis=1) | (df["filing_date"] >= df["trade_date"])


class EventSchema(pa.DataFrameModel):
    event_id: Series[str]
    ticker: Series[str] = pa.Field(str_matches=TICKER_PATTERN)
    event_date: Series[pd.Timestamp]
    event_type: Series[str] = pa.Field(isin=EVENT_TYPES)
    headline: Series[str] = pa.Field(nullable=True)

    class Config:
        strict = True
        coerce = True


NODE_TYPES = ["person", "entity", "account"]


class AccountTradeSchema(pa.DataFrameModel):
    trade_id: Series[str]
    account_id: Series[str]
    account_holder: Series[str]
    ticker: Series[str] = pa.Field(str_matches=TICKER_PATTERN)
    trade_date: Series[pd.Timestamp]
    side: Series[str] = pa.Field(isin=["buy", "sell"])
    shares: Series[float] = pa.Field(gt=0)
    price: Series[float] = pa.Field(gt=0)

    class Config:
        strict = True
        coerce = True


class RelationshipSchema(pa.DataFrameModel):
    source: Series[str]
    source_type: Series[str] = pa.Field(isin=NODE_TYPES)
    target: Series[str]
    target_type: Series[str] = pa.Field(isin=NODE_TYPES)
    relation: Series[str]
    evidence_source: Series[str]  # where the link came from: a link without a source is not evidence

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check(name="no_self_links")
    def no_self_links(cls, df: pd.DataFrame) -> Series[bool]:
        return df["source"] != df["target"]


SCHEMAS = {
    "prices": PriceSchema,
    "insider_trades": InsiderTradeSchema,
    "events": EventSchema,
    "account_trades": AccountTradeSchema,
    "relationships": RelationshipSchema,
}

# Columns whose values must be unique as a group. Conflicting duplicates = error.
KEYS = {
    "prices": ["date", "ticker"],
    "insider_trades": ["trade_id"],
    "events": ["event_id"],
    "account_trades": ["trade_id"],
    "relationships": ["source", "target", "relation"],
}
DATE_COLS = {
    "prices": ["date"],
    "insider_trades": ["trade_date", "filing_date"],
    "events": ["event_date"],
    "account_trades": ["trade_date"],
    "relationships": [],
}
NUM_COLS = {
    "prices": ["open", "high", "low", "close", "volume"],
    "insider_trades": ["shares", "price"],
    "events": [],
    "account_trades": ["shares", "price"],
    "relationships": [],
}

# Plain-language explanations for the report. Unlisted rules fall back to the rule name.
RULE_DESCRIPTIONS = {
    "high_is_daily_max": "The day's high is below its open, low or close, which is impossible. "
    "Usually columns swapped or a bad tick.",
    "low_is_daily_min": "The day's low is above its open, high or close, which is impossible.",
    "volume_is_whole_number": "Volume is not a whole number of shares.",
    "no_self_links": "A relationship links something to itself.",
    "filing_not_before_trade": "The filing date is earlier than the trade date: one of the two dates is wrong.",
    "not_nullable": "Required value is blank.",
    "greater_than(0)": "Value must be greater than zero.",
    "greater_than_or_equal_to(0)": "Value must not be negative.",
}
