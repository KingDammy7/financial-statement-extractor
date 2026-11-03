"""fse extract <files or folders> [--mode auto|llm|rules|both] [--out results.jsonl] [--csv summary.csv]"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .pipeline import extract_file
from .schema import BALANCE_FIELDS, INCOME_FIELDS

SUPPORTED = {".pdf", ".xlsx", ".xlsm", ".csv"}


def _collect(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for i in inputs:
        p = Path(i)
        files += sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED) if p.is_dir() else [p]
    return files


def _already_done(out: Path) -> set[str]:
    if not out.exists():
        return set()
    return {json.loads(line)["sha256"] for line in out.read_text().splitlines() if line.strip() and '"sha256"' in line}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="Extract and reconcile statements")
    ex.add_argument("inputs", nargs="+")
    ex.add_argument("--mode", choices=["auto", "llm", "rules", "both"], default="auto")
    ex.add_argument("--out", type=Path, help="Append results as JSON Lines (re-runs skip files already in it)")
    ex.add_argument("--csv", type=Path, help="Write a flat summary CSV")
    ex.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)

    files = _collect(args.inputs)
    done = _already_done(args.out) if args.out else set()
    todo = [f for f in files if hashlib.sha256(f.read_bytes()).hexdigest() not in done]
    if len(todo) < len(files):
        print(f"Skipping {len(files) - len(todo)} file(s) already in {args.out}", file=sys.stderr)

    def run(f: Path) -> dict:
        try:
            return extract_file(f, mode=args.mode)
        except Exception as e:  # one bad file must not sink the batch
            return {"file": f.name, "status": "error", "error": f"{type(e).__name__}: {e}"[:300]}

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(run, todo))

    if args.out:
        with args.out.open("a", encoding="utf-8") as fh:
            for r in results:
                if r.get("status") != "error":
                    fh.write(json.dumps(r) + "\n")
    if args.csv:
        cols = ["file", "status", "extractor", *INCOME_FIELDS, *BALANCE_FIELDS]
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in results:
                w.writerow({"file": r["file"], "status": r["status"], "extractor": r.get("extractor"), **r.get("normalised", {})})
    if not args.out and not args.csv:
        print(json.dumps(results if len(results) != 1 else results[0], indent=2))

    for r in results:
        print(f"{r['status']:>13}  {r['file']}", file=sys.stderr)
    return 1 if any(r["status"] == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
