"""Turn PDFs and spreadsheets into page text, with OCR for scanned pages, then
pick the chunks worth sending to the model."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

MIN_TEXT_CHARS = 40  # below this a PDF page is treated as scanned and OCR'd


@dataclass
class Page:
    number: int  # 1-based
    text: str
    ocr: bool = False


def load(path: str | Path) -> list[Page]:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(p)
    if suffix in (".xlsx", ".xlsm"):
        return _load_xlsx(p)
    if suffix == ".csv":
        return [Page(1, _rows_to_text(csv.reader(io.StringIO(p.read_text(encoding="utf-8-sig")))))]
    raise ValueError(f"Unsupported file type: {suffix}")


def _load_pdf(path: Path) -> list[Page]:
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=True) or ""
            if len(text.strip()) >= MIN_TEXT_CHARS:
                pages.append(Page(i, text))
            else:
                pages.append(Page(i, _ocr(page), ocr=True))
    return pages


def _ocr(page) -> str:
    try:
        import pytesseract
    except ImportError as e:  # pragma: no cover - depends on optional extra
        raise RuntimeError("Scanned page found. Install the 'ocr' extra and Tesseract to read it.") from e
    image = page.to_image(resolution=300).original
    return pytesseract.image_to_string(image, config="--psm 6")


def _load_xlsx(path: Path) -> list[Page]:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    return [Page(i, f"[sheet: {ws.title}]\n" + _rows_to_text(ws.iter_rows(values_only=True)))
            for i, ws in enumerate(wb.worksheets, start=1)]


def _rows_to_text(rows) -> str:
    lines = []
    for row in rows:
        cells = ["" if c is None else str(c) for c in row]
        if any(cells):
            lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


# --- chunking and retrieval -------------------------------------------------

KEYWORDS = {
    "income_statement": ["revenue", "sales", "cost of", "gross profit", "operating", "expenses", "net income",
                         "net loss", "profit", "ebitda", "income statement", "profit and loss", "p&l"],
    "balance_sheet": ["total assets", "liabilities", "equity", "balance sheet", "cash", "receivable",
                      "payable", "retained earnings", "financial position"],
}


@dataclass
class Chunk:
    page: int
    text: str
    score: float = 0.0


def chunk_pages(pages: list[Page], max_lines: int = 60, overlap: int = 8) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in pages:
        lines = p.text.splitlines()
        step = max_lines - overlap
        for start in range(0, max(1, len(lines)), step):
            body = "\n".join(lines[start:start + max_lines]).strip()
            if body:
                chunks.append(Chunk(p.number, body))
            if start + max_lines >= len(lines):
                break
    return chunks


def retrieve(chunks: list[Chunk], statement_type: str, k: int = 4) -> list[Chunk]:
    """Keyword scoring with a bonus for chunks dense in numbers. Cheap, explainable,
    and good enough to keep a 40-page pack under the model's context budget.
    Swap for embeddings when documents get less formulaic."""
    terms = KEYWORDS[statement_type]
    for c in chunks:
        low = c.text.lower()
        hits = sum(low.count(t) for t in terms)
        numbers = len(re.findall(r"\(?-?[\d,]{3,}(?:\.\d+)?\)?", c.text))
        c.score = hits * 2 + min(numbers, 40) * 0.25
    ranked = sorted(chunks, key=lambda c: c.score, reverse=True)[:k]
    return sorted(ranked, key=lambda c: c.page)


def guess_statement_type(pages: list[Page]) -> str:
    text = " ".join(p.text.lower() for p in pages)
    bs = sum(text.count(t) for t in KEYWORDS["balance_sheet"])
    inc = sum(text.count(t) for t in KEYWORDS["income_statement"])
    return "balance_sheet" if bs > inc else "income_statement"
