import type { Config } from "@netlify/functions";
import { extractText, getDocumentProxy } from "unpdf";
import schema from "../../src/generated/schema.json";
import { PROMPT_TEMPLATE, PROMPT_VERSION } from "../../src/generated/prompt.ts";
import { reconcile, summary } from "../../src/reconcile.ts";
import { validateExtraction } from "./_lib/validate.ts";

/**
 * Live mode for the demo: PDF text layer -> Claude forced tool call -> validate -> reconcile.
 * Off unless the site owner sets ANTHROPIC_API_KEY. Scanned PDFs (no text layer)
 * are refused here; the Python CLI handles them with OCR.
 */
const TOOL = "record_statement";
const MAX_BYTES = 4 * 1024 * 1024;
const MAX_CHARS = 24_000;

const json = (body: unknown, status = 200) => Response.json(body, { status });

async function callClaude(apiKey: string, model: string, messages: unknown[]) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify({
        model, max_tokens: 2048, temperature: 0,
        tools: [{ name: TOOL, description: "Record the extracted statement fields.", input_schema: schema }],
        tool_choice: { type: "tool", name: TOOL },
        messages,
      }),
    });
    if (res.ok) return (await res.json()) as { content: { type: string; name?: string; id?: string; input?: unknown }[] };
    if (res.status !== 429 && res.status < 500) throw new Error(`Model API error ${res.status}`);
    await new Promise((r) => setTimeout(r, 400 * 2 ** (attempt - 1)));
  }
  throw new Error("Model API unavailable after retries");
}

export default async (req: Request) => {
  const apiKey = Netlify.env.get("ANTHROPIC_API_KEY");
  if (req.method === "GET") return json({ live: Boolean(apiKey), promptVersion: PROMPT_VERSION });
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);
  if (!apiKey) return json({ error: "Live mode is off on this deployment. Browse the sample results instead." }, 503);

  const form = await req.formData().catch(() => null);
  const file = form?.get("file");
  if (!(file instanceof File) || file.type !== "application/pdf") return json({ error: "Upload a PDF" }, 400);
  if (file.size > MAX_BYTES) return json({ error: "Max 4 MB" }, 413);

  const pdf = await getDocumentProxy(new Uint8Array(await file.arrayBuffer()));
  const { text: pages } = await extractText(pdf, { mergePages: false });
  if (pages.join("").trim().length < 40) {
    return json({ error: "This PDF has no text layer (probably a scan). OCR runs in the Python CLI, not in this demo." }, 422);
  }

  const lower = pages.join(" ").toLowerCase();
  const stype = (lower.match(/total assets|liabilities|balance sheet/g)?.length ?? 0) >
    (lower.match(/revenue|gross profit|net income|operating/g)?.length ?? 0) ? "balance_sheet" : "income_statement";
  let excerpts = pages.map((t, i) => `--- page ${i + 1} ---\n${t}`).join("\n\n");
  const truncated = excerpts.length > MAX_CHARS;
  excerpts = excerpts.slice(0, MAX_CHARS);

  const model = Netlify.env.get("FSE_MODEL") ?? "claude-sonnet-4-5";
  const messages: unknown[] = [{ role: "user", content: PROMPT_TEMPLATE.replace("{{statement_type}}", stype).replace("{{excerpts}}", excerpts) }];
  const repairs: string[] = [];

  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await callClaude(apiKey, model, messages);
    const call = res.content.find((b) => b.type === "tool_use" && b.name === TOOL);
    const v = validateExtraction(call?.input);
    if (v.ok) {
      const checks = reconcile(v.value);
      return json({
        file: file.name.slice(0, 120), extractor: "llm", status: summary(checks), extraction: v.value,
        reconciliation: checks, trace: { model, prompt_version: PROMPT_VERSION, attempts: attempt, repairs, pages: pages.length, truncated },
      });
    }
    repairs.push(v.errors.join("; "));
    messages.push({ role: "assistant", content: res.content });
    messages.push({ role: "user", content: call?.id
      ? [{ type: "tool_result", tool_use_id: call.id, is_error: true, content: `Validation failed: ${repairs.at(-1)}. Call ${TOOL} again.` }]
      : `Call ${TOOL}. Previous error: ${repairs.at(-1)}` });
  }
  return json({ error: "Model output failed validation 3 times", repairs }, 502);
};

export const config: Config = {
  path: "/api/extract",
  // protects the owner's API key from being drained by one visitor
  rateLimit: { windowLimit: 5, windowSize: 60, aggregateBy: ["ip", "domain"] },
};
