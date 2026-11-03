from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal, Optional

from . import llm, rules
from .documents import chunk_pages, guess_statement_type, load, retrieve
from .reconcile import reconcile, summary
from .schema import BALANCE_FIELDS, INCOME_FIELDS, Extraction

Mode = Literal["auto", "llm", "rules", "both"]


def _cross_check(a: Extraction, b: Extraction) -> list[dict]:
    """Fields where the LLM and the rules disagree by more than 0.5%."""
    names = INCOME_FIELDS if a.statement_type == "income_statement" else BALANCE_FIELDS
    out = []
    for n in names:
        x, y = a.amount(n), b.amount(n)
        if x is not None and y is not None and abs(x - y) > max(1.0, 0.005 * max(abs(x), abs(y))):
            out.append({"field": n, "llm": x, "rules": y})
    return out


def extract_file(path: str | Path, mode: Mode = "auto", client: Optional[llm.MessagesClient] = None) -> dict:
    path = Path(path)
    pages = load(path)
    stype = guess_statement_type(pages)
    use_llm = mode in ("llm", "both") or (mode == "auto" and (client is not None or os.environ.get("ANTHROPIC_API_KEY")))

    trace: dict = {"pages": len(pages), "ocr_pages": [p.number for p in pages if p.ocr]}
    rules_result = rules.extract(pages) if mode in ("rules", "both") or not use_llm else None

    if use_llm:
        chunks = retrieve(chunk_pages(pages), stype)
        trace["chunks_sent"] = [{"page": c.page, "score": round(c.score, 1)} for c in chunks]
        result, llm_trace = llm.extract(chunks, stype, client=client)
        trace.update(llm_trace)
        used = "llm"
    else:
        assert rules_result is not None
        result, used = rules_result, "rules"

    checks = reconcile(result)
    out = {
        "file": path.name,
        # content hash, so re-running a batch can skip files already processed (idempotent batches)
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "extractor": used,
        "status": summary(checks),
        "extraction": result.model_dump(exclude_none=True),
        "normalised": {n: result.amount(n) for n in (INCOME_FIELDS + BALANCE_FIELDS) if result.amount(n) is not None},
        "reconciliation": [c.to_dict() for c in checks],
        "trace": trace,
    }
    if mode == "both" and rules_result is not None:
        out["disagreements"] = _cross_check(result, rules_result)
        if out["disagreements"]:
            out["status"] = "needs_review"
    return out
