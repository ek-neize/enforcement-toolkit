"""Output schema for case-document extraction.

The Pydantic model is the single source of truth: it generates the JSON schema
sent to the LLM (as a tool definition) AND validates what comes back.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ConductType(str, Enum):
    INSIDER_TRADING = "insider_trading"
    TIPPING = "tipping"
    MARKET_MANIPULATION = "market_manipulation"
    FRAUD = "fraud"
    MISREPRESENTATION = "misrepresentation"
    UNREGISTERED_ACTIVITY = "unregistered_activity"
    ILLEGAL_DISTRIBUTION = "illegal_distribution"
    OTHER = "other"


class Respondent(BaseModel):
    name: str = Field(description="Full name of the person or company, as written in the document.")
    entity_type: Literal["individual", "company"]
    role: str | None = Field(None, description="Role relevant to the case, e.g. 'CEO', 'director', 'tippee'.")


class Money(BaseModel):
    amount: float
    currency: str = Field(description="ISO 4217 code, e.g. 'CAD', 'USD'.")


class Sanction(BaseModel):
    kind: Literal[
        "administrative_penalty",
        "disgorgement",
        "trading_ban",
        "director_officer_ban",
        "costs",
        "other",
    ]
    respondent: str | None = Field(None, description="Name of the respondent the sanction applies to.")
    amount: Money | None = None
    duration_years: float | None = Field(
        None, description="Duration of a ban in years; null if permanent or not stated."
    )
    permanent: bool = False


class Evidence(BaseModel):
    field: str = Field(description="Name of the extracted field this quote supports, e.g. 'decision_date'.")
    quote: str = Field(description="VERBATIM span copied from the document (max ~40 words).")


class CaseExtraction(BaseModel):
    case_title: str | None = None
    decision_date: date | None = Field(None, description="Date the decision was issued (YYYY-MM-DD).")
    respondents: list[Respondent] = Field(default_factory=list)
    securities: list[str] = Field(
        default_factory=list, description="Issuers or tickers whose securities were involved."
    )
    conduct_types: list[ConductType] = Field(default_factory=list)
    conduct_start: date | None = None
    conduct_end: date | None = None
    profit_or_loss_avoided: Money | None = None
    sanctions: list[Sanction] = Field(default_factory=list)
    legislation_cited: list[str] = Field(
        default_factory=list, description="Statutes and sections, e.g. 'Securities Act (Ontario) s. 76(1)'."
    )
    evidence: list[Evidence] = Field(
        default_factory=list, description="Supporting verbatim quotes, at least one per non-empty field."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Your overall confidence that the extraction is complete and correct."
    )
    notes: str | None = Field(None, description="Ambiguities or anything a reviewer should check.")


def _inline_refs(schema: dict) -> dict:
    """Inline $ref/$defs so the schema is self-contained for tool use."""
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                target = resolve(defs[node["$ref"].split("/")[-1]])
                extras = {k: resolve(v) for k, v in node.items() if k != "$ref"}
                return {**target, **extras}
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


def tool_input_schema() -> dict:
    return _inline_refs(CaseExtraction.model_json_schema())
