import { runClassifier } from "./moderator.js";
import logger from "./logger.js";

// ─── Label normalisation ───────────────────────────────────────────────────────
// Accepts: 1/"1"/"harmful"/"hate"/"BLOCK"/"yes"/"true" → true (= should block)
//          0/"0"/"safe"/"ALLOW"/"no"/"false"            → false
export function normaliseLabel(raw) {
  if (raw === null || raw === undefined) return null;
  const s = String(raw).trim().toLowerCase();
  if (["1", "harmful", "hate", "block", "yes", "true", "hate_speech"].includes(s)) return true;
  if (["0", "safe", "allow", "no", "false", "not_hate_speech"].includes(s)) return false;
  return null;
}

// ─── CSV parser ───────────────────────────────────────────────────────────────
// Returns [{ [col]: value, ... }]. Handles quoted fields and \r\n.
export function parseCSV(text) {
  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  if (lines.length < 2) return [];
  const headers = splitCSVLine(lines[0]);
  return lines.slice(1)
    .filter(l => l.trim())
    .map(l => {
      const values = splitCSVLine(l);
      return Object.fromEntries(headers.map((h, i) => [h.trim(), (values[i] ?? "").trim()]));
    });
}

function splitCSVLine(line) {
  const fields = [];
  let cur = "";
  let inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuote && line[i + 1] === '"') { cur += '"'; i++; }
      else inQuote = !inQuote;
    } else if (ch === "," && !inQuote) {
      fields.push(cur); cur = "";
    } else {
      cur += ch;
    }
  }
  fields.push(cur);
  return fields;
}

// ─── Metrics ──────────────────────────────────────────────────────────────────
export function computeMetrics(rows, modelKey) {
  let tp = 0, fp = 0, tn = 0, fn = 0;
  for (const row of rows) {
    const truth = row.truth;
    const verdict = row.results[modelKey]?.verdict;
    if (verdict === undefined || truth === null) continue;
    const predicted = verdict === "BLOCK";
    if (truth && predicted)  tp++;
    else if (!truth && predicted) fp++;
    else if (!truth && !predicted) tn++;
    else if (truth && !predicted)  fn++;
  }
  const total = tp + fp + tn + fn;
  const accuracy  = total ? (tp + tn) / total : 0;
  const precision = (tp + fp) ? tp / (tp + fp) : 0;
  const recall    = (tp + fn) ? tp / (tp + fn) : 0;
  const f1 = (precision + recall) ? 2 * precision * recall / (precision + recall) : 0;
  return { tp, fp, tn, fn, accuracy, precision, recall, f1 };
}

// ─── Runner ───────────────────────────────────────────────────────────────────
// Calls onProgress({ done, total, modelKey, rowIndex }) after each classification.
// Returns rows with results filled in.
// interCallDelayMs: pause between every API call to stay well under rate limits.
export async function runBenchmark(rows, models, mode, blacklist, whitelist, customInstructions, onProgress, interCallDelayMs = 500) {
  // Count already-completed pairs (for resume — rows may have partial results)
  const alreadyDone = rows.reduce((n, row) =>
    n + models.filter(m => row.results[m.key] !== undefined).length, 0);
  const total = rows.length * models.length;
  let done = alreadyDone;

  for (const row of rows) {
    for (const model of models) {
      // Skip pairs already completed in a previous (interrupted) run
      if (row.results[model.key] !== undefined) {
        done++;
        onProgress({ done, total, modelKey: model.key, rowIndex: rows.indexOf(row) });
        continue;
      }
      const t0 = Date.now();
      try {
        const result = await runClassifier(model, row.text, mode, blacklist, whitelist, customInstructions, "input");
        row.results[model.key] = { ...result, latencyMs: Date.now() - t0 };
      } catch (err) {
        row.results[model.key] = {
          verdict: "ERROR",
          confidence: 0,
          reason: err.message || "Classification failed",
          category: "error",
          latencyMs: Date.now() - t0,
        };
      }
      done++;
      logger.mod("benchmark progress:", done, "/", total, model.key);
      onProgress({ done, total, modelKey: model.key, rowIndex: rows.indexOf(row) });
      if (done < total) await new Promise(r => setTimeout(r, interCallDelayMs));
    }
  }
  return rows;
}

// ─── CSV export ───────────────────────────────────────────────────────────────
export function exportResultsCSV(rows, models, promptConfig) {
  const escape = v => `"${String(v ?? "").replace(/"/g, '""')}"`;

  // Prompt metadata columns (same for every row — repeated for self-contained rows)
  const promptCols = promptConfig ? [
    "prompt_mode",
    "prompt_blacklist",
    "prompt_whitelist",
    "prompt_custom_instructions",
    "prompt_system_prompt",
  ] : [];

  // Per-model result columns + per-row prompt column (for models that embed text in prompt)
  const modelCols = models.flatMap(m => [
    `${m.key}_verdict`,
    `${m.key}_confidence`,
    `${m.key}_reason`,
    `${m.key}_latency_ms`,
    `${m.key}_prompt_used`,
  ]);

  const headers = ["text", "truth", "source", ...promptCols, ...modelCols];

  const lines = [
    headers.join(","),
    ...rows.map(row => [
      escape(row.text),
      row.truth === true ? "harmful" : row.truth === false ? "safe" : "",
      escape(row.source ?? ""),
      ...(promptConfig ? [
        escape(promptConfig.mode ?? ""),
        escape((promptConfig.blacklist ?? []).join("; ")),
        escape((promptConfig.whitelist ?? []).join("; ")),
        escape(promptConfig.customInstructions ?? ""),
        escape(promptConfig.renderedSystemPrompt ?? ""),
      ] : []),
      ...models.flatMap(m => {
        const r = row.results[m.key] ?? {};
        const p = r.promptUsed;
        const promptStr = p
          ? (p.rawPrompt ?? p.userMessage ?? (p.type === "moderation-api" ? `[moderation-api] ${p.input ?? ""}` : ""))
          : "";
        return [
          escape(r.verdict ?? ""),
          escape(r.confidence ?? ""),
          escape(r.reason ?? ""),
          escape(r.latencyMs ?? ""),
          escape(promptStr),
        ];
      }),
    ].join(",")),
  ];
  return lines.join("\n");
}
