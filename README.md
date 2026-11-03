# Financial Statement Extractor

**Live demo:** https://statement-extractor-dami.netlify.app

This tool reads income statements and balance sheets in PDF, scanned PDF, Excel or CSV form. It extracts the key figures into a strict JSON schema, then checks the arithmetic. If a number doesn't add up, or the LLM and the rule-based reader disagree, the file is marked for human review instead of being trusted.

I built it in November 2026 as a reference implementation of the target-analysis step in practice acquisitions: a seller sends financials, and the deal team needs consistent, checked numbers. The companies in `samples/` are fictional.

## Why it is built this way

The model reads the documents, but code decides whether the result can be trusted:

1. **Forced tool call against a schema.** Claude has to call `record_statement`, and that tool's `input_schema` is the Pydantic `Extraction` model (`fse/schema.py`). Prose answers aren't accepted.
2. **Validation and a bounded repair loop.** Pydantic validates the output. If validation fails, the error goes back to the model as an `is_error` tool result, at most twice. After that the file fails loudly rather than being half-trusted.
3. **Reconciliation.** `fse/reconcile.py` checks that revenue − cost of revenue = gross profit, that gross profit − opex = operating income, that net income ≤ revenue, and that assets = liabilities + equity.
4. **Cross-checking.** `--mode both` runs the LLM and the rules extractor and flags any field where they differ by more than 0.5%.
5. **Traceability.** Every figure records the page it came from and the label printed next to it. Every run records the prompt version, the model, the number of attempts and any repair errors.

## Pipeline

```
file ─► documents.load()            PDF text layer (pdfplumber), OCR for scanned pages (Tesseract), xlsx/csv
     ─► chunk_pages() + retrieve()  60-line chunks, keyword + number-density scoring, top-k pages sent
     ─► llm.extract()               Claude, tool_choice forced, temperature 0, prompts/extract_v1.md
        or rules.extract()          deterministic fallback when no API key is set (or as a cross-check)
     ─► reconcile()                 arithmetic checks ─► status: reconciled | needs_review | unverified
```

Retrieval is plain keyword scoring for now: the results are easy to explain, and it keeps a 40-page financial pack inside a small context budget. For less formulaic documents, the next step is embeddings.

## Use it

```bash
pip install -e ".[dev]"            # needs Tesseract for scanned PDFs: brew install tesseract / apt install tesseract-ocr
python scripts/make_samples.py     # regenerate the fictional sample documents
pytest -q                          # 19 tests, no network: the LLM path runs against a fake client

fse extract samples/ --mode rules --csv out/summary.csv
export ANTHROPIC_API_KEY=...       # read from the environment only, never logged or written out
fse extract samples/ --mode both --out out/results.jsonl
```

Batch runs are idempotent. `--out` appends JSON Lines keyed by each file's SHA-256, so running the command again only processes new files. If one file fails, it's reported and the rest of the batch carries on.

Sample output (rules mode) for the file with the deliberate typo:

```json
{
  "file": "northgate_income_statement_2025_typo.pdf",
  "status": "needs_review",
  "reconciliation": [
    { "name": "gross_profit", "formula": "revenue - cost_of_revenue",
      "expected": 3743000.0, "actual": 3473000.0, "status": "fail", "diff": -270000.0 }
  ]
}
```

## The web demo (`web/`)

This is a React + TypeScript page on Netlify. It shows the CLI's real output for each sample file, which `scripts/export_web_assets.py` writes into `web/src/generated/`.

There's also a live mode: `netlify/functions/extract.mts` sends an uploaded PDF to Claude, using the same schema and prompt that the export script copies across. Live mode only switches on when the site owner sets `ANTHROPIC_API_KEY` in Netlify, and it's limited to 5 requests per minute so the key can't be drained.

The TypeScript reconciliation is a port of the Python version. Its tests run it against the Python outputs, so the two implementations can't quietly drift apart. CI also fails if the schema or prompt in the web demo falls out of sync with the engine.

## What I'd do next

- Add cash flow statements and extract multiple periods (year-on-year columns).
- Build an evaluation set of real (redacted) statements with hand-labelled answers, and track field-level accuracy for each prompt version.
- Take the files straight from the data room (see [dataroom-tracker](https://github.com/kingdammy7/dataroom-tracker)) once a room is complete.
- Run the model through Azure OpenAI or Claude on a cloud provider when the data has to stay inside a tenant boundary.
