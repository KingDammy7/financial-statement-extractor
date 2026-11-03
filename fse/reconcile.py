"""Arithmetic checks. An extraction that does not add up is flagged, never silently trusted.

This is where the model's output gets checked: the LLM reads numbers, these rules decide
whether the numbers are internally consistent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .schema import Extraction


@dataclass
class Check:
    name: str
    formula: str
    expected: Optional[float]
    actual: Optional[float]
    status: str  # "pass" | "fail" | "skipped"

    @property
    def diff(self) -> Optional[float]:
        if self.expected is None or self.actual is None:
            return None
        return round(self.actual - self.expected, 2)

    def to_dict(self) -> dict:
        return {**asdict(self), "diff": self.diff}


def _check(name: str, formula: str, expected: Optional[float], actual: Optional[float], tolerance: float) -> Check:
    if expected is None or actual is None:
        return Check(name, formula, expected, actual, "skipped")
    # tolerance is relative to the larger magnitude, with a floor of 1 unit for rounding on the page
    allowed = max(1.0, tolerance * max(abs(expected), abs(actual)))
    return Check(name, formula, expected, actual, "pass" if abs(actual - expected) <= allowed else "fail")


def _bound(name: str, formula: str, limit: Optional[float], actual: Optional[float]) -> Check:
    """actual must not exceed limit (a profit larger than revenue usually means a misread row)."""
    if limit is None or actual is None:
        return Check(name, formula, limit, actual, "skipped")
    return Check(name, formula, limit, actual, "pass" if actual <= limit else "fail")


def _sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or b is None else a - b


def _add(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or b is None else a + b


def reconcile(x: Extraction, tolerance: float = 0.005) -> list[Check]:
    a = x.amount
    if x.statement_type == "income_statement":
        return [
            _check("gross_profit", "revenue - cost_of_revenue", _sub(a("revenue"), a("cost_of_revenue")), a("gross_profit"), tolerance),
            _check("operating_income", "gross_profit - operating_expenses", _sub(a("gross_profit"), a("operating_expenses")), a("operating_income"), tolerance),
            _bound("net_income_within_revenue", "net_income <= revenue", a("revenue"), a("net_income")),
        ]
    return [
        _check("balance", "total_liabilities + total_equity = total_assets", _add(a("total_liabilities"), a("total_equity")), a("total_assets"), tolerance),
    ]


def summary(checks: list[Check]) -> str:
    failed = [c for c in checks if c.status == "fail"]
    if failed:
        return "needs_review"
    if all(c.status == "skipped" for c in checks):
        return "unverified"
    return "reconciled"
