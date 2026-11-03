"""Deterministic extractor for clean, conventionally labelled statements.

Used as the no-API-key fallback, and as a cross-check: when the rules and the
LLM disagree on a number, that field is worth a human look.
"""
from __future__ import annotations

import re
from typing import Optional

from .documents import Page, guess_statement_type
from .schema import Amount, Extraction

LABELS: dict[str, list[str]] = {
    "revenue": [r"total (net )?revenues?", r"net revenues?", r"revenues?", r"total sales", r"net sales", r"turnover"],
    "cost_of_revenue": [r"(total )?cost of (revenues?|sales|services)", r"direct costs?"],
    "gross_profit": [r"gross (profit|margin)"],
    "operating_expenses": [r"total operating expenses", r"operating expenses", r"total overheads?"],
    "operating_income": [r"operating (income|profit|loss)", r"income from operations"],
    "net_income": [r"net (income|profit|loss)( for the (year|period))?", r"profit for the (year|period)"],
    "total_assets": [r"total assets"],
    "total_liabilities": [r"total liabilities"],
    "total_equity": [r"total (stockholders'?|shareholders'?|owners'?|members'?) ?equity", r"total equity"],
}

NUMBER = r"(\(?-?\$?\s?[\d,]+(?:\.\d+)?\)?)"


def parse_number(raw: str) -> float:
    s = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    negative = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = s.strip("()-")
    return -float(s) if negative else float(s)


def _find(pages: list[Page], patterns: list[str]) -> Optional[Amount]:
    for pat in patterns:
        rx = re.compile(rf"^[ \t]*({pat})\b[^\d(\-$\n]*{NUMBER}", re.IGNORECASE | re.MULTILINE)
        for p in pages:
            m = rx.search(p.text)
            if m:
                return Amount(value=parse_number(m.group(m.lastindex)), page=p.number, label_in_doc=m.group(1).strip())
    return None


def extract(pages: list[Page]) -> Extraction:
    text = "\n".join(p.text for p in pages)
    stype = guess_statement_type(pages)
    units = "thousands" if re.search(r"in thousands|\(\$?000s?\)|£'?000", text, re.I) else \
            "millions" if re.search(r"in millions", text, re.I) else "units"
    currency = "GBP" if "£" in text else "EUR" if "€" in text else "USD" if "$" in text or "USD" in text else None
    period = re.search(r"((?:year|period|quarter|twelve months) ended [A-Z][a-z]+ \d{1,2},? \d{4}|as (?:of|at) [A-Z][a-z]+ \d{1,2},? \d{4})", text, re.I)
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)

    fields = LABELS.keys() if stype == "income_statement" else ("total_assets", "total_liabilities", "total_equity")
    values = {f: _find(pages, LABELS[f]) for f in fields}
    return Extraction(
        company_name=first_line[:200] if first_line else None,
        statement_type=stype,  # type: ignore[arg-type]
        period_label=period.group(1) if period else None,
        currency=currency,
        units=units,  # type: ignore[arg-type]
        notes=["Extracted by deterministic rules (no LLM)."],
        **{k: v for k, v in values.items() if v is not None},
    )
