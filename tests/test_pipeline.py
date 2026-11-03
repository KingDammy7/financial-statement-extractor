from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from fse import llm
from fse.documents import chunk_pages, load, retrieve
from fse.pipeline import extract_file
from fse.reconcile import reconcile, summary
from fse.rules import parse_number
from fse.schema import Extraction

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


# --- rules + reconciliation on the generated samples ------------------------

@pytest.mark.parametrize("name,status,field,value", [
    ("riverbend_income_statement_2025.pdf", "reconciled", "revenue", 8_648_000),
    ("riverbend_balance_sheet_2025.pdf", "reconciled", "total_assets", 5_143_000),
    ("northgate_income_statement_2025_typo.pdf", "needs_review", "gross_profit", 3_473_000),
    ("hillside_income_statement_2025.xlsx", "reconciled", "net_income", 1_902_000),
])
def test_rules_extraction(name, status, field, value):
    r = extract_file(SAMPLES / name, mode="rules")
    assert r["status"] == status
    assert r["normalised"][field] == value
    assert r["extraction"]["units"] == "thousands"


def test_typo_is_caught_by_reconciliation():
    r = extract_file(SAMPLES / "northgate_income_statement_2025_typo.pdf", mode="rules")
    failed = {c["name"]: c for c in r["reconciliation"] if c["status"] == "fail"}
    assert failed["gross_profit"]["diff"] == -270_000  # 3,473 printed vs 3,743 implied


def test_scanned_pdf_goes_through_ocr():
    r = extract_file(SAMPLES / "lakeside_income_statement_2025_scanned.pdf", mode="rules")
    assert r["trace"]["ocr_pages"] == [1]
    assert r["normalised"]["revenue"] == 5_120_000
    assert r["status"] == "reconciled"


@pytest.mark.parametrize("raw,expected", [("1,234", 1234), ("(88)", -88), ("-293", -293), ("$ 4,905", 4905), ("12.5", 12.5)])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


# --- schema -----------------------------------------------------------------

def test_schema_rejects_balance_sheet_without_total_assets():
    with pytest.raises(ValidationError):
        Extraction(statement_type="balance_sheet", total_equity={"value": 1})


def test_schema_rejects_bad_currency_and_date():
    with pytest.raises(ValidationError):
        Extraction(statement_type="income_statement", revenue={"value": 1}, currency="DOLLARS")
    with pytest.raises(ValidationError):
        Extraction(statement_type="income_statement", revenue={"value": 1}, period_end="31/12/2025")


def test_balance_check_fails_when_it_does_not_balance():
    x = Extraction(statement_type="balance_sheet", total_assets={"value": 100}, total_liabilities={"value": 60}, total_equity={"value": 30})
    assert summary(reconcile(x)) == "needs_review"


# --- retrieval --------------------------------------------------------------

def test_retrieval_prefers_the_statement_page_over_the_cover():
    pages = load(SAMPLES / "riverbend_income_statement_2025.pdf")
    top = retrieve(chunk_pages(pages), "income_statement", k=1)
    assert top[0].page == 2


# --- LLM path with a fake client (no network) -------------------------------

def _tool_response(payload, id_="t1"):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=llm.TOOL_NAME, input=payload, id=id_)])


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


GOOD = {"statement_type": "income_statement", "units": "thousands", "currency": "usd",
        "revenue": {"value": 8648, "page": 2}, "cost_of_revenue": {"value": 4905, "page": 2},
        "gross_profit": {"value": 3743, "page": 2}, "net_income": {"value": 1039, "page": 2}}


def test_llm_forces_the_tool_and_validates():
    fake = FakeMessages([_tool_response(GOOD)])
    r = extract_file(SAMPLES / "riverbend_income_statement_2025.pdf", mode="llm", client=fake)
    call = fake.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": llm.TOOL_NAME}
    assert call["temperature"] == 0
    assert "--- page 2 ---" in call["messages"][0]["content"]
    assert r["extractor"] == "llm" and r["status"] == "reconciled"
    assert r["extraction"]["currency"] == "USD"
    assert r["trace"]["prompt_version"] == llm.PROMPT_VERSION and r["trace"]["attempts"] == 1


def test_llm_repairs_invalid_output_once():
    bad = {"statement_type": "income_statement", "currency": "US Dollars"}  # no revenue/net_income, bad currency
    fake = FakeMessages([_tool_response(bad), _tool_response(GOOD, id_="t2")])
    r = extract_file(SAMPLES / "riverbend_income_statement_2025.pdf", mode="llm", client=fake)
    assert r["trace"]["attempts"] == 2
    repair_turn = fake.calls[1]["messages"][-1]["content"][0]
    assert repair_turn["type"] == "tool_result" and repair_turn["is_error"] is True


def test_llm_gives_up_after_bounded_repairs():
    bad = {"statement_type": "balance_sheet"}
    fake = FakeMessages([_tool_response(bad)] * 3)
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        extract_file(SAMPLES / "riverbend_balance_sheet_2025.pdf", mode="llm", client=fake)


def test_both_mode_flags_disagreement_between_llm_and_rules():
    wrong = {**GOOD, "revenue": {"value": 8468, "page": 2}}  # transposed digits
    fake = FakeMessages([_tool_response(wrong)])
    r = extract_file(SAMPLES / "riverbend_income_statement_2025.pdf", mode="both", client=fake)
    assert r["status"] == "needs_review"
    assert r["disagreements"][0]["field"] == "revenue"
