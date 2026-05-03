"""
fix_errors.py  —  Re-run ERROR rows in a benchmark CSV and write a patched copy.

Reads the system prompt and text directly from the CSV — no reconfiguration needed.
Writes <stem>_fixed.csv next to the original.

Usage:
    python scripts/fix_errors.py <path/to/results.csv>

API keys loaded from .env in the project root, or from environment variables.
    ANTHROPIC_API_KEY  OPENAI_API_KEY  MISTRAL_API_KEY
    GROQ_API_KEY       GOOGLE_AI_KEY   XAI_API_KEY
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# Load .env from the project root (two levels up from scripts/)
load_dotenv(Path(__file__).parent.parent / ".env")

# ─── Model registry (mirrors moderator.js) ───────────────────────────────────

MODELS = {
    "claude-sonnet":       dict(model_id="claude-sonnet-4-20250514", fmt="anthropic",
                                endpoint="https://api.anthropic.com/v1/messages",
                                env_key="ANTHROPIC_API_KEY", mod="llm"),
    "gpt-4o":              dict(model_id="gpt-4o", fmt="openai",
                                endpoint="https://api.openai.com/v1/chat/completions",
                                env_key="OPENAI_API_KEY", mod="llm"),
    "openai-moderation":   dict(model_id="omni-moderation-latest", fmt="openai",
                                endpoint="https://api.openai.com/v1/moderations",
                                env_key="OPENAI_API_KEY", mod="openai-moderation"),
    "mistral-small":       dict(model_id="mistral-small-latest", fmt="openai",
                                endpoint="https://api.mistral.ai/v1/chat/completions",
                                env_key="MISTRAL_API_KEY", mod="llm"),
    "pixtral":             dict(model_id="pixtral-12b-2409", fmt="openai",
                                endpoint="https://api.mistral.ai/v1/chat/completions",
                                env_key="MISTRAL_API_KEY", mod="llm"),
    "mistral-moderation":  dict(model_id="mistral-moderation-latest", fmt="openai",
                                endpoint="https://api.mistral.ai/v1/moderations",
                                env_key="MISTRAL_API_KEY", mod="mistral-moderation"),
    "gemini-3-flash-free": dict(model_id="gemini-3-flash-preview", fmt="openai",
                                endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                                env_key="GOOGLE_AI_KEY", mod="llm"),
    "gemini-2-flash":      dict(model_id="gemini-2.0-flash", fmt="openai",
                                endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                                env_key="GOOGLE_AI_KEY", mod="llm"),
    "grok-4":              dict(model_id="grok-4", fmt="openai",
                                endpoint="https://api.x.ai/v1/chat/completions",
                                env_key="XAI_API_KEY", mod="llm"),
    "grok-4-reasoning":    dict(model_id="grok-4.20-reasoning", fmt="openai",
                                endpoint="https://api.x.ai/v1/chat/completions",
                                env_key="XAI_API_KEY", mod="llm"),
    "groq-llama3-70b":     dict(model_id="llama-3.3-70b-versatile", fmt="openai",
                                endpoint="https://api.groq.com/openai/v1/chat/completions",
                                env_key="GROQ_API_KEY", mod="llm"),
    "groq-llama3-8b":      dict(model_id="llama-3.1-8b-instant", fmt="openai",
                                endpoint="https://api.groq.com/openai/v1/chat/completions",
                                env_key="GROQ_API_KEY", mod="llm"),
    "groq-qwen3-32b":      dict(model_id="qwen/qwen3-32b", fmt="openai",
                                endpoint="https://api.groq.com/openai/v1/chat/completions",
                                env_key="GROQ_API_KEY", mod="llm"),
    "llama-guard-3-8b":    dict(model_id="llama-guard-3-8b", fmt="openai",
                                endpoint="https://api.groq.com/openai/v1/chat/completions",
                                env_key="GROQ_API_KEY", mod="llamaguard"),
}

LLAMA_GUARD_CATEGORIES = {
    "S1": "violent-crimes",        "S2": "non-violent-crimes",
    "S3": "sex-related-crimes",    "S4": "child-sexual-exploitation",
    "S5": "defamation",            "S6": "specialized-advice",
    "S7": "privacy",               "S8": "intellectual-property",
    "S9": "indiscriminate-weapons","S10": "hate",
    "S11": "suicide-self-harm",    "S12": "sexual-content",
    "S13": "elections",            "S14": "code-interpreter-abuse",
}

# ─── Low-level API helpers ────────────────────────────────────────────────────

def _headers(m):
    key = os.environ.get(m["env_key"], "")
    if not key:
        raise RuntimeError(f"Missing environment variable: {m['env_key']}")
    if m["fmt"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _post(m, body, retries=4):
    for attempt in range(retries + 1):
        r = requests.post(m["endpoint"], headers=_headers(m), json=body, timeout=120)
        if r.status_code in (429, 529):
            wait = int(r.headers.get("retry-after", 2 ** attempt * 2))
            print(f"      rate-limited — waiting {wait}s …")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Rate-limited after {retries} retries")


# ─── Format-specific classifiers ─────────────────────────────────────────────

def _call_llm(m, system_prompt, user_message):
    if m["fmt"] == "anthropic":
        body = {"model": m["model_id"], "max_tokens": 512,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}]}
    else:
        body = {"model": m["model_id"], "max_tokens": 512,
                "messages": [{"role": "system", "content": system_prompt},
                              {"role": "user", "content": user_message}]}
    data = _post(m, body)
    return (data["content"][0]["text"] if m["fmt"] == "anthropic"
            else data["choices"][0]["message"]["content"])


def _parse_llm_json(raw):
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    vm = re.search(r'"verdict"\s*:\s*"(ALLOW|BLOCK)"', raw)
    cm = re.search(r'"confidence"\s*:\s*([0-9.]+)', raw)
    rm = re.search(r'"reason"\s*:\s*"([^"]{0,200})', raw)
    if vm:
        return {"verdict": vm.group(1),
                "confidence": float(cm.group(1)) if cm else 0.8,
                "reason": (rm.group(1) + "…") if rm else "Truncated response",
                "category": "blocked-topic" if vm.group(1) == "BLOCK" else "appropriate"}
    return None


def _call_moderation(m, text):
    data = _post(m, {"model": m["model_id"], "input": text})
    result = data["results"][0]
    scores = result["category_scores"]
    top_cat, top_score = max(scores.items(), key=lambda x: x[1])
    flagged = any(result["categories"].values())
    return {"verdict": "BLOCK" if flagged else "ALLOW",
            "confidence": top_score,
            "reason": f"Flagged: {top_cat.replace('_',' ')} ({top_score:.0%})" if flagged else "No violations",
            "category": top_cat.replace("_", "-") if flagged else "appropriate"}


def _call_llamaguard(m, text):
    body = {"model": m["model_id"], "max_tokens": 20,
            "messages": [{"role": "user", "content": text}]}
    data = _post(m, body)
    raw = data["choices"][0]["message"]["content"]
    unsafe = raw.strip().lower().startswith("unsafe")
    match = re.search(r"unsafe\s*\n\s*(S\d+(?:,\s*S\d+)*)", raw, re.IGNORECASE)
    codes = match.group(1).split(",") if match else []
    names = [LLAMA_GUARD_CATEGORIES.get(c.strip().upper(), c.strip().lower()) for c in codes]
    return {"verdict": "BLOCK" if unsafe else "ALLOW",
            "confidence": None,
            "reason": f"Unsafe: {', '.join(names) or 'unspecified'}" if unsafe else "No violations",
            "category": (names[0] if names else "harmful") if unsafe else "appropriate"}


# ─── Main classify entry point ────────────────────────────────────────────────

def classify(model_key, text, system_prompt):
    """Returns dict with verdict, confidence, reason, category, latency_ms."""
    if model_key not in MODELS:
        return dict(verdict="ERROR", confidence=0,
                    reason=f"Unknown model key: {model_key}", category="error", latency_ms=0)
    m = MODELS[model_key]
    t0 = time.time()
    try:
        mod = m["mod"]
        if mod in ("openai-moderation", "mistral-moderation"):
            result = _call_moderation(m, text)
        elif mod == "llamaguard":
            result = _call_llamaguard(m, text)
        else:
            user_msg = f'Classify this student message:\n\n"{text}"'
            raw = _call_llm(m, system_prompt, user_msg)
            result = _parse_llm_json(raw)
            if result is None:
                return dict(verdict="ERROR", confidence=0,
                            reason=f"Unparseable response: {raw[:120]}",
                            category="error", latency_ms=int((time.time()-t0)*1000))
        return {**result, "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return dict(verdict="ERROR", confidence=0, reason=str(e),
                    category="error", latency_ms=int((time.time()-t0)*1000))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/fix_errors.py <results.csv>")
        sys.exit(1)

    csv_path = Path(sys.argv[1]).resolve()
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows from {csv_path.name}")

    verdict_cols = [c for c in df.columns if c.endswith("_verdict")]
    model_keys   = [c[: -len("_verdict")] for c in verdict_cols]
    system_prompt = df["prompt_system_prompt"].iloc[0] if "prompt_system_prompt" in df.columns else ""

    total_errors = sum((df[f"{k}_verdict"] == "ERROR").sum() for k in model_keys)
    if total_errors == 0:
        print("No ERROR rows found — nothing to do.")
        return

    total_fixed = 0

    for model_key in model_keys:
        error_idx = df.index[df[f"{model_key}_verdict"] == "ERROR"].tolist()
        if not error_idx:
            continue
        print(f"\n{model_key}: {len(error_idx)} error(s)")
        for idx in error_idx:
            text = df.at[idx, "text"]
            preview = text[:70] + "…" if len(text) > 70 else text
            print(f"  row {idx}: {preview}")

            print(f" running with model_key: {model_key}")
            print("-"*50)
            print(f" running with text: {text }")
            print("-"*50)
            print(f" running with system_prompt: {system_prompt}")
            print("-"*50)
            result = classify(model_key, text, system_prompt)

            df.at[idx, f"{model_key}_verdict"]    = result["verdict"]
            df.at[idx, f"{model_key}_confidence"] = float(result["confidence"]) if result.get("confidence") is not None else float("nan")
            df.at[idx, f"{model_key}_reason"]     = result.get("reason", "")
            df.at[idx, f"{model_key}_latency_ms"] = result["latency_ms"]

            ok = result["verdict"] != "ERROR"
            print(f"    {'✓' if ok else '✗'} {result['verdict']}  —  {result.get('reason','')[:80]}")
            if ok:
                total_fixed += 1

            time.sleep(0.5)

    out_path = csv_path.with_stem(csv_path.stem + "_fixed")
    df.to_csv(out_path, index=False)
    still_broken = total_errors - total_fixed
    print(f"\n{total_fixed}/{total_errors} errors fixed → {out_path.name}")
    if still_broken:
        print(f"{still_broken} still errored — re-run the script on the _fixed file to retry.")


if __name__ == "__main__":
    main()
