import { useEffect, useState } from "react";
import demo from "./generated/demo-results.json";
import type { Check, Extraction } from "./reconcile.ts";

interface Result {
  file: string;
  extractor: string;
  status: string;
  extraction: Extraction;
  reconciliation: Check[];
  trace: Record<string, unknown>;
}

const results = demo as unknown as Result[];
const STATUS: Record<string, string> = { reconciled: "Reconciled", needs_review: "Needs review", unverified: "Unverified" };
const FIELDS = [
  ["revenue", "Revenue"], ["cost_of_revenue", "Cost of revenue"], ["gross_profit", "Gross profit"],
  ["operating_expenses", "Operating expenses"], ["operating_income", "Operating income"], ["net_income", "Net income"],
  ["total_assets", "Total assets"], ["total_liabilities", "Total liabilities"], ["total_equity", "Total equity"],
] as const;

const money = (n: number | null, cur = "USD") =>
  n === null ? "–" : new Intl.NumberFormat("en-US", { style: "currency", currency: cur, maximumFractionDigits: 0 }).format(n);
const scale = { units: 1, thousands: 1_000, millions: 1_000_000 } as const;

function ResultView({ r }: { r: Result }) {
  const x = r.extraction;
  const cur = x.currency ?? "USD";
  const [showJson, setShowJson] = useState(false);
  return (
    <div className="result">
      <div className="row">
        <div>
          <h2>{x.company_name ?? r.file}</h2>
          <p className="muted">
            {x.statement_type === "income_statement" ? "Income statement" : "Balance sheet"}
            {x.period_label ? ` · ${x.period_label}` : ""} · printed in {x.units ?? "units"} · extractor: {r.extractor}
            {Array.isArray(r.trace.ocr_pages) && (r.trace.ocr_pages as number[]).length > 0 ? " · OCR used" : ""}
          </p>
        </div>
        <span className={`pill ${r.status}`}>{STATUS[r.status] ?? r.status}</span>
      </div>

      <div className="cols">
        <table>
          <thead><tr><th>Field</th><th className="num">Value</th><th>Source</th></tr></thead>
          <tbody>
            {FIELDS.filter(([k]) => x[k]).map(([k, label]) => {
              const a = x[k]!;
              return (
                <tr key={k}>
                  <td>{label}</td>
                  <td className="num">{money(a.value * scale[x.units ?? "units"], cur)}</td>
                  <td className="muted small">{a.page ? `p.${a.page}` : ""} {a.label_in_doc ? `“${a.label_in_doc}”` : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div>
          <h3>Reconciliation</h3>
          <ul className="checks">
            {r.reconciliation.map((c) => (
              <li key={c.name} className={c.status}>
                <span className="mark" aria-hidden>{c.status === "pass" ? "✓" : c.status === "fail" ? "✕" : "–"}</span>
                <div>
                  <code>{c.formula}</code>
                  {c.status === "fail" && <div className="small">Expected {money(c.expected, cur)}, printed {money(c.actual, cur)} (off by {money(c.diff, cur)})</div>}
                  {c.status === "skipped" && <div className="small muted">Not enough fields to check</div>}
                </div>
              </li>
            ))}
          </ul>
          {x.notes && x.notes.length > 0 && <p className="small muted">{x.notes.join(" ")}</p>}
        </div>
      </div>
      <button className="ghost" onClick={() => setShowJson(!showJson)}>{showJson ? "Hide" : "Show"} raw JSON</button>
      {showJson && <pre>{JSON.stringify(r, null, 2)}</pre>}
    </div>
  );
}

export function App() {
  const [selected, setSelected] = useState(0);
  const [live, setLive] = useState<boolean | null>(null);
  const [liveResult, setLiveResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/extract").then((r) => r.json()).then((d) => setLive(Boolean(d.live))).catch(() => setLive(false));
  }, []);

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setBusy(true); setError(null); setLiveResult(null);
    const form = new FormData(); form.set("file", file);
    try {
      const res = await fetch("/api/extract", { method: "POST", body: form });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? `Failed (${res.status})`);
      setLiveResult(body as Result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const r = results[selected]!;
  return (
    <div className="shell">
      <header className="top">
        <strong>Financial Statement Extractor</strong>
        <a href="https://github.com/kingdammy7/financial-statement-extractor">Source on GitHub</a>
      </header>

      <section className="intro">
        <h1>From statement PDF to checked numbers</h1>
        <p>
          A Python pipeline reads income statements and balance sheets (PDF, scanned PDF or Excel). It extracts the
          figures into a strict JSON schema, then checks that they add up. Anything that doesn't is flagged for a
          person to review. All companies here are fictional.
        </p>
      </section>

      <section className="card">
        <h2 className="sr">Sample documents</h2>
        <div className="tabs" role="tablist">
          {results.map((s, i) => (
            <button key={s.file} role="tab" aria-selected={i === selected} className={i === selected ? "tab on" : "tab"} onClick={() => setSelected(i)}>
              <span className={`dot ${s.status}`} />{s.file.replace(/_/g, " ").replace(/\.(pdf|xlsx)$/, "")}
            </button>
          ))}
        </div>
        <p className="small muted">
          These results were produced by running the Python CLI over <code>samples/</code> in rules mode.{" "}
          <a href={`/samples/${r.file}`}>Download this document</a>
        </p>
        <ResultView r={r} />
      </section>

      <section className="card">
        <h2>Try your own PDF</h2>
        {live === null ? <p className="muted">Checking…</p> : live ? (
          <>
            <p className="muted">Uses Claude with a forced tool call, validates against the schema (up to two repair attempts), then reconciles. Text-layer PDFs only, 4 MB max, 5 per minute.</p>
            <label className="upload">{busy ? "Extracting…" : "Choose a PDF"}
              <input type="file" accept="application/pdf" disabled={busy} onChange={(e) => { void onUpload(e.target.files?.[0]); e.target.value = ""; }} />
            </label>
            {error && <p className="error">{error}</p>}
            {liveResult && <ResultView r={liveResult} />}
          </>
        ) : (
          <p className="muted">
            Live LLM mode is switched off on this deployment, so it can't spend the owner's API key. To run it yourself,
            clone the repo and run <code>fse extract your.pdf --mode llm</code> with <code>ANTHROPIC_API_KEY</code> set.
          </p>
        )}
      </section>

      <footer className="foot">Reference implementation by Damilola Ayodele, November 2026.</footer>
    </div>
  );
}
