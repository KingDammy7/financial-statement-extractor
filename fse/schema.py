"""The contract every extractor (LLM or rules) must satisfy.

The same JSON Schema is handed to Claude as a tool's input_schema, exported to
web/src/schema.json for the live demo, and used to validate whatever comes back.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

StatementType = Literal["income_statement", "balance_sheet"]
Units = Literal["units", "thousands", "millions"]

INCOME_FIELDS = ("revenue", "cost_of_revenue", "gross_profit", "operating_expenses", "operating_income", "net_income")
BALANCE_FIELDS = ("total_assets", "total_liabilities", "total_equity")
_MULTIPLIER = {"units": 1, "thousands": 1_000, "millions": 1_000_000}


class Amount(BaseModel):
    value: float = Field(description="The number exactly as printed, before applying units. Negative for losses or bracketed numbers.")
    page: Optional[int] = Field(default=None, ge=1, description="1-based page the number was read from.")
    label_in_doc: Optional[str] = Field(default=None, max_length=120, description="The row label as printed, e.g. 'Total net revenue'.")


class Extraction(BaseModel):
    company_name: Optional[str] = Field(default=None, max_length=200)
    statement_type: StatementType
    period_label: Optional[str] = Field(default=None, max_length=60, description="As printed, e.g. 'Year ended 31 December 2025'.")
    period_end: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="ISO date YYYY-MM-DD if determinable.")
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$", description="ISO 4217 code, e.g. USD.")
    units: Units = Field(default="units", description="Scale stated on the document, e.g. '$ in thousands' -> thousands.")

    revenue: Optional[Amount] = None
    cost_of_revenue: Optional[Amount] = None
    gross_profit: Optional[Amount] = None
    operating_expenses: Optional[Amount] = None
    operating_income: Optional[Amount] = None
    net_income: Optional[Amount] = None

    total_assets: Optional[Amount] = None
    total_liabilities: Optional[Amount] = None
    total_equity: Optional[Amount] = None

    notes: list[str] = Field(default_factory=list, description="Anything ambiguous: restatements, missing totals, unclear units.")

    @field_validator("currency", mode="before")
    @classmethod
    def _upper(cls, v):
        return v.upper() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _has_core_fields(self):
        if self.statement_type == "income_statement" and not (self.revenue or self.net_income):
            raise ValueError("income_statement needs at least revenue or net_income")
        if self.statement_type == "balance_sheet" and not self.total_assets:
            raise ValueError("balance_sheet needs total_assets")
        return self

    def amount(self, name: str) -> Optional[float]:
        """Value in base currency units (units applied)."""
        a: Optional[Amount] = getattr(self, name)
        return None if a is None else a.value * _MULTIPLIER[self.units]


def tool_schema() -> dict:
    """JSON Schema for the Claude tool. Pydantic emits $defs, which the API accepts."""
    return Extraction.model_json_schema()
