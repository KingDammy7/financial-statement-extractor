import { describe, expect, it } from "vitest";
import demo from "../src/generated/demo-results.json";
import { reconcile, summary, type Extraction } from "../src/reconcile.ts";
import { validateExtraction } from "../netlify/functions/_lib/validate.ts";

describe("TypeScript reconcile matches the Python engine", () => {
  for (const r of demo) {
    it(r.file, () => {
      const checks = reconcile(r.extraction as Extraction);
      expect(checks.map((c) => [c.name, c.status])).toEqual(r.reconciliation.map((c) => [c.name, c.status]));
      expect(summary(checks)).toBe(r.status);
    });
  }
});

describe("validateExtraction", () => {
  it("accepts a demo result", () => {
    expect(validateExtraction(demo[0]!.extraction).ok).toBe(true);
  });
  it("rejects missing core fields, bad currency and non-numeric values", () => {
    const bad = validateExtraction({ statement_type: "balance_sheet", currency: "dollars", total_equity: { value: "12" } });
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.errors.join(" ")).toMatch(/total_assets.*currency|currency.*total_assets/s);
  });
});
