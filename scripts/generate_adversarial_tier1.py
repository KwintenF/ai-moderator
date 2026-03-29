"""
generate_adversarial_tier1.py  —  Apply Tier 1 (algorithmic) adversarial attacks to ETHOS.

Reads:   public/input-data/ethos_binary.json
Writes:  public/input-data/ethos_<attack>.json  (one file per attack)

Each output file is a drop-in replacement for ethos_binary.json — same [{text, label}]
shape that the benchmark tab already understands, plus extra fields for provenance:
  originalText  — the unmodified source text
  source        — "ethos"
  attack        — { type, params, appliedAt }

Usage:
    python scripts/generate_adversarial_tier1.py [--attacks all] [--intensity 0.3] [--seed 42]
    python scripts/generate_adversarial_tier1.py --attacks homoglyph leet char_spacing

All Tier 1 attacks (no API, deterministic, fast):
  homoglyph       Replace Latin chars with Unicode visual lookalikes (Cyrillic / Greek)
  zero_width      Insert U+200B zero-width spaces between characters
  char_spacing    Insert spaces between every character: hate → h a t e
  leet            Leet-speak substitutions: a→4, e→3, i→1, o→0, s→$
  char_repeat     Randomly repeat one character per word: hate → haate
  punct_insert    Insert punctuation mid-word: hate → h.a.t.e  /  f*ck
  word_reversal   Reverse characters of randomly selected words: hate → etah
  typo            Swap a random char for an adjacent-keyboard key
"""

import argparse
import json
import random
import re
import string
from datetime import datetime, timezone
from pathlib import Path


# ─── Homoglyph table ──────────────────────────────────────────────────────────
# Maps ASCII lowercase → Unicode visual lookalike (Cyrillic / Greek).
# Only characters with near-perfect visual matches are included — the goal is
# that the output is indistinguishable to a human reader.
HOMOGLYPHS: dict[str, str] = {
    "a": "\u0430",   # Cyrillic а
    "c": "\u0441",   # Cyrillic с
    "e": "\u0435",   # Cyrillic е
    "i": "\u0456",   # Ukrainian і (Cyrillic)
    "j": "\u0458",   # Cyrillic ј
    "o": "\u043e",   # Cyrillic о
    "p": "\u0440",   # Cyrillic р
    "s": "\u0455",   # Cyrillic ѕ
    "x": "\u0445",   # Cyrillic х
    "y": "\u0443",   # Cyrillic у
    # Greek
    "v": "\u03bd",   # Greek ν
    "n": "\u0578",   # Armenian ո  (visually near-identical to n)
}

# ─── Leet-speak table ─────────────────────────────────────────────────────────
LEET: dict[str, str] = {
    "a": "4",
    "e": "3",
    "i": "1",
    "o": "0",
    "s": "$",
    "t": "7",
    "l": "1",
    "g": "9",
    "b": "8",
}

# ─── Adjacent-key QWERTY table ───────────────────────────────────────────────
# Used for typo injection: maps each letter to plausible adjacent-key mistakes.
ADJACENT_KEYS: dict[str, list[str]] = {
    "a": ["q", "w", "s", "z"],
    "b": ["v", "g", "h", "n"],
    "c": ["x", "d", "f", "v"],
    "d": ["s", "e", "r", "f", "c", "x"],
    "e": ["w", "r", "d", "s"],
    "f": ["d", "r", "t", "g", "v", "c"],
    "g": ["f", "t", "y", "h", "b", "v"],
    "h": ["g", "y", "u", "j", "n", "b"],
    "i": ["u", "o", "k", "j"],
    "j": ["h", "u", "i", "k", "n", "m"],
    "k": ["j", "i", "o", "l", "m"],
    "l": ["k", "o", "p"],
    "m": ["n", "j", "k"],
    "n": ["b", "h", "j", "m"],
    "o": ["i", "p", "l", "k"],
    "p": ["o", "l"],
    "q": ["w", "a"],
    "r": ["e", "t", "f", "d"],
    "s": ["a", "w", "e", "d", "z", "x"],
    "t": ["r", "y", "g", "f"],
    "u": ["y", "i", "j", "h"],
    "v": ["c", "f", "g", "b"],
    "w": ["q", "e", "a", "s"],
    "x": ["z", "s", "d", "c"],
    "y": ["t", "u", "h", "g"],
    "z": ["a", "s", "x"],
}

# ─── Attack implementations ───────────────────────────────────────────────────
# Each function: (text: str, rng: random.Random, params: dict) -> str
# Attacks operate on individual characters or words; they never change label/truth.
# Only words that look like genuine words (no URLs, no short tokens) are modified.

def _is_word(token: str) -> bool:
    """True if the token looks like a natural-language word worth modifying."""
    return bool(re.match(r"^[a-zA-Z]{2,}$", token))


def attack_homoglyph(text: str, rng: random.Random, params: dict) -> str:
    """Replace a fraction of eligible lowercase letters with visual lookalikes."""
    intensity = params.get("intensity", 0.3)
    chars = list(text)
    for i, ch in enumerate(chars):
        lower = ch.lower()
        if lower in HOMOGLYPHS and rng.random() < intensity:
            replacement = HOMOGLYPHS[lower]
            # Preserve rough case intent — lookalikes are lowercase Unicode,
            # so we just use the replacement directly (uppercase originals become
            # lowercase lookalikes; imperceptible at small font sizes).
            chars[i] = replacement
    return "".join(chars)


def attack_zero_width(text: str, rng: random.Random, params: dict) -> str:
    """
    Insert U+200B (zero-width space) between characters of randomly chosen words.
    Invisible to human readers; breaks subword tokenisation.
    """
    intensity = params.get("intensity", 0.4)
    ZWS = "\u200b"
    words = text.split(" ")
    result = []
    for word in words:
        if _is_word(word) and rng.random() < intensity:
            result.append(ZWS.join(word))
        else:
            result.append(word)
    return " ".join(result)


def attack_char_spacing(text: str, rng: random.Random, params: dict) -> str:
    """
    Insert spaces between every character of randomly chosen words.
    hate → h a t e
    """
    intensity = params.get("intensity", 0.4)
    words = text.split(" ")
    result = []
    for word in words:
        if _is_word(word) and rng.random() < intensity:
            result.append(" ".join(word))
        else:
            result.append(word)
    return " ".join(result)


def attack_leet(text: str, rng: random.Random, params: dict) -> str:
    """Replace eligible letters with leet-speak digits/symbols."""
    intensity = params.get("intensity", 0.5)
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch.lower() in LEET and rng.random() < intensity:
            replacement = LEET[ch.lower()]
            chars[i] = replacement
    return "".join(chars)


def attack_char_repeat(text: str, rng: random.Random, params: dict) -> str:
    """
    Repeat one randomly chosen character within randomly selected words.
    hate → haate,  kill → killl
    """
    intensity = params.get("intensity", 0.5)
    n_repeats = params.get("n_repeats", 2)
    words = text.split(" ")
    result = []
    for word in words:
        if _is_word(word) and rng.random() < intensity:
            idx = rng.randrange(len(word))
            word = word[:idx] + word[idx] * n_repeats + word[idx + 1 :]
        result.append(word)
    return " ".join(result)


def attack_punct_insert(text: str, rng: random.Random, params: dict) -> str:
    """
    Insert punctuation between every character of randomly chosen words.
    Punctuation character is chosen randomly per word.
    hate → h.a.t.e  or  h*a*t*e
    """
    intensity = params.get("intensity", 0.4)
    chars_pool = params.get("chars", [".", "*", "-", "_"])
    words = text.split(" ")
    result = []
    for word in words:
        if _is_word(word) and rng.random() < intensity:
            sep = rng.choice(chars_pool)
            result.append(sep.join(word))
        else:
            result.append(word)
    return " ".join(result)


def attack_word_reversal(text: str, rng: random.Random, params: dict) -> str:
    """
    Reverse the characters of randomly selected words.
    hate → etah
    """
    intensity = params.get("intensity", 0.4)
    words = text.split(" ")
    result = []
    for word in words:
        if _is_word(word) and len(word) > 3 and rng.random() < intensity:
            result.append(word[::-1])
        else:
            result.append(word)
    return " ".join(result)


def attack_typo(text: str, rng: random.Random, params: dict) -> str:
    """
    Replace one character in randomly selected words with an adjacent-key substitute.
    Mimics accidental misspelling.
    """
    intensity = params.get("intensity", 0.4)
    words = text.split(" ")
    result = []
    for word in words:
        if _is_word(word) and rng.random() < intensity:
            # Find positions that have an adjacent key
            eligible = [i for i, ch in enumerate(word)
                        if ch.lower() in ADJACENT_KEYS]
            if eligible:
                idx = rng.choice(eligible)
                typo_char = rng.choice(ADJACENT_KEYS[word[idx].lower()])
                # Preserve case
                if word[idx].isupper():
                    typo_char = typo_char.upper()
                word = word[:idx] + typo_char + word[idx + 1:]
        result.append(word)
    return " ".join(result)


# ─── Attack registry ──────────────────────────────────────────────────────────

ATTACKS: dict[str, dict] = {
    "homoglyph": {
        "fn":     attack_homoglyph,
        "params": {"intensity": 0.3},
        "label":  "Homoglyph substitution",
        "desc":   "Latin chars replaced with Cyrillic/Greek visual lookalikes",
    },
    "zero_width": {
        "fn":     attack_zero_width,
        "params": {"intensity": 0.4},
        "label":  "Zero-width injection",
        "desc":   "U+200B zero-width spaces injected between chars of selected words",
    },
    "char_spacing": {
        "fn":     attack_char_spacing,
        "params": {"intensity": 0.4},
        "label":  "Character spacing",
        "desc":   "Spaces inserted between every character: hate → h a t e",
    },
    "leet": {
        "fn":     attack_leet,
        "params": {"intensity": 0.5},
        "label":  "Leet speak",
        "desc":   "Letter-to-digit/symbol substitutions: a→4, e→3, i→1, o→0, s→$",
    },
    "char_repeat": {
        "fn":     attack_char_repeat,
        "params": {"intensity": 0.5, "n_repeats": 2},
        "label":  "Character repetition",
        "desc":   "One random char repeated per word: hate → haate",
    },
    "punct_insert": {
        "fn":     attack_punct_insert,
        "params": {"intensity": 0.4, "chars": [".", "*", "-", "_"]},
        "label":  "Punctuation insertion",
        "desc":   "Punctuation inserted between chars: hate → h.a.t.e",
    },
    "word_reversal": {
        "fn":     attack_word_reversal,
        "params": {"intensity": 0.4},
        "label":  "Word reversal",
        "desc":   "Random words reversed character-by-character: hate → etah",
    },
    "typo": {
        "fn":     attack_typo,
        "params": {"intensity": 0.4},
        "label":  "Typo injection",
        "desc":   "One char per word swapped for an adjacent QWERTY key",
    },
}


# ─── Dataset generation ───────────────────────────────────────────────────────

def apply_attack(rows: list[dict], attack_id: str, rng: random.Random) -> list[dict]:
    attack   = ATTACKS[attack_id]
    fn       = attack["fn"]
    params   = attack["params"]
    applied_at = datetime.now(timezone.utc).isoformat()

    result = []
    for row in rows:
        original = row["text"]
        perturbed = fn(original, rng, params)
        result.append({
            "text":         perturbed,
            "originalText": original,
            "label":        row["label"],
            "source":       "ethos",
            "attack": {
                "type":      attack_id,
                "label":     attack["label"],
                "desc":      attack["desc"],
                "params":    params,
                "appliedAt": applied_at,
            },
        })
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate Tier 1 adversarial variants of ETHOS.")
    parser.add_argument(
        "--attacks", nargs="+", default=["all"],
        help="Which attacks to run (default: all). Options: " + " ".join(ATTACKS.keys()),
    )
    parser.add_argument("--intensity", type=float, default=None,
                        help="Override intensity for all attacks (0.0–1.0)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility (default: 42)")
    args = parser.parse_args()

    root     = Path(__file__).parent.parent
    src_path = root / "public" / "input-data" / "ethos_binary.json"
    out_dir  = root / "public" / "input-data"

    if not src_path.exists():
        print(f"Error: source file not found: {src_path}")
        raise SystemExit(1)

    with open(src_path, encoding="utf-8") as f:
        source_rows = json.load(f)
    print(f"Loaded {len(source_rows)} rows from {src_path.name}")

    attack_ids = list(ATTACKS.keys()) if "all" in args.attacks else args.attacks
    for aid in attack_ids:
        if aid not in ATTACKS:
            print(f"  Unknown attack '{aid}' — skipping. Valid: {list(ATTACKS.keys())}")

    attack_ids = [a for a in attack_ids if a in ATTACKS]

    for attack_id in attack_ids:
        # Override intensity if requested
        if args.intensity is not None:
            ATTACKS[attack_id]["params"] = {
                **ATTACKS[attack_id]["params"],
                "intensity": args.intensity,
            }

        rng = random.Random(args.seed)
        adversarial = apply_attack(source_rows, attack_id, rng)

        out_path = out_dir / f"ethos_{attack_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(adversarial, f, ensure_ascii=False, indent=2)

        # Diff stats
        n_changed = sum(
            1 for orig, adv in zip(source_rows, adversarial)
            if orig["text"] != adv["text"]
        )
        print(f"  [{attack_id:14s}] {n_changed:4d}/{len(adversarial)} rows modified  →  {out_path.name}")

    print(f"\nDone. {len(attack_ids)} file(s) written to {out_dir}/")


if __name__ == "__main__":
    main()
