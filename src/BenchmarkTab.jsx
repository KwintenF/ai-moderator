import { useState, useEffect, useRef } from "react";
import { MODERATOR_MODELS, buildClassifierPrompt } from "./moderator.js";
import {
  normaliseLabel, parseCSV,
  runBenchmark, computeMetrics, exportResultsCSV,
} from "./benchmarkRunner.js";
import { PRESETS } from "./presets.js";

const STORAGE_KEY  = "benchmark_results_v1";
const PROGRESS_KEY = "benchmark_progress_v1";
const ETHOS_PATH   = "/input-data/ethos_binary.json";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pct(n) { return (n * 100).toFixed(1) + "%"; }
function fmt(n)  { return typeof n === "number" ? n.toFixed(3) : "—"; }

function MetricBar({ value, color = "violet" }) {
  const colors = {
    violet: "bg-violet-500",
    emerald: "bg-emerald-500",
    amber: "bg-amber-500",
    red: "bg-red-500",
  };
  return (
    <div className="w-full bg-slate-800 rounded-full h-1 mt-0.5">
      <div className={`${colors[color]} h-1 rounded-full transition-all`} style={{ width: pct(value) }} />
    </div>
  );
}

function ModelCheckbox({ model, checked, onChange }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer group">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="accent-violet-500 cursor-pointer"
      />
      <span className="text-[11px] text-slate-300 group-hover:text-slate-100 transition-colors">
        {model.label}
      </span>
      <span className="text-[9px] text-slate-600">{model.provider}</span>
    </label>
  );
}

// ─── BenchmarkTab ─────────────────────────────────────────────────────────────

export default function BenchmarkTab({ mode: propMode, blacklist: propBlacklist, whitelist: propWhitelist, customInstructions: propCustomInstructions }) {
  // ── local prompt config (independent from main app, presets override this)
  const [mode, setMode]                       = useState(propMode);
  const [blacklist, setBlacklist]             = useState(propBlacklist);
  const [whitelist, setWhitelist]             = useState(propWhitelist);
  const [customInstructions, setCustomInstructions] = useState(propCustomInstructions);
  const [activePresetId, setActivePresetId]   = useState(null);

  const applyPreset = (presetId) => {
    const preset = PRESETS.find(p => p.id === presetId);
    if (!preset) return;
    setMode(preset.mode);
    setBlacklist(preset.blacklist);
    setWhitelist(preset.whitelist);
    setCustomInstructions(preset.customInstructions);
    setActivePresetId(presetId);
  };

  // ── dataset state
  const [datasetSource, setDatasetSource] = useState("ethos"); // "ethos" | "csv"
  const [rawRows, setRawRows]  = useState([]);     // parsed but unrun rows
  const [csvError, setCsvError] = useState("");
  const [csvColumns, setCsvColumns] = useState({ text: "", label: "" });
  const [csvHeaders, setCsvHeaders] = useState([]);
  const [csvParsed, setCsvParsed] = useState([]);  // raw CSV objects before column mapping

  const [sampleSize, setSampleSize] = useState(50);

  // ── model selection
  const [selectedKeys, setSelectedKeys] = useState(
    MODERATOR_MODELS.slice(0, 2).map(m => m.key)
  );

  // ── run state
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const abortRef = useRef(false);

  // ── interrupted run detection
  const [interrupted, setInterrupted] = useState(() => {
    try {
      const saved = localStorage.getItem(PROGRESS_KEY);
      return saved ? JSON.parse(saved) : null;
    } catch { return null; }
  });

  // ── results (persisted to localStorage)
  const [results, setResults] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? JSON.parse(saved) : null;
    } catch { return null; }
  });

  // persist whenever results change
  useEffect(() => {
    if (results) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(results)); } catch {}
    }
  }, [results]);

  // ── load ETHOS on mount / when source switches to ethos
  useEffect(() => {
    if (datasetSource !== "ethos") return;
    fetch(ETHOS_PATH)
      .then(r => r.json())
      .then(data => {
        setRawRows(data.map(d => ({
          text:   d.text,
          truth:  normaliseLabel(d.label),
          source: "ethos",
        })));
        setCsvError("");
      })
      .catch(() => setCsvError("Failed to load ETHOS dataset from /input-data/ethos_binary.json"));
  }, [datasetSource]);

  // ── CSV upload
  const handleCSVUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const parsed = parseCSV(ev.target.result);
        if (!parsed.length) { setCsvError("CSV appears empty"); return; }
        setCsvParsed(parsed);
        const headers = Object.keys(parsed[0]);
        setCsvHeaders(headers);
        // auto-detect common column names
        const textCol  = headers.find(h => /text|comment|post|content|message/i.test(h)) ?? headers[0];
        const labelCol = headers.find(h => /label|hate|harm|toxic|class|target/i.test(h)) ?? headers[1] ?? "";
        setCsvColumns({ text: textCol, label: labelCol });
        setCsvError("");
      } catch (err) {
        setCsvError("Failed to parse CSV: " + err.message);
      }
    };
    reader.readAsText(file);
  };

  // apply column mapping when user confirms
  const applyCSVMapping = () => {
    if (!csvColumns.text || !csvColumns.label) { setCsvError("Select both text and label columns"); return; }
    const rows = csvParsed.map(r => ({
      text:   r[csvColumns.text] ?? "",
      truth:  normaliseLabel(r[csvColumns.label]),
      source: "csv",
    })).filter(r => r.text);
    setRawRows(rows);
    setCsvError("");
  };

  const selectedModels = MODERATOR_MODELS.filter(m => selectedKeys.includes(m.key));

  // sample: take evenly from both classes for a balanced sample
  const getSample = () => {
    const harmful = rawRows.filter(r => r.truth === true);
    const safe    = rawRows.filter(r => r.truth === false);
    const n = Math.min(sampleSize, rawRows.length);
    const half = Math.floor(n / 2);
    const shuffle = arr => [...arr].sort(() => Math.random() - 0.5);
    return [
      ...shuffle(harmful).slice(0, half),
      ...shuffle(safe).slice(0, n - half),
    ].sort(() => Math.random() - 0.5);
  };

  const startRun = async (rows, models, runMeta) => {
    abortRef.current = false;
    setRunning(true);
    setProgress({ done: 0, total: 0 });
    setInterrupted(null);

    const saveProgress = (p) => {
      try {
        localStorage.setItem(PROGRESS_KEY, JSON.stringify({
          rows,
          ...runMeta,
          done: p.done,
          total: p.total,
        }));
      } catch {}
    };

    let completed;
    try {
      completed = await runBenchmark(
        rows, models,
        runMeta.promptConfig.mode,
        runMeta.promptConfig.blacklist,
        runMeta.promptConfig.whitelist,
        runMeta.promptConfig.customInstructions,
        (p) => {
          setProgress(p);
          saveProgress(p);
          if (abortRef.current) throw new Error("Aborted");
        }
      );
    } catch (err) {
      // "Aborted" is expected when the user clicks Stop — leave progress for resume.
      // Any other error is unexpected: log it so it's visible in the console.
      if (err?.message !== "Aborted") console.error("Benchmark run failed:", err);
      setRunning(false);
      return;
    }

    // Completed — promote to final results and clear progress
    setResults({ rows: completed, ...runMeta });
    localStorage.removeItem(PROGRESS_KEY);
    setRunning(false);
  };

  const handleRun = () => {
    if (!selectedModels.length) return;
    const promptConfig = {
      mode,
      blacklist: [...blacklist],
      whitelist: [...whitelist],
      customInstructions,
      renderedSystemPrompt: buildClassifierPrompt(mode, blacklist, whitelist, customInstructions, "input"),
    };
    const runMeta = {
      models: selectedModels.map(m => ({ key: m.key, label: m.label, provider: m.provider })),
      startedAt: new Date().toISOString(),
      dataset: datasetSource,
      promptConfig,
    };
    // Clear any stale interrupted run before starting fresh
    localStorage.removeItem(PROGRESS_KEY);
    const sample = getSample().map(r => ({ ...r, results: {} }));
    startRun(sample, selectedModels, runMeta);
  };

  const handleResume = () => {
    if (!interrupted) return;
    const models = interrupted.models.map(m => MODERATOR_MODELS.find(x => x.key === m.key) ?? m);
    startRun(interrupted.rows, models, {
      models: interrupted.models,
      startedAt: interrupted.startedAt,
      dataset: interrupted.dataset,
      promptConfig: interrupted.promptConfig,
    });
  };

  const handleExport = () => {
    if (!results) return;
    const modelObjs = results.models.map(m => MODERATOR_MODELS.find(x => x.key === m.key) ?? m);
    const csv = exportResultsCSV(results.rows, modelObjs, results.promptConfig);
    const ts  = new Date(results.startedAt).toISOString().slice(0, 16).replace(/[T:]/g, "-");
    const a   = document.createElement("a");
    a.href    = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `benchmark_${ts}.csv`;
    a.click();
  };

  const verdictIcon = (row, modelKey) => {
    const r = row.results[modelKey];
    if (!r) return <span className="text-slate-700">·</span>;
    if (r.verdict === "ERROR") return (
      <span className="text-amber-500 text-[10px]" title={r.reason ?? ""}>
        ERR
        {r.reason && (
          <span className="block text-[8px] text-amber-600/80 max-w-[120px] truncate leading-tight">
            {r.reason}
          </span>
        )}
      </span>
    );
    const predicted = r.verdict === "BLOCK";
    const correct   = predicted === row.truth;
    return correct
      ? <span className="text-emerald-400">✓</span>
      : <span className="text-red-400">✗</span>;
  };

  const metrics = results
    ? Object.fromEntries(
        results.models.map(m => [m.key, computeMetrics(results.rows, m.key)])
      )
    : {};

  return (
    <div className="flex min-h-screen">
      {/* ── Left config panel ── */}
      <div className="w-64 shrink-0 border-r border-slate-800/50 p-4 space-y-5 overflow-y-auto">

        {/* Preset */}
        <div>
          <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-2">Prompt preset</p>
          <div className="space-y-1">
            {PRESETS.map(p => (
              <button key={p.id} onClick={() => applyPreset(p.id)}
                title={p.description}
                className={`w-full text-left px-2 py-1.5 rounded text-[10px] transition-colors border ${
                  activePresetId === p.id
                    ? "bg-violet-600/20 border-violet-500/50 text-violet-300"
                    : "border-slate-700/50 text-slate-400 hover:text-slate-200 hover:border-slate-600"
                }`}>
                {p.name}
              </button>
            ))}
          </div>
          {activePresetId && (
            <p className="text-[9px] text-slate-600 mt-1.5 leading-snug">
              {PRESETS.find(p => p.id === activePresetId)?.description}
            </p>
          )}
        </div>

        {/* Dataset */}
        <div>
          <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-2">Dataset</p>
          <div className="flex gap-2 mb-3">
            {["ethos", "csv"].map(s => (
              <button key={s} onClick={() => setDatasetSource(s)}
                className={`flex-1 py-1.5 rounded text-[10px] uppercase tracking-wider transition-colors border ${
                  datasetSource === s
                    ? "bg-violet-600/20 border-violet-500/50 text-violet-300"
                    : "border-slate-700/50 text-slate-500 hover:text-slate-300"
                }`}>
                {s === "ethos" ? "ETHOS" : "Upload CSV"}
              </button>
            ))}
          </div>

          {datasetSource === "ethos" && rawRows.length > 0 && (
            <p className="text-[10px] text-slate-500">
              {rawRows.length} rows loaded &mdash; {rawRows.filter(r => r.truth).length} harmful,{" "}
              {rawRows.filter(r => !r.truth).length} safe
            </p>
          )}

          {datasetSource === "csv" && (
            <div className="space-y-2">
              <input type="file" accept=".csv" onChange={handleCSVUpload}
                className="w-full text-[10px] text-slate-400 file:mr-2 file:text-[9px] file:bg-slate-800 file:border file:border-slate-700 file:rounded file:px-2 file:py-1 file:text-slate-300 file:cursor-pointer" />
              {csvHeaders.length > 0 && (
                <div className="space-y-1.5">
                  {["text", "label"].map(col => (
                    <div key={col}>
                      <p className="text-[9px] text-slate-600 mb-0.5">{col} column</p>
                      <select value={csvColumns[col]} onChange={e => setCsvColumns(p => ({ ...p, [col]: e.target.value }))}
                        className="w-full bg-slate-900/60 border border-slate-700/50 rounded px-2 py-1 text-[10px] text-slate-300">
                        <option value="">— select —</option>
                        {csvHeaders.map(h => <option key={h} value={h}>{h}</option>)}
                      </select>
                    </div>
                  ))}
                  <button onClick={applyCSVMapping}
                    className="w-full py-1.5 bg-slate-700/40 hover:bg-slate-700/60 rounded text-[10px] text-slate-300 transition-colors">
                    Apply mapping
                  </button>
                  {rawRows.length > 0 && (
                    <p className="text-[10px] text-slate-500">{rawRows.length} rows mapped</p>
                  )}
                </div>
              )}
            </div>
          )}

          {csvError && <p className="text-[10px] text-red-400 mt-1">{csvError}</p>}
        </div>

        {/* Sample size */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <p className="text-[9px] text-slate-500 uppercase tracking-widest">
              Sample size &mdash; <span className="text-slate-300">{sampleSize}</span> rows
            </p>
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox"
                checked={sampleSize === rawRows.length}
                onChange={e => setSampleSize(e.target.checked ? rawRows.length : Math.min(50, rawRows.length))}
                className="accent-violet-500 cursor-pointer" />
              <span className="text-[9px] text-slate-500">Full</span>
            </label>
          </div>
          <input type="range" min={10} max={rawRows.length || 1000} step={10}
            value={Math.min(sampleSize, rawRows.length)}
            onChange={e => setSampleSize(Number(e.target.value))}
            disabled={sampleSize === rawRows.length}
            className="w-full accent-violet-500 disabled:opacity-40" />
          <p className="text-[9px] text-slate-600 mt-0.5">Balanced 50/50 sample</p>
        </div>

        {/* Models */}
        <div>
          <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-2">Models to compare</p>
          <div className="space-y-2">
            {MODERATOR_MODELS.map(m => (
              <ModelCheckbox key={m.key} model={m}
                checked={selectedKeys.includes(m.key)}
                onChange={e => setSelectedKeys(prev =>
                  e.target.checked ? [...prev, m.key] : prev.filter(k => k !== m.key)
                )} />
            ))}
          </div>
        </div>

        {/* Resume interrupted run */}
        {interrupted && !running && (
          <div className="border border-amber-700/40 rounded-lg p-2.5 bg-amber-900/10 space-y-1.5">
            <p className="text-[10px] text-amber-400 font-medium">Interrupted run detected</p>
            <p className="text-[9px] text-slate-500 leading-snug">
              {interrupted.done}/{interrupted.total} classifications done
              {interrupted.startedAt && ` · started ${new Date(interrupted.startedAt).toLocaleTimeString()}`}
            </p>
            <div className="flex gap-1.5">
              <button onClick={handleResume}
                className="flex-1 py-1 bg-amber-700/30 hover:bg-amber-700/50 border border-amber-700/40 rounded text-[10px] text-amber-300 transition-colors">
                Resume
              </button>
              <button onClick={() => { localStorage.removeItem(PROGRESS_KEY); setInterrupted(null); }}
                className="flex-1 py-1 border border-slate-700/50 hover:border-red-700/50 rounded text-[10px] text-slate-500 hover:text-red-400 transition-colors">
                Discard
              </button>
            </div>
          </div>
        )}

        {/* Run / Stop */}
        <div className="space-y-2">
          <button onClick={handleRun}
            disabled={running || !rawRows.length || !selectedModels.length}
            className="w-full py-2 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-700 disabled:text-slate-500 rounded-lg text-[11px] text-white font-medium transition-colors">
            {running ? `Running… ${progress.done}/${progress.total}` : "Run benchmark"}
          </button>
          {running && (
            <button onClick={() => { abortRef.current = true; }}
              className="w-full py-1.5 border border-slate-700 hover:border-red-700 rounded-lg text-[10px] text-slate-400 hover:text-red-400 transition-colors">
              Stop
            </button>
          )}
          {running && (
            <div className="w-full bg-slate-800 rounded-full h-1">
              <div className="bg-violet-500 h-1 rounded-full transition-all"
                style={{ width: progress.total ? pct(progress.done / progress.total) : "0%" }} />
            </div>
          )}
        </div>

        {/* Export */}
        {results && (
          <button onClick={handleExport}
            className="w-full py-1.5 border border-slate-700/50 hover:border-slate-500 rounded-lg text-[10px] text-slate-400 hover:text-slate-200 transition-colors">
            Export CSV
          </button>
        )}

        {results && (
          <button onClick={() => { setResults(null); localStorage.removeItem(STORAGE_KEY); localStorage.removeItem(PROGRESS_KEY); setInterrupted(null); }}
            className="w-full py-1.5 border border-slate-700/50 hover:border-red-700/50 rounded-lg text-[10px] text-slate-600 hover:text-red-400 transition-colors">
            Clear results
          </button>
        )}
      </div>

      {/* ── Results area ── */}
      <div className="flex-1 overflow-auto p-5">
        {!results && !running && (
          <div className="h-full flex items-center justify-center">
            <p className="text-slate-600 text-sm">Configure a dataset and models, then run the benchmark.</p>
          </div>
        )}

        {results && (
          <>
            {/* Metrics summary */}
            <div className="mb-5">
              <div className="flex items-center gap-3 mb-3">
                <p className="text-[9px] text-slate-500 uppercase tracking-widest">Results</p>
                <p className="text-[10px] text-slate-600">
                  {results.rows.length} rows &mdash; {results.dataset} &mdash;{" "}
                  {new Date(results.startedAt).toLocaleString()}
                </p>
              </div>
              <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${results.models.length}, minmax(0,1fr))` }}>
                {results.models.map(m => {
                  const mx = metrics[m.key];
                  if (!mx) return null;
                  return (
                    <div key={m.key} className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/30">
                      <p className="text-[11px] text-slate-200 font-medium mb-0.5">{m.label}</p>
                      <p className="text-[9px] text-slate-500 mb-2">{m.provider}</p>
                      <div className="space-y-1.5 text-[10px]">
                        {[
                          { label: "F1",        value: mx.f1,        color: "violet" },
                          { label: "Accuracy",  value: mx.accuracy,  color: "emerald" },
                          { label: "Precision", value: mx.precision, color: "amber" },
                          { label: "Recall",    value: mx.recall,    color: "red" },
                        ].map(({ label, value, color }) => (
                          <div key={label}>
                            <div className="flex justify-between text-slate-400">
                              <span>{label}</span><span>{fmt(value)}</span>
                            </div>
                            <MetricBar value={value} color={color} />
                          </div>
                        ))}
                        <p className="text-[9px] text-slate-600 mt-1">
                          TP {mx.tp} · FP {mx.fp} · TN {mx.tn} · FN {mx.fn}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Row-by-row table */}
            <div className="overflow-x-auto">
              <table className="w-full text-[10px] border-collapse">
                <thead>
                  <tr className="border-b border-slate-800">
                    <th className="text-left py-2 pr-4 text-slate-500 font-normal w-1/2">Text</th>
                    <th className="text-center py-2 px-2 text-slate-500 font-normal w-16">Truth</th>
                    {results.models.map(m => (
                      <th key={m.key} className="text-center py-2 px-2 text-slate-500 font-normal w-24">
                        {m.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {results.rows.map((row, i) => (
                    <tr key={i} className="border-b border-slate-800/40 hover:bg-slate-800/20">
                      <td className="py-1.5 pr-4 text-slate-400 max-w-xs">
                        <span className="line-clamp-2">{row.text}</span>
                      </td>
                      <td className="text-center py-1.5 px-2">
                        <span className={row.truth ? "text-red-400" : "text-emerald-400"}>
                          {row.truth ? "harmful" : "safe"}
                        </span>
                      </td>
                      {results.models.map(m => (
                        <td key={m.key} className="text-center py-1.5 px-2" title={row.results[m.key]?.reason ?? ""}>
                          {verdictIcon(row, m.key)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
