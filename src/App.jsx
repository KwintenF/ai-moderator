import { useState, useRef, useEffect } from "react";
import {
  MODES,
  CHAT_MODELS, MODERATOR_MODELS, IMAGE_MODERATOR_MODELS,
  buildAssistantSystemPrompt,
  callModel, runClassifier, runImageClassifier,
} from "./moderator.js";

function ModelDropdown({ label, current, setter, pool }) {
  return (
    <div>
      <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-1">{label}</p>
      <select
        value={current.key}
        onChange={e => setter(pool.find(m => m.key === e.target.value))}
        className="w-full bg-slate-900/60 border border-slate-700/50 rounded-lg px-3 py-2 text-[11px] text-slate-300 focus:outline-none focus:border-slate-500 font-mono appearance-none cursor-pointer"
      >
        {pool.map(m => (
          <option key={m.key} value={m.key}>{m.label} — {m.provider}</option>
        ))}
      </select>
    </div>
  );
}

// ─── Constants ────────────────────────────────────────────────────────────────

const VALID_MODES = ["student", "teacher"];
const APP_MODE = VALID_MODES.includes(import.meta.env.VITE_MODE)
  ? import.meta.env.VITE_MODE
  : "teacher";
const IS_STUDENT_MODE = APP_MODE === "student";

const DEFAULT_BLACKLIST = import.meta.env.VITE_BLACKLIST
  ? import.meta.env.VITE_BLACKLIST.split(",").map(t => t.trim())
  : ["violence", "adult content", "drugs", "weapons", "hacking"];

const DEFAULT_WHITELIST = import.meta.env.VITE_WHITELIST
  ? import.meta.env.VITE_WHITELIST.split(",").map(t => t.trim())
  : [
      "math", "science", "history", "literature", "geography", "grammar",
      "biology", "chemistry", "physics", "algebra", "geometry",
      "programming basics", "reading", "writing", "essays",
    ];

const DEFAULT_MODE = import.meta.env.VITE_MODERATION_MODE === "blacklist"
  ? MODES.BLACKLIST
  : MODES.WHITELIST;

const DEFAULT_CUSTOM_INSTRUCTIONS = import.meta.env.VITE_CUSTOM_INSTRUCTIONS || "";

// ─── Sub-components ───────────────────────────────────────────────────────────

function Tag({ label, onRemove, color = "blue" }) {
  const colors = {
    blue: "bg-blue-900/40 text-blue-300 border-blue-700/50",
    red: "bg-red-900/40 text-red-300 border-red-700/50",
    green: "bg-emerald-900/40 text-emerald-300 border-emerald-700/50",
    amber: "bg-amber-900/40 text-amber-300 border-amber-700/50",
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs border font-mono ${colors[color]}`}>
      {label}
      {onRemove && (
        <button onClick={onRemove} className="ml-0.5 opacity-60 hover:opacity-100 transition-opacity leading-none">x</button>
      )}
    </span>
  );
}

function TagInput({ tags, onAdd, onRemove, color, placeholder }) {
  const [input, setInput] = useState("");
  const handleKey = (e) => {
    if ((e.key === "Enter" || e.key === ",") && input.trim()) {
      e.preventDefault();
      onAdd(input.trim().toLowerCase());
      setInput("");
    }
  };
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2 min-h-6">
        {tags.map((t) => <Tag key={t} label={t} onRemove={() => onRemove(t)} color={color} />)}
      </div>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKey}
        placeholder={placeholder}
        className="w-full bg-slate-900/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-500 font-mono"
      />
    </div>
  );
}

function PipelineIndicator({ stage }) {
  const stages = [
    { key: "classifying-input", label: "Checking input" },
    { key: "generating", label: "Generating" },
    { key: "classifying-output", label: "Checking output" },
  ];
  if (!stage) return null;
  const currentIdx = stages.findIndex(s => s.key === stage);
  return (
    <div className="flex items-center gap-2 mb-4 px-1">
      {stages.map((s, i) => {
        const done = i < currentIdx;
        const active = i === currentIdx;
        return (
          <div key={s.key} className="flex items-center gap-1.5">
            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono border transition-all ${
              active ? "bg-violet-900/50 border-violet-600/50 text-violet-300" :
              done ? "bg-slate-800/50 border-slate-700/30 text-slate-500" :
              "bg-slate-900/30 border-slate-800/30 text-slate-700"
            }`}>
              {active && <div className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />}
              {done && <span className="text-emerald-500 text-xs">v</span>}
              {s.label}
            </div>
            {i < stages.length - 1 && (
              <div className={`w-4 h-px ${done ? "bg-slate-600" : "bg-slate-800"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function ConfidenceBar({ value }) {
  const pct = Math.round(value * 100);
  const color = value > 0.85 ? "bg-red-500" : value > 0.6 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-mono text-slate-500 w-8 text-right">{pct}%</span>
    </div>
  );
}

function MessageBubble({ msg }) {
  const isUser = msg.role === "user";
  const [showAudit, setShowAudit] = useState(false);
  const hasAudit = msg.inputCheck || msg.outputCheck;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-5`}>
      <div className={`max-w-[80%] ${isUser ? "order-2" : "order-1"}`}>
        {!isUser && (
          <div className="flex items-center gap-1.5 mb-1">
            <div className={`w-5 h-5 rounded-full flex items-center justify-center ${msg.blocked ? "bg-red-700" : "bg-gradient-to-br from-violet-500 to-indigo-600"}`}>
              <span className="text-[9px] text-white font-bold">{msg.blocked ? "!" : "C"}</span>
            </div>
            <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">
              {msg.blocked ? "Moderator" : "AI"}
            </span>
            {hasAudit && (
              <button onClick={() => setShowAudit(!showAudit)}
                className="text-[9px] text-slate-600 hover:text-slate-400 font-mono underline underline-offset-2 ml-1 transition-colors">
                {showAudit ? "hide audit" : "show audit"}
              </button>
            )}
          </div>
        )}

        {isUser && hasAudit && (
          <div className="flex justify-end mb-1">
            <button onClick={() => setShowAudit(!showAudit)}
              className="text-[9px] text-slate-600 hover:text-slate-400 font-mono underline underline-offset-2 transition-colors">
              {showAudit ? "hide audit" : "show audit"}
            </button>
          </div>
        )}

        {showAudit && hasAudit && (
          <div className="mb-2 bg-slate-900/80 border border-slate-700/40 rounded-xl p-3 space-y-2.5">
            {msg.inputCheck && (
              <div>
                <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-1.5 font-semibold">Input classifier</p>
                <div className="space-y-1">
                  <div className="flex justify-between text-[10px]">
                    <span className="text-slate-500">Verdict</span>
                    <span className={msg.inputCheck.verdict === "BLOCK" ? "text-red-400" : "text-emerald-400"}>{msg.inputCheck.verdict}</span>
                  </div>
                  <div className="flex justify-between text-[10px]">
                    <span className="text-slate-500">Category</span>
                    <span className="text-slate-300 font-mono">{msg.inputCheck.category}</span>
                  </div>
                  {!msg.inputCheck.confidenceEstimated && <div className="text-[10px] text-slate-500 mb-1">Confidence</div>}
                  {!msg.inputCheck.confidenceEstimated && <ConfidenceBar value={msg.inputCheck.confidence} />}
                  <p className="text-[10px] text-slate-400 mt-1 italic">"{msg.inputCheck.reason}"</p>
                </div>
              </div>
            )}
            {msg.outputCheck && (
              <div className="border-t border-slate-800 pt-2.5">
                <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-1.5 font-semibold">Output classifier</p>
                <div className="space-y-1">
                  <div className="flex justify-between text-[10px]">
                    <span className="text-slate-500">Verdict</span>
                    <span className={msg.outputCheck.verdict === "BLOCK" ? "text-red-400" : "text-emerald-400"}>{msg.outputCheck.verdict}</span>
                  </div>
                  <div className="flex justify-between text-[10px]">
                    <span className="text-slate-500">Category</span>
                    <span className="text-slate-300 font-mono">{msg.outputCheck.category}</span>
                  </div>
                  {!msg.outputCheck.confidenceEstimated && <div className="text-[10px] text-slate-500 mb-1">Confidence</div>}
                  {!msg.outputCheck.confidenceEstimated && <ConfidenceBar value={msg.outputCheck.confidence} />}
                  <p className="text-[10px] text-slate-400 mt-1 italic">"{msg.outputCheck.reason}"</p>
                </div>
              </div>
            )}
          </div>
        )}

        <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
          isUser ? "bg-indigo-600/80 text-white rounded-tr-sm"
          : msg.blocked ? "bg-red-950/60 border border-red-800/40 text-red-300 rounded-tl-sm"
          : "bg-slate-800/80 border border-slate-700/30 text-slate-200 rounded-tl-sm"
        }`}>
          {msg.blocked && (
            <div className="flex items-center gap-1.5 mb-2 text-red-400">
              <span>x</span>
              <span className="text-[10px] font-mono uppercase tracking-wider font-semibold">
                Blocked — {msg.blockedAt === "input" ? "Input rejected" : "Response rejected"}
              </span>
            </div>
          )}
          <p className="whitespace-pre-wrap">{msg.content}</p>
        </div>
        <div className={`text-[10px] text-slate-600 mt-1 font-mono ${isUser ? "text-right" : ""}`}>
          {msg.time}
        </div>
      </div>
    </div>
  );
}

function AuditLog({ log }) {
  if (log.length === 0) return (
    <div className="text-center text-[10px] text-slate-700 py-6 font-mono">No events yet</div>
  );
  return (
    <div className="space-y-2">
      {[...log].reverse().map((entry, i) => (
        <div key={i} className={`rounded-lg p-2.5 border text-[10px] font-mono ${
          entry.verdict === "BLOCK" ? "bg-red-950/30 border-red-800/30" : "bg-slate-800/30 border-slate-700/20"
        }`}>
          <div className="flex justify-between mb-1">
            <span className={entry.verdict === "BLOCK" ? "text-red-400" : "text-emerald-400"}>{entry.verdict}</span>
            <span className="text-slate-600">{entry.stage} - {entry.time}</span>
          </div>
          <p className="text-slate-500 truncate">"{entry.text}"</p>
          <p className="text-slate-600 mt-0.5 italic">{entry.reason}</p>
          {!entry.confidenceEstimated && <ConfidenceBar value={entry.confidence} />}
        </div>
      ))}
    </div>
  );
}

// ─── Forum Moderator ──────────────────────────────────────────────────────────

function ForumModerator({ mode, blacklist, whitelist, customInstructions }) {
  const [textModeratorModel,  setTextModeratorModel]  = useState(MODERATOR_MODELS[0]);
  const [imageModeratorModel, setImageModeratorModel] = useState(IMAGE_MODERATOR_MODELS[0]);
  const [posts, setPosts] = useState("");
  const [images, setImages] = useState([]); // [{ name, caption, base64, mediaType, dataUrl }]
  const [results, setResults] = useState([]);
  const [running, setRunning] = useState(false);
  const fileInputRef = useRef(null);
  const imageInputRef = useRef(null);

  const loadFile = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setPosts(ev.target.result);
    reader.readAsText(file);
    e.target.value = "";
  };

  const [imageError, setImageError] = useState("");

  const loadImages = (e) => {
    const files = Array.from(e.target.files);
    const unsupported = files.filter(f => f.type === "image/svg+xml" || f.name.endsWith(".svg"));
    if (unsupported.length > 0) {
      setImageError(`SVG is not supported — convert to PNG first: rsvg-convert -w 800 file.svg -o file.png`);
      e.target.value = "";
      return;
    }
    setImageError("");
    files.forEach(file => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        const dataUrl = ev.target.result;
        const base64 = dataUrl.split(",")[1];
        setImages(prev => [...prev, { name: file.name, caption: "", base64, mediaType: file.type, dataUrl }]);
      };
      reader.readAsDataURL(file);
    });
    e.target.value = "";
  };

  const parsePosts = (raw) => {
    try {
      const json = JSON.parse(raw);
      if (Array.isArray(json)) return json.map(item => ({
        post: item.post || "",
        author: item.author || null,
        timestamp: item.timestamp || null,
        type: "text",
      }));
    } catch {
      // not JSON — fall back to --- separated plain text
    }
    return raw.split("\n---\n").map(p => ({ post: p.trim(), author: null, timestamp: null, type: "text" })).filter(p => p.post);
  };

  const classify = async () => {
    setRunning(true);
    const out = [];
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    for (const item of parsePosts(posts)) {
      try {
        const result = await runClassifier(textModeratorModel, item.post, mode, blacklist, whitelist, customInstructions, "input");
        out.push({ ...item, ...result, time });
      } catch {
        out.push({ ...item, verdict: "ERROR", confidence: 0, category: "error", reason: "Failed to classify post", time });
      }
    }

    for (const img of images) {
      try {
        const result = await runImageClassifier(imageModeratorModel, img.base64, img.mediaType, img.caption, mode, blacklist, whitelist, customInstructions);
        out.push({ post: img.caption || img.name, author: null, timestamp: null, type: "image", dataUrl: img.dataUrl, ...result, time });
      } catch {
        out.push({ post: img.caption || img.name, author: null, timestamp: null, type: "image", dataUrl: img.dataUrl, verdict: "ERROR", confidence: 0, category: "error", reason: "Failed to classify image", time });
      }
    }

    setResults(out);
    setRunning(false);
  };

  const exportCSV = () => {
    const header = "type,verdict,confidence,category,author,timestamp,reason,post";
    const rows = results.map(r =>
      `${r.type || "text"},${r.verdict},${r.confidence},${r.category},${r.author || ""},${r.timestamp || ""},"${r.reason.replace(/"/g, '""')}","${r.post.replace(/"/g, '""')}"`
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "moderation-log.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalItems = parsePosts(posts).length + images.length;
  const blockedCount = results.filter(r => r.verdict === "BLOCK").length;

  return (
    <div className="space-y-4">
      <div>
        <div className="flex justify-between items-center mb-2">
          <p className="text-[10px] text-slate-500 uppercase tracking-widest">Posts to classify</p>
          <button onClick={() => fileInputRef.current.click()} className="px-3 py-1 text-[10px] font-mono bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-slate-100 rounded-md transition-colors">+ Load file</button>
          <input ref={fileInputRef} type="file" accept=".txt,.json" onChange={loadFile} className="hidden" />
        </div>
        <p className="text-[9px] text-slate-600 mb-2">Separate multiple posts with <span className="text-slate-500 font-mono">---</span> on its own line, or load a <span className="text-slate-500 font-mono">.txt</span> / <span className="text-slate-500 font-mono">.json</span> file</p>
        <textarea
          value={posts}
          onChange={e => setPosts(e.target.value)}
          placeholder={"Post 1 text...\n---\nPost 2 text...\n---\nPost 3 text..."}
          rows={6}
          className="w-full bg-slate-900/60 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-500 resize-none font-mono"
        />
      </div>
      {/* Image uploads */}
      <div>
        <div className="flex justify-between items-center mb-2">
          <p className="text-[10px] text-slate-500 uppercase tracking-widest">Images</p>
          <button onClick={() => imageInputRef.current.click()} className="px-3 py-1 text-[10px] font-mono bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-slate-100 rounded-md transition-colors">+ Add images</button>
          <input ref={imageInputRef} type="file" accept="image/*" multiple onChange={loadImages} className="hidden" />
        </div>
        <p className="text-[9px] text-slate-600 mb-2">jpg, png, gif, webp — SVG not supported, convert first</p>
        {imageError && <p className="text-[9px] text-red-400 font-mono mb-2">{imageError}</p>}
        {images.length === 0 ? (
          <p className="text-[9px] text-slate-700 font-mono italic">No images added</p>
        ) : (
          <div className="space-y-2">
            {images.map((img, i) => (
              <div key={i} className="flex gap-2 items-center bg-slate-900/40 rounded-lg p-2 border border-slate-700/30">
                <img src={img.dataUrl} alt="" className="w-10 h-10 object-cover rounded shrink-0" />
                <input
                  value={img.caption}
                  onChange={e => setImages(prev => prev.map((im, j) => j === i ? { ...im, caption: e.target.value } : im))}
                  placeholder="Optional caption..."
                  className="flex-1 bg-transparent text-[10px] text-slate-300 placeholder-slate-600 focus:outline-none font-mono"
                />
                <button onClick={() => setImages(prev => prev.filter((_, j) => j !== i))} className="text-slate-700 hover:text-slate-400 text-[10px]">x</button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2 border border-slate-800/50 rounded-lg p-3">
        <ModelDropdown label="Text moderator" current={textModeratorModel} setter={setTextModeratorModel} pool={MODERATOR_MODELS} />
        <ModelDropdown label="Image moderator" current={imageModeratorModel} setter={setImageModeratorModel} pool={IMAGE_MODERATOR_MODELS} />
      </div>

      <button
        onClick={classify}
        disabled={running || (totalItems === 0)}
        className="w-full py-2 text-[10px] uppercase tracking-widest bg-violet-900/40 border border-violet-700/40 text-violet-300 hover:bg-violet-900/60 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg transition-colors"
      >
        {running ? "Classifying..." : `Classify${totalItems > 1 ? ` (${totalItems} items)` : ""}`}
      </button>

      {results.length > 0 && (
        <div>
          <div className="flex justify-between items-center mb-2">
            <p className="text-[10px] text-slate-500 uppercase tracking-widest">Results</p>
            <button onClick={exportCSV} className="text-[9px] text-slate-600 hover:text-slate-400 transition-colors font-mono">export CSV</button>
          </div>
          <div className="grid grid-cols-3 gap-1.5 mb-3">
            {[
              { label: "Total", value: results.length, color: "text-slate-300" },
              { label: "Blocked", value: blockedCount, color: "text-red-400" },
              { label: "Passed", value: results.length - blockedCount, color: "text-emerald-400" },
            ].map(s => (
              <div key={s.label} className="bg-slate-800/40 rounded-lg p-2 border border-slate-700/30 text-center">
                <div className={`text-base font-bold ${s.color}`}>{s.value}</div>
                <div className="text-[9px] text-slate-600">{s.label}</div>
              </div>
            ))}
          </div>
          <div className="space-y-2">
            {results.map((r, i) => (
              <div key={i} className={`rounded-lg p-2.5 border text-[10px] font-mono ${
                r.verdict === "BLOCK" ? "bg-red-950/30 border-red-800/30" :
                r.verdict === "ERROR" ? "bg-amber-950/30 border-amber-800/30" :
                "bg-slate-800/30 border-slate-700/20"}`}>
                <div className="flex justify-between mb-1">
                  <span className={r.verdict === "BLOCK" ? "text-red-400" : r.verdict === "ERROR" ? "text-amber-400" : "text-emerald-400"}>{r.verdict}</span>
                  <span className="text-slate-600">{r.type === "image" ? "image · " : ""}{r.category} · {r.time}</span>
                </div>
                {(r.author || r.timestamp) && (
                  <div className="flex gap-2 mb-1">
                    {r.author && <span className="text-violet-400">{r.author}</span>}
                    {r.timestamp && <span className="text-slate-600">{new Date(r.timestamp).toLocaleString()}</span>}
                  </div>
                )}
                {r.type === "image" && r.dataUrl && (
                  <img src={r.dataUrl} alt="" className="w-16 h-16 object-cover rounded mb-1" />
                )}
                <p className="text-slate-500 truncate">"{r.post.slice(0, 60)}{r.post.length > 60 ? "..." : ""}"</p>
                <p className="text-slate-600 mt-0.5 italic">{r.reason}</p>
                {!r.confidenceEstimated && <ConfidenceBar value={r.confidence} />}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [mode, setMode] = useState(DEFAULT_MODE);
  const [blacklist, setBlacklist] = useState(DEFAULT_BLACKLIST);
  const [whitelist, setWhitelist] = useState(DEFAULT_WHITELIST);
  const [customInstructions, setCustomInstructions] = useState(DEFAULT_CUSTOM_INSTRUCTIONS);
  const [responderModel,       setResponderModel]       = useState(CHAT_MODELS[0]);
  const [inputModeratorModel,  setInputModeratorModel]  = useState(MODERATOR_MODELS[0]);
  const [outputModeratorModel, setOutputModeratorModel] = useState(MODERATOR_MODELS[0]);
  const [imageModeratorModel,  setImageModeratorModel]  = useState(IMAGE_MODERATOR_MODELS[0]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [pipelineStage, setPipelineStage] = useState(null);
  const [panel, setPanel] = useState("config");
  const [error, setError] = useState("");
  const [auditLog, setAuditLog] = useState([]);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pipelineStage]);

  const addTag = (list, setList) => (tag) => {
    if (tag && !list.includes(tag)) setList([...list, tag]);
  };
  const removeTag = (list, setList) => (tag) => setList(list.filter((t) => t !== tag));
  const logAudit = (entry) => setAuditLog(prev => [...prev, entry]);

  const sendMessage = async () => {
    if (!input.trim() || pipelineStage) return;
    setError("");
    const userText = input.trim();
    setInput("");
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    const userMsg = { role: "user", content: userText, time };
    setMessages(prev => [...prev, userMsg]);

    try {
      // Stage 1: Classify input
      setPipelineStage("classifying-input");
      const inputCheck = await runClassifier(inputModeratorModel, userText, mode, blacklist, whitelist, customInstructions, "input");

      logAudit({ stage: "input", verdict: inputCheck.verdict, confidence: inputCheck.confidence, reason: inputCheck.reason, text: userText.slice(0, 60), time });

      setMessages(prev => prev.map((m, i) => i === prev.length - 1 ? { ...m, inputCheck } : m));

      if (inputCheck.verdict === "BLOCK") {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: mode === MODES.WHITELIST
            ? `I can only help with schoolwork topics like ${whitelist.slice(0, 3).join(", ")}, and more. ${inputCheck.reason}`
            : `I'm unable to help with that. ${inputCheck.reason}`,
          blocked: true, blockedAt: "input", time, inputCheck,
        }]);
        setPipelineStage(null);
        return;
      }

      // Stage 2: Generate response
      setPipelineStage("generating");
      const history = messages.filter(m => !m.blocked).concat(userMsg).map(m => ({ role: m.role, content: m.content }));
      const systemPrompt = buildAssistantSystemPrompt(mode, blacklist, whitelist, customInstructions);
      const replyText = await callModel(responderModel, history, systemPrompt);

      // Stage 3: Classify output
      setPipelineStage("classifying-output");
      const outputCheck = await runClassifier(outputModeratorModel, replyText, mode, blacklist, whitelist, customInstructions, "output");

      logAudit({ stage: "output", verdict: outputCheck.verdict, confidence: outputCheck.confidence, reason: outputCheck.reason, text: replyText.slice(0, 60), time });

      if (outputCheck.verdict === "BLOCK") {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: "The generated response was flagged by the moderator and withheld. Please try rephrasing your question.",
          blocked: true, blockedAt: "output", time, inputCheck, outputCheck,
        }]);
      } else {
        setMessages(prev => [...prev, { role: "assistant", content: replyText, time, inputCheck, outputCheck }]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setPipelineStage(null);
      inputRef.current?.focus();
    }
  };

  const clearChat = () => { setMessages([]); setAuditLog([]); };
  const blockedCount = auditLog.filter(e => e.verdict === "BLOCK").length;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex" style={{ fontFamily: "'DM Mono', monospace" }}>

      {/* Sidebar — hidden in student mode */}
      {!IS_STUDENT_MODE && <div className={`${panel === "forum" ? "flex-1" : "w-72 shrink-0"} min-h-screen bg-slate-900/50 border-r border-slate-800/50 flex flex-col`}>
        <div className="p-5 border-b border-slate-800/50">
          <div className="flex items-center gap-2 mb-1">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
              <span className="text-xs text-white font-bold">M</span>
            </div>
            <span className="font-semibold text-sm tracking-wide">AI Moderator</span>
          </div>
          <p className="text-[10px] text-slate-500 ml-9">Semantic guardrail pipeline</p>
        </div>

        {/* Mode Toggle */}
        <div className="p-4 border-b border-slate-800/50">
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-2">Mode</p>
          <div className="grid grid-cols-2 gap-1.5">
            {Object.entries(MODES).map(([key, val]) => {
              const active = mode === val;
              return (
                <button key={val} onClick={() => { setMode(val); clearChat(); }}
                  className={`px-2 py-2 rounded-lg text-xs transition-all text-left ${active
                    ? val === MODES.BLACKLIST ? "bg-red-900/50 border border-red-700/50 text-red-300" : "bg-emerald-900/50 border border-emerald-700/50 text-emerald-300"
                    : "bg-slate-800/50 border border-slate-700/30 text-slate-500 hover:text-slate-300"}`}>
                  <div className="font-semibold text-[11px]">{key === "BLACKLIST" ? "Blacklist" : "Whitelist"}</div>
                  <div className="text-[9px] opacity-70 mt-0.5">{key === "BLACKLIST" ? "Block specific topics" : "School assistant"}</div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-800/50">
          {["config", "audit", "forum", "info"].map((p) => (
            <button key={p} onClick={() => setPanel(p)}
              className={`flex-1 py-2.5 text-[10px] uppercase tracking-widest transition-colors relative ${panel === p ? "text-slate-200" : "text-slate-600 hover:text-slate-400"}`}>
              {p}
              {p === "audit" && blockedCount > 0 && (
                <span className="absolute top-1.5 right-1 w-3.5 h-3.5 bg-red-600 rounded-full text-[8px] flex items-center justify-center text-white">{blockedCount}</span>
              )}
              {panel === p && <div className="absolute bottom-0 left-0 right-0 h-px bg-violet-500" />}
            </button>
          ))}
        </div>

        {/* Panel Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {panel === "config" && (
            <>
              {mode === MODES.BLACKLIST ? (
                <div>
                  <p className="text-[10px] text-red-400 uppercase tracking-widest mb-2">Blocked Topics</p>
                  <TagInput tags={blacklist} onAdd={addTag(blacklist, setBlacklist)} onRemove={removeTag(blacklist, setBlacklist)} color="red" placeholder="Add topic + Enter" />
                  <p className="text-[9px] text-slate-600 mt-1.5">The semantic classifier understands meaning, not just keywords.</p>
                </div>
              ) : (
                <div>
                  <p className="text-[10px] text-emerald-400 uppercase tracking-widest mb-2">Allowed Topics</p>
                  <TagInput tags={whitelist} onAdd={addTag(whitelist, setWhitelist)} onRemove={removeTag(whitelist, setWhitelist)} color="green" placeholder="Add subject + Enter" />
                  <p className="text-[9px] text-slate-600 mt-1.5">Only these academic subjects are permitted.</p>
                </div>
              )}
              <div>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-2">Custom Rules</p>
                <textarea value={customInstructions} onChange={(e) => setCustomInstructions(e.target.value)}
                  placeholder="e.g. Also block any requests for complete essays. Always require students to show their working..."
                  rows={4}
                  className="w-full bg-slate-900/60 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-500 resize-none font-mono" />
                <p className="text-[9px] text-slate-600 mt-1">Injected into both classifier and assistant prompts.</p>
              </div>
              <div className="space-y-3">
                <p className="text-[10px] text-slate-500 uppercase tracking-widest">Models</p>
                <ModelDropdown label="Responder" current={responderModel} setter={m => { setResponderModel(m); clearChat(); }} pool={CHAT_MODELS} />
                <ModelDropdown label="Input Moderator" current={inputModeratorModel} setter={setInputModeratorModel} pool={MODERATOR_MODELS} />
                <ModelDropdown label="Output Moderator" current={outputModeratorModel} setter={setOutputModeratorModel} pool={MODERATOR_MODELS} />
                <ModelDropdown label="Image Moderator" current={imageModeratorModel} setter={setImageModeratorModel} pool={IMAGE_MODERATOR_MODELS} />
              </div>
            </>
          )}

          {panel === "audit" && (
            <div>
              <div className="flex justify-between items-center mb-3">
                <p className="text-[10px] text-slate-500 uppercase tracking-widest">Classification Log</p>
                <div className="flex gap-2">
                  {auditLog.length > 0 && (
                    <button onClick={() => {
                      const header = "stage,verdict,confidence,category,reason,text,time";
                      const rows = auditLog.map(e =>
                        `${e.stage},${e.verdict},${e.confidence},${e.category},"${e.reason.replace(/"/g, '""')}","${e.text.replace(/"/g, '""')}",${e.time}`
                      );
                      const csv = [header, ...rows].join("\n");
                      const blob = new Blob([csv], { type: "text/csv" });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = "chat-audit-log.csv";
                      a.click();
                      URL.revokeObjectURL(url);
                    }} className="text-[9px] text-slate-600 hover:text-slate-400 transition-colors font-mono">export CSV</button>
                  )}
                  <button onClick={() => setAuditLog([])} className="text-[9px] text-slate-600 hover:text-slate-400 transition-colors">clear</button>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-1.5 mb-3">
                {[
                  { label: "Total", value: auditLog.length, color: "text-slate-300" },
                  { label: "Blocked", value: blockedCount, color: "text-red-400" },
                  { label: "Passed", value: auditLog.length - blockedCount, color: "text-emerald-400" },
                ].map(s => (
                  <div key={s.label} className="bg-slate-800/40 rounded-lg p-2 border border-slate-700/30 text-center">
                    <div className={`text-base font-bold ${s.color}`}>{s.value}</div>
                    <div className="text-[9px] text-slate-600">{s.label}</div>
                  </div>
                ))}
              </div>
              <AuditLog log={auditLog} />
            </div>
          )}

          {panel === "forum" && (
            <ForumModerator
              mode={mode}
              blacklist={blacklist}
              whitelist={whitelist}
              customInstructions={customInstructions}
            />
          )}

          {panel === "info" && (
            <div className="space-y-3">
              <div className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/30">
                <p className="text-[10px] text-slate-400 font-semibold mb-2">Pipeline stages</p>
                {[
                  { label: "1. Input classifier", desc: "Semantic check before the AI sees the message" },
                  { label: "2. AI assistant", desc: "Generates response under system prompt constraints" },
                  { label: "3. Output classifier", desc: "Checks response before student sees it" },
                ].map(s => (
                  <div key={s.label} className="mb-2">
                    <p className="text-[10px] text-violet-400 font-mono">{s.label}</p>
                    <p className="text-[9px] text-slate-500">{s.desc}</p>
                  </div>
                ))}
              </div>
              <div className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/30">
                <p className="text-[10px] text-slate-400 font-semibold mb-2">What it catches</p>
                {["Roleplay / jailbreak attempts", "Hypothetical framings", "Language switching", "Topic pivoting", "Indirect references", "Instruction overrides"].map(item => (
                  <div key={item} className="flex items-center gap-2 mb-1">
                    <div className="w-1 h-1 rounded-full bg-violet-500" />
                    <span className="text-[10px] text-slate-500">{item}</span>
                  </div>
                ))}
              </div>
              <div className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/30">
                <p className="text-[10px] text-slate-400 font-semibold mb-1.5">Multi-model</p>
                <p className="text-[9px] text-slate-500 leading-relaxed">Switch models in the Config tab. <span className="text-violet-400 font-mono">callModel()</span> supports both Anthropic and OpenAI-compatible APIs. Add new models to the <span className="text-violet-400 font-mono">MODELS</span> registry and a matching proxy route in <span className="text-violet-400 font-mono">vite.config.js</span>.</p>
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-slate-800/50">
          <button onClick={clearChat}
            className="w-full py-2 text-[10px] uppercase tracking-widest text-slate-600 hover:text-slate-400 transition-colors border border-slate-800 rounded-lg hover:border-slate-700">
            Clear conversation
          </button>
        </div>
      </div>}

      {/* Chat Area — hidden when forum tab is active */}
      {panel !== "forum" && <div className="flex-1 flex flex-col min-w-0">
        <div className="px-6 py-3.5 border-b border-slate-800/50 flex items-center justify-between bg-slate-900/20 shrink-0">
          <div className="flex items-center gap-3">
            <div className={`px-2.5 py-1 rounded-md text-[10px] font-semibold uppercase tracking-widest border ${
              mode === MODES.BLACKLIST ? "bg-red-900/30 border-red-700/40 text-red-400" : "bg-emerald-900/30 border-emerald-700/40 text-emerald-400"
            }`}>
              {mode === MODES.BLACKLIST ? "Blacklist" : "Whitelist"} Active
            </div>
            <div className="flex items-center gap-1.5 text-[10px] text-slate-600">
              <div className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" />
              Semantic classifier active
            </div>
          </div>
          <div className="flex gap-1 flex-wrap justify-end max-w-xs">
            {(mode === MODES.BLACKLIST ? blacklist : whitelist).slice(0, 3).map(t => (
              <Tag key={t} label={t} color={mode === MODES.BLACKLIST ? "red" : "green"} />
            ))}
            {(mode === MODES.BLACKLIST ? blacklist : whitelist).length > 3 && (
              <span className="text-[10px] text-slate-600 self-center">+{(mode === MODES.BLACKLIST ? blacklist : whitelist).length - 3} more</span>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {messages.length === 0 && !pipelineStage ? (
            <div className="flex flex-col items-center justify-center h-full text-center opacity-40">
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center mb-4">
                <span className="text-xl text-white font-bold">M</span>
              </div>
              <p className="text-sm text-slate-400 font-semibold">{mode === MODES.WHITELIST ? "Whitelist" : "Blacklist"} Mode</p>
              <p className="text-xs text-slate-600 mt-1 max-w-sm">
                {mode === MODES.WHITELIST
                  ? "Every message passes through a semantic classifier before the AI responds. Students cannot bypass it with clever rephrasing."
                  : `Blocking ${blacklist.length} topic categories via semantic understanding, not just keyword matching.`}
              </p>
            </div>
          ) : (
            messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)
          )}

          {pipelineStage && <PipelineIndicator stage={pipelineStage} />}

          {error && (
            <div className="bg-red-950/40 border border-red-800/40 rounded-lg p-3 text-xs text-red-400 mb-4">
              Error: {error}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="px-6 py-4 border-t border-slate-800/50 bg-slate-900/20 shrink-0">
          <div className="flex gap-3">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
              disabled={!!pipelineStage}
              placeholder={pipelineStage ? "Processing..." : mode === MODES.WHITELIST ? "Ask about your schoolwork..." : "Type a message..."}
              className="flex-1 bg-slate-900/60 border border-slate-700/50 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500 font-mono transition-colors disabled:opacity-40"
            />
            <button onClick={sendMessage} disabled={!!pipelineStage || !input.trim()}
              className="px-5 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-xl text-sm transition-all font-semibold">
              {pipelineStage ? "..." : "Send"}
            </button>
          </div>
          <p className="text-[10px] text-slate-700 mt-2 font-mono">
            Input classifier → AI → Output classifier
          </p>
        </div>
      </div>}
    </div>
  );
}
