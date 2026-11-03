import type { Extraction } from "../../../src/reconcile.ts";

const AMOUNT_FIELDS = [
  "revenue", "cost_of_revenue", "gross_profit", "operating_expenses", "operating_income", "net_income",
  "total_assets", "total_liabilities", "total_equity",
] as const;

/** Mirrors the Pydantic rules in fse/schema.py that matter for the demo. */
export function validateExtraction(raw: unknown): { ok: true; value: Extraction } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  if (typeof raw !== "object" || raw === null) return { ok: false, errors: ["not an object"] };
  const x = raw as Record<string, unknown>;

  if (x.statement_type !== "income_statement" && x.statement_type !== "balance_sheet") errors.push("statement_type invalid");
  if (x.units !== undefined && !["units", "thousands", "millions"].includes(String(x.units))) errors.push("units invalid");
  if (typeof x.currency === "string") x.currency = x.currency.toUpperCase();
  if (x.currency !== undefined && !/^[A-Z]{3}$/.test(String(x.currency))) errors.push("currency must be ISO 4217");
  if (x.period_end !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(String(x.period_end))) errors.push("period_end must be YYYY-MM-DD");

  for (const f of AMOUNT_FIELDS) {
    const a = x[f] as { value?: unknown; page?: unknown } | undefined;
    if (a === undefined || a === null) { delete x[f]; continue; }
    if (typeof a.value !== "number" || !Number.isFinite(a.value)) errors.push(`${f}.value must be a number`);
    if (a.page !== undefined && (!Number.isInteger(a.page) || (a.page as number) < 1)) errors.push(`${f}.page must be >= 1`);
  }
  if (x.statement_type === "income_statement" && !x.revenue && !x.net_income) errors.push("income_statement needs revenue or net_income");
  if (x.statement_type === "balance_sheet" && !x.total_assets) errors.push("balance_sheet needs total_assets");

  return errors.length ? { ok: false, errors } : { ok: true, value: x as unknown as Extraction };
}
