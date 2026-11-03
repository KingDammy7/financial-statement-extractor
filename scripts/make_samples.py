"""Generate fictional sample statements in samples/. All companies and figures are invented.

python scripts/make_samples.py
"""
from __future__ import annotations

import io
from pathlib import Path

from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)


def fmt(n: float) -> str:
    return f"({abs(n):,.0f})" if n < 0 else f"{n:,.0f}"


INCOME_CLEAN = [
    ("Revenue", None), ("Patient service revenue", 8_412), ("Other revenue", 236), ("Total revenue", 8_648),
    ("Cost of services", 4_905), ("Gross profit", 3_743),
    ("Operating expenses", None), ("Salaries and benefits (admin)", 1_310), ("Rent and occupancy", 402),
    ("General and administrative", 611), ("Total operating expenses", 2_323),
    ("Operating income", 1_420), ("Interest expense", (-88)), ("Income before taxes", 1_332),
    ("Income tax expense", (-293)), ("Net income", 1_039),
]


def statement_pdf(path: Path, company: str, title: str, period: str, units: str, rows, cover: bool = True):
    c = canvas.Canvas(str(path), pagesize=LETTER)
    w, h = LETTER
    if cover:
        c.setFont("Helvetica-Bold", 20); c.drawString(72, h - 140, company)
        c.setFont("Helvetica", 12)
        c.drawString(72, h - 170, "Financial statements prepared for diligence purposes")
        c.drawString(72, h - 188, "Fictional sample document. Not real data.")
        c.drawString(72, h - 230, "Contents: statement on page 2. Notes are not included in this sample.")
        c.showPage()
    c.setFont("Helvetica-Bold", 14); c.drawString(72, h - 72, company)
    c.setFont("Helvetica", 11); c.drawString(72, h - 90, title)
    c.drawString(72, h - 106, f"For the {period}" if not period.lower().startswith("as") else period.capitalize())
    c.drawString(72, h - 122, units)
    y = h - 160
    for label, val in rows:
        if val is None:
            c.setFont("Helvetica-Bold", 11); c.drawString(72, y, label)
        else:
            bold = label.lower().startswith(("total", "gross", "operating income", "net"))
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 11)
            c.drawString(90 if not bold else 72, y, label)
            c.drawRightString(w - 90, y, fmt(val))
        y -= 18
    c.showPage(); c.save()


def scanned_pdf(path: Path, lines: list[str]):
    """An image-only PDF, like a scan: no text layer at all, so OCR is required."""
    img = Image.new("L", (1700, 2200), 255)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 38)
    except OSError:
        font = ImageFont.load_default(size=38)
    y = 160
    for ln in lines:
        if "\t" in ln:
            label, num = ln.split("\t")
            d.text((150, y), label, fill=0, font=font)
            d.text((1500, y), num, fill=0, font=font, anchor="ra")
        else:
            d.text((150, y), ln, fill=0, font=font)
        y += 64
    img = img.rotate(0.4, fillcolor=255)  # slight skew, as scans have
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.drawImage(ImageReader(buf), 0, 0, width=LETTER[0], height=LETTER[1])
    c.showPage(); c.save()


def main():
    statement_pdf(OUT / "riverbend_income_statement_2025.pdf", "Riverbend Family Dermatology, PLLC (fictional)",
                  "Statement of Income", "year ended December 31, 2025", "(USD in thousands)", INCOME_CLEAN)

    statement_pdf(OUT / "riverbend_balance_sheet_2025.pdf", "Riverbend Family Dermatology, PLLC (fictional)",
                  "Balance Sheet", "as of December 31, 2025", "(USD in thousands)", [
                      ("Assets", None), ("Cash", 1_204), ("Patient accounts receivable, net", 1_377),
                      ("Equipment, net", 912), ("Right-of-use asset", 1_650), ("Total assets", 5_143),
                      ("Liabilities", None), ("Accounts payable", 318), ("Accrued payroll", 276),
                      ("Lease liability", 1_702), ("Term loan", 1_150), ("Total liabilities", 3_446),
                      ("Members' equity", None), ("Total members' equity", 1_697),
                  ], cover=False)

    # Same layout, but gross profit was keyed wrong (3,473 instead of 3,743): should be flagged.
    bad = [(l, 3_473 if l == "Gross profit" else v) for l, v in INCOME_CLEAN]
    statement_pdf(OUT / "northgate_income_statement_2025_typo.pdf", "Northgate Eye Associates, PC (fictional)",
                  "Statement of Income", "year ended December 31, 2025", "(USD in thousands)", bad, cover=False)

    scanned_pdf(OUT / "lakeside_income_statement_2025_scanned.pdf", [
        "Lakeside Pediatric Group, LLC (fictional)", "Statement of Income",
        "For the year ended December 31, 2025", "(USD in thousands)", "",
        "Total revenue\t5,120", "Cost of services\t2,960", "Gross profit\t2,160",
        "Total operating expenses\t1,402", "Operating income\t758", "Net income\t611",
    ])

    wb = Workbook(); ws = wb.active; ws.title = "P&L FY2025"
    ws.append(["Hillside Orthopedics, PC (fictional)"]); ws.append(["Statement of Income - year ended December 31, 2025"])
    ws.append(["USD in thousands"]); ws.append([])
    for label, v in [("Total revenue", 12_880), ("Cost of services", 7_215), ("Gross profit", 5_665),
                     ("Total operating expenses", 3_120), ("Operating income", 2_545), ("Net income", 1_902)]:
        ws.append([label, v])
    wb.save(OUT / "hillside_income_statement_2025.xlsx")
    print("Wrote samples to", OUT)


if __name__ == "__main__":
    main()
