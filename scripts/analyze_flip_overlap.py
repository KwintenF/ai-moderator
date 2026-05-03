"""
analyze_flip_overlap.py  —  Cross-reference borderline texts with adversarial benchmark results.

For each adversarial variant (typos, leet, etc.) checks how many of the extra FNs and FPs
come from texts already identified as borderline in the normal run vs. texts that were stable.

Usage:
  python3 scripts/analyze_flip_overlap.py \\
    output-data/full_claude_x/benchmark_2026-05-01-12-12.csv \\
    output-data/full_claude_x/stats_x_unstable.csv \\
    output-data/full_claude_x/benchmark_2026-05-01-09-42_typos.csv \\
    output-data/full_claude_x/benchmark_2026-05-01-11-02_leet.csv \\
    --labels "Typos" "Leet"
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

POSITIVE = "BLOCK"
NEGATIVE = "ALLOW"
TRUTH_POS = {"harmful", "1", "true", "yes", "block", "hate", "hate_speech"}
TRUTH_NEG = {"safe", "0", "false", "no", "allow", "not_hate_speech"}


def norm_truth(v):
    s = str(v).strip().lower()
    if s in TRUTH_POS: return POSITIVE
    if s in TRUTH_NEG: return NEGATIVE
    return None


def get_vcol(df):
    vcols = [c for c in df.columns if c.endswith("_verdict")]
    if not vcols:
        raise ValueError("No *_verdict columns found")
    return vcols[0]


def analyze(normal_df, unstable_df, adv_df, label, vcol):
    truth = normal_df["truth"].apply(norm_truth)

    # Unstable text sets by truth class
    unstable_harmful = set(unstable_df[unstable_df["truth"] == POSITIVE]["text"].tolist())
    unstable_safe    = set(unstable_df[unstable_df["truth"] == NEGATIVE]["text"].tolist())

    # Align by row index (same 998 texts, same order)
    normal_verdict = normal_df[vcol]
    adv_verdict    = adv_df[vcol]

    harmful_mask = truth == POSITIVE
    safe_mask    = truth == NEGATIVE

    # Per-text flip: was BLOCK in normal, ALLOW in adversarial (extra FN)
    became_fn = (normal_verdict == POSITIVE) & (adv_verdict == NEGATIVE) & harmful_mask
    # Was ALLOW in normal, BLOCK in adversarial (extra FP)
    became_fp = (normal_verdict == NEGATIVE) & (adv_verdict == POSITIVE) & safe_mask
    # Recovered: was ALLOW in normal (FN), now BLOCK in adversarial
    recovered = (normal_verdict == NEGATIVE) & (adv_verdict == POSITIVE) & harmful_mask

    extra_fn_total = int(became_fn.sum())
    extra_fn_from_unstable = int(
        (became_fn & normal_df["text"].isin(unstable_harmful)).sum()
    )
    extra_fn_from_stable = extra_fn_total - extra_fn_from_unstable

    extra_fp_total = int(became_fp.sum())
    extra_fp_from_unstable = int(
        (became_fp & normal_df["text"].isin(unstable_safe)).sum()
    )
    extra_fp_from_stable = extra_fp_total - extra_fp_from_unstable

    recovered_total = int(recovered.sum())

    # Absolute FN counts
    normal_fn = int(((normal_verdict == NEGATIVE) & harmful_mask).sum())
    adv_fn    = int(((adv_verdict    == NEGATIVE) & harmful_mask).sum())
    normal_fp = int(((normal_verdict == POSITIVE) & safe_mask).sum())
    adv_fp    = int(((adv_verdict    == POSITIVE) & safe_mask).sum())

    print(f"\n  {'─'*56}")
    print(f"  {label}")
    print(f"  {'─'*56}")
    print(f"  FN  :  {normal_fn} → {adv_fn}  (Δ = {adv_fn - normal_fn:+d})")
    print(f"  FP  :  {normal_fp} → {adv_fp}  (Δ = {adv_fp - normal_fp:+d})")

    if extra_fn_total > 0:
        print(f"\n  Extra FNs breakdown  ({extra_fn_total} texts newly missed):")
        print(f"    From borderline texts : {extra_fn_from_unstable}  "
              f"({extra_fn_from_unstable/extra_fn_total:.0%})")
        print(f"    From stable texts     : {extra_fn_from_stable}  "
              f"({extra_fn_from_stable/extra_fn_total:.0%})")
        if extra_fn_from_stable == 0:
            print(f"    ✓ All extra FNs come from already-borderline texts")
        else:
            print(f"    ! {extra_fn_from_stable} stable texts newly flipped → genuine attack effect")
    elif adv_fn < normal_fn:
        print(f"\n  FN decreased by {normal_fn - adv_fn} — attack caught more harmful texts")

    if recovered_total > 0:
        print(f"  Recovered FNs (now caught): {recovered_total}")

    if extra_fp_total > 0:
        print(f"\n  Extra FPs breakdown  ({extra_fp_total} texts newly over-blocked):")
        print(f"    From borderline texts : {extra_fp_from_unstable}  "
              f"({extra_fp_from_unstable/extra_fp_total:.0%})")
        print(f"    From stable texts     : {extra_fp_from_stable}  "
              f"({extra_fp_from_stable/extra_fp_total:.0%})")
        if extra_fp_from_stable == 0:
            print(f"    ✓ All extra FPs come from already-borderline texts")
        else:
            print(f"    ! {extra_fp_from_stable} stable texts newly flipped → genuine attack effect")


def main():
    parser = argparse.ArgumentParser(
        description="Cross-reference borderline texts with adversarial benchmark results."
    )
    parser.add_argument("normal",    help="Normal benchmark CSV (reference run)")
    parser.add_argument("unstable",  help="Unstable texts CSV from compute_benchmark_stats.py")
    parser.add_argument("adversarial", nargs="+",
                        help="Adversarial benchmark CSV(s) to compare against")
    parser.add_argument("--labels", nargs="*", default=None,
                        help="Labels for each adversarial CSV (default: filename)")
    args = parser.parse_args()

    normal_df   = pd.read_csv(args.normal)
    unstable_df = pd.read_csv(args.unstable)
    vcol        = get_vcol(normal_df)

    labels = args.labels or [Path(p).stem for p in args.adversarial]
    if len(labels) != len(args.adversarial):
        print("--labels count must match adversarial CSV count")
        sys.exit(1)

    print(f"\nCross-reference: borderline texts vs adversarial effects")
    print(f"  Normal    : {Path(args.normal).name}  ({len(normal_df)} rows)")
    print(f"  Unstable  : {len(unstable_df[unstable_df['truth']==POSITIVE])} harmful  "
          f"+ {len(unstable_df[unstable_df['truth']==NEGATIVE])} safe borderline texts")
    print(f"  Model     : {vcol.replace('_verdict','')}")

    for path, label in zip(args.adversarial, labels):
        adv_df = pd.read_csv(path)
        analyze(normal_df, unstable_df, adv_df, label, vcol)

    print()


if __name__ == "__main__":
    main()
