"""
generate_adversarial_tier2.py  —  LLM-assisted (Tier 2) adversarial generation.

Reads a source dataset (ETHOS JSON or any prior adversarial JSON), rewrites each
row using a chosen LLM attack, and saves the result to public/input-data/.

Reads API keys from .env in the project root (or from environment variables).

Usage:
    python scripts/generate_adversarial_tier2.py --attack paraphrase
    python scripts/generate_adversarial_tier2.py --attack implicitise --model gpt-4o-mini
    python scripts/generate_adversarial_tier2.py --attack synonym --prompt-version v2
    python scripts/generate_adversarial_tier2.py --attack paraphrase --limit 10 --dry-run
    python scripts/generate_adversarial_tier2.py --list-attacks

Supported models:
  Anthropic : claude-haiku-4-5-20251001  claude-sonnet-4-20250514
  OpenAI    : gpt-4o-mini  gpt-4o
  Mistral   : mistral-small-latest  mistral-medium-latest
  Groq      : llama-3.1-8b-instant  llama-3.3-70b-versatile

Output format matches Tier 1 — drop-in for the benchmark tab:
  { text, originalText, label, source, attack: { type, tier, promptId,
    promptUsed, model, provider, appliedAt, success } }

Resume: if the output file already exists, rows with a non-empty 'text' are kept
and only missing/failed rows are re-requested.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Load .env from project root before importing prompts
ROOT = Path(__file__).parent.parent
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from prompts_adversarial import PROMPTS, PROMPT_BY_ID   # noqa: E402  (after env load)


# ─── Provider registry ────────────────────────────────────────────────────────

PROVIDERS = {
    # model_id → { provider, api_key_env, endpoint, format }
    "claude-haiku-4-5-20251001": {
        "provider": "Anthropic",
        "key_env":  "ANTHROPIC_API_KEY",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "format":   "anthropic",
    },
    "claude-sonnet-4-20250514": {
        "provider": "Anthropic",
        "key_env":  "ANTHROPIC_API_KEY",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "format":   "anthropic",
    },
    "gpt-4o-mini": {
        "provider": "OpenAI",
        "key_env":  "OPENAI_API_KEY",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "format":   "openai",
    },
    "gpt-4o": {
        "provider": "OpenAI",
        "key_env":  "OPENAI_API_KEY",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "format":   "openai",
    },
    "mistral-small-latest": {
        "provider": "Mistral",
        "key_env":  "MISTRAL_API_KEY",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "format":   "openai",
    },
    "mistral-medium-latest": {
        "provider": "Mistral",
        "key_env":  "MISTRAL_API_KEY",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "format":   "openai",
    },
    "llama-3.1-8b-instant": {
        "provider": "Groq",
        "key_env":  "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "format":   "openai",
    },
    "llama-3.3-70b-versatile": {
        "provider": "Groq",
        "key_env":  "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "format":   "openai",
    },
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


# ─── API call ─────────────────────────────────────────────────────────────────

def call_llm(model_id: str, system: str, user: str,
             max_tokens: int = 256,
             max_retries: int = 4,
             base_delay: float = 2.0) -> str:
    """
    Call the LLM and return the text response.
    Retries on 429 / 529 with exponential backoff.
    Raises RuntimeError on unrecoverable failure.
    """
    cfg = PROVIDERS[model_id]
    api_key = os.environ.get(cfg["key_env"], "")
    if not api_key:
        raise RuntimeError(
            f"API key not found: set {cfg['key_env']} in .env or environment"
        )

    if cfg["format"] == "anthropic":
        headers = {
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        }
        body = {
            "model":      model_id,
            "max_tokens": max_tokens,
            "system":     system,
            "messages":   [{"role": "user", "content": user}],
        }
    else:  # openai-compatible
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        body = {
            "model":      model_id,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        }

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(cfg["endpoint"], headers=headers,
                                 json=body, timeout=30)
        except requests.RequestException as exc:
            if attempt == max_retries:
                raise RuntimeError(f"Network error: {exc}") from exc
            time.sleep(base_delay * 2 ** attempt)
            continue

        if resp.status_code in (429, 529):
            retry_after = float(resp.headers.get("retry-after", base_delay * 2 ** attempt))
            if attempt == max_retries:
                raise RuntimeError(f"Rate limited after {max_retries} retries")
            time.sleep(retry_after)
            continue

        if not resp.ok:
            try:
                msg = resp.json().get("error", {}).get("message", resp.text[:200])
            except Exception:
                msg = resp.text[:200]
            raise RuntimeError(f"API error {resp.status_code}: {msg}")

        data = resp.json()
        if cfg["format"] == "anthropic":
            return data["content"][0]["text"].strip()
        else:
            return data["choices"][0]["message"]["content"].strip()

    raise RuntimeError("Unexpected exit from retry loop")


# ─── Row processing ───────────────────────────────────────────────────────────

_REFUSAL_STARTS = (
    "i can't",
    "i cannot",
    "i'm not able",
    "i am not able",
    "i won't",
    "i will not",
    "i'm unable",
    "i apologize",
    "i'm sorry",
    "as an ai",
    "this request",
    "i'm not going to",
    "i do not",
    "i don't",
    "unfortunately",
)

def _is_refusal(text: str) -> bool:
    """
    Heuristic: True if the response looks like a refusal rather than the
    requested transformation. Checks the first sentence / opening phrase.
    """
    # Normalise: take first 120 chars, strip leading whitespace
    head = text.strip()[:120].lower()
    return any(head.startswith(p) for p in _REFUSAL_STARTS)


def process_row(row: dict, prompt_cfg: dict, model_id: str,
                dry_run: bool = False) -> dict:
    """
    Apply one LLM attack to a single row.
    Returns a new row dict with perturbed text and full provenance.
    On dry_run, skips the API call and returns a placeholder.
    """
    original = row.get("originalText") or row["text"]   # use deepest original
    system   = prompt_cfg["system"]
    user     = prompt_cfg["user"].format(text=original)
    applied_at = datetime.now(timezone.utc).isoformat()

    if dry_run:
        perturbed = f"[DRY RUN — would call {model_id}]"
        success   = None
    else:
        try:
            perturbed = call_llm(model_id, system, user)
            if _is_refusal(perturbed):
                success   = False
                perturbed = original      # fall back to original
                print(f"    ↩  refusal detected — keeping original", file=sys.stderr)
            else:
                success = True
        except RuntimeError as exc:
            perturbed = original
            success   = False
            print(f"    ✗  API error: {exc}", file=sys.stderr)

    cfg_info = PROVIDERS[model_id]
    return {
        "text":         perturbed,
        "originalText": original,
        "label":        row["label"],
        "source":       row.get("source", "ethos"),
        "attack": {
            "type":       row.get("attack", {}).get("type", ""),   # chain info if stacking
            "tier":       2,
            "attackType": prompt_cfg["id"].rsplit("_", 1)[0],      # e.g. "paraphrase"
            "promptId":   prompt_cfg["id"],
            "promptDesc": prompt_cfg["description"],
            "promptUsed": {"system": system, "user": user},
            "model":      model_id,
            "provider":   cfg_info["provider"],
            "appliedAt":  applied_at,
            "success":    success,
        },
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    attack_ids = list(PROMPTS.keys())

    parser = argparse.ArgumentParser(
        description="Tier 2 LLM-assisted adversarial generation for ETHOS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--attack", choices=attack_ids,
                        help="Which attack to apply")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        choices=list(PROVIDERS.keys()),
                        help=f"LLM to use for generation (default: {DEFAULT_MODEL})")
    parser.add_argument("--prompt-version", default="v1",
                        help="Prompt version to use (default: v1)")
    parser.add_argument("--input", default=None,
                        help="Input JSON path (default: public/input-data/ethos_binary.json)")
    parser.add_argument("--output", default=None,
                        help="Output JSON path (default: public/input-data/ethos_<attack>_<model>.json)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N rows (for testing)")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Seconds to wait between API calls (default: 0.5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be sent without calling the API")
    parser.add_argument("--list-attacks", action="store_true",
                        help="List all available attacks and prompt versions, then exit")
    args = parser.parse_args()

    if args.list_attacks:
        print("\nAvailable attacks and prompt versions:\n")
        for attack_id, versions in PROMPTS.items():
            print(f"  {attack_id}")
            for ver_id, p in versions.items():
                print(f"    {ver_id}  [{p['id']}]  {p['description']}")
                if p.get("notes"):
                    print(f"           note: {p['notes']}")
        print()
        return

    if not args.attack:
        parser.error("--attack is required (or use --list-attacks to see options)")

    # Resolve prompt
    attack_versions = PROMPTS.get(args.attack, {})
    if args.prompt_version not in attack_versions:
        print(f"Error: version '{args.prompt_version}' not found for attack '{args.attack}'.")
        print(f"  Available: {list(attack_versions.keys())}")
        sys.exit(1)
    prompt_cfg = attack_versions[args.prompt_version]

    # Paths
    in_path = Path(args.input) if args.input else ROOT / "public" / "input-data" / "ethos_binary.json"
    if not in_path.exists():
        print(f"Error: input file not found: {in_path}")
        sys.exit(1)

    model_slug = args.model.replace("/", "-")
    default_out = ROOT / "public" / "input-data" / f"ethos_{args.attack}_{model_slug}.json"
    out_path = Path(args.output) if args.output else default_out

    # Load source
    with open(in_path, encoding="utf-8") as f:
        source_rows = json.load(f)
    if args.limit:
        source_rows = source_rows[: args.limit]

    print(f"\nTier 2 adversarial generation")
    print(f"  Attack   : {args.attack}  ({prompt_cfg['id']})")
    print(f"  Model    : {args.model}  [{PROVIDERS[args.model]['provider']}]")
    print(f"  Input    : {in_path.name}  ({len(source_rows)} rows)")
    print(f"  Output   : {out_path.name}")
    if args.dry_run:
        print("  Mode     : DRY RUN — no API calls")

    # Resume: load existing output if present
    existing: list[dict] = []
    if out_path.exists() and not args.dry_run:
        with open(out_path, encoding="utf-8") as f:
            existing = json.load(f)
        print(f"  Resume   : {len(existing)} rows already in output file")

    existing_originals = {
        r.get("originalText", r["text"])
        for r in existing
        if r.get("attack", {}).get("success") is not False
    }

    # Process
    results = list(existing)
    skipped = 0
    processed = 0
    failed = 0
    refused = 0

    rows_to_run = [r for r in source_rows
                   if (r.get("originalText") or r["text"]) not in existing_originals]

    if not rows_to_run:
        print("\nAll rows already processed — nothing to do.")
    else:
        print(f"\nProcessing {len(rows_to_run)} rows "
              f"({'dry run' if args.dry_run else f'delay={args.delay}s between calls'})…\n")

    for i, row in enumerate(rows_to_run):
        original_preview = (row.get("originalText") or row["text"])[:60].replace("\n", " ")
        print(f"  [{i + 1:4d}/{len(rows_to_run)}] {original_preview}…", end=" ", flush=True)

        out_row = process_row(row, prompt_cfg, args.model, dry_run=args.dry_run)
        results.append(out_row)

        if args.dry_run or out_row["attack"]["success"] is True:
            print(f"→ {out_row['text'][:60].replace(chr(10), ' ')}…")
            processed += 1
        elif out_row["attack"]["success"] is False:
            # distinguish refusal from API error via stderr output already printed
            print("↩ kept original")
            refused += 1
        else:
            print("(dry run)")
            processed += 1

        # Save after every row so progress survives interruption
        if not args.dry_run:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

        if i < len(rows_to_run) - 1 and not args.dry_run:
            time.sleep(args.delay)

    # Final save (also covers dry-run if we want to inspect output)
    if args.dry_run:
        print(f"\n[dry run] would write {len(results)} rows to {out_path}")
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nDone.  processed={processed}  refused={refused}  skipped={skipped}  failed={failed}")
        print(f"Saved {len(results)} rows → {out_path}")


if __name__ == "__main__":
    main()
