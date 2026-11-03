/**
 * TypeScript port of fse/reconcile.py for the live demo function.
 * tests/reconcile.test.ts runs it against the Python outputs in demo-results.json,
 * so the two implementations can't quietly drift apart.
 */
export interface Amount { value: number; page?: number; label_in_doc?: string }
export interface Extraction {
  company_name?: string;
  statement_type: "income_statement" | "balance_sheet";
  period_label?: string;
  period_end?: string;
  currency?: string;
  units?: "units" | "thousands" | "millions";
  revenue?: Amount; cost_of_revenue?: Amount; gross_profit?: Amount; operating_expenses?: Amount;
  operating_income?: Amount; net_income?: Amount;
  total_assets?: Amount; total_liabilities?: Amount; total_equity?: Amount;
  notes?: string[];
}
export interface Check {
  name: string; formula: string; expected: number | null; actual: number | null;
  status: "pass" | "fail" | "skipped"; diff: number | null;
}

const MULT = { units: 1, thousands: 1_000, millions: 1_000_000 } as const;
type Field = Exclude<keyof Extraction, "company_name" | "statement_type" | "period_label" | "period_end" | "currency" | "units" | "notes">;

export const amount = (x: Extraction, f: Field): number | null => {
  const a = x[f];
  return a ? a.value * MULT[x.units ?? "units"] : null;
};

const check = (name: string, formula: string, expected: number | null, actual: number | null, tol: number): Check => {
  if (expected === null || actual === null) return { name, formula, expected, actual, status: "skipped", diff: null };
  const allowed = Math.max(1, tol * Math.max(Math.abs(expected), Math.abs(actual)));
  const diff = Math.round((actual - expected) * 100) / 100;
  return { name, formula, expected, actual, status: Math.abs(actual - expected) <= allowed ? "pass" : "fail", diff };
};
const bound = (name: string, formula: string, limit: number | null, actual: number | null): Check =>
  limit === null || actual === null
    ? { name, formula, expected: limit, actual, status: "skipped", diff: null }
    : { name, formula, expected: limit, actual, status: actual <= limit ? "pass" : "fail", diff: Math.round((actual - limit) * 100) / 100 };
const sub = (a: number | null, b: number | null) => (a === null || b === null ? null : a - b);
const add = (a: number | null, b: number | null) => (a === null || b === null ? null : a + b);

export function reconcile(x: Extraction, tol = 0.005): Check[] {
  const a = (f: Field) => amount(x, f);
  if (x.statement_type === "income_statement") {
    return [
      check("gross_profit", "revenue - cost_of_revenue", sub(a("revenue"), a("cost_of_revenue")), a("gross_profit"), tol),
      check("operating_income", "gross_profit - operating_expenses", sub(a("gross_profit"), a("operating_expenses")), a("operating_income"), tol),
      bound("net_income_within_revenue", "net_income <= revenue", a("revenue"), a("net_income")),
    ];
  }
  return [check("balance", "total_liabilities + total_equity = total_assets", add(a("total_liabilities"), a("total_equity")), a("total_assets"), tol)];
}

export function summary(checks: Check[]): "reconciled" | "needs_review" | "unverified" {
  if (checks.some((c) => c.status === "fail")) return "needs_review";
  if (checks.every((c) => c.status === "skipped")) return "unverified";
  return "reconciled";
}
