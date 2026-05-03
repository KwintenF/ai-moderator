"""
compute_benchmark_stats.py  —  Compute FPR/FNR statistics from repeated benchmark runs.

Takes N CSVs from identical benchmark runs (same dataset, same prompt, different API calls)
and outputs a stats JSON consumed by compare_prompts.py to draw crosshair error bars.

Also reports per-text flip counts: texts whose verdict changed across runs — a direct
measure of model stochasticity independent of any adversarial attack.

Usage:
  python3 scripts/compute_benchmark_stats.py \\
    output-data/full_claude_x/benchmark_run1.csv \\
    output-data/full_claude_x/benchmark_run2.csv \\
    output-data/full_claude_x/benchmark_run3.csv \\
    --output output-data/full_claude_x/stats_x.json \\
    --label "X prompt"

The output JSON can then be passed to compare_prompts.py with --stats to show
error bars on the fingerprint scatter plot.
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor":   "white",
    "font.size":        10,
})

POSITIVE = "BLOCK"
NEGATIVE = "ALLOW"


def norm_truth(v):
    s = str(v).strip().lower()
    if s in ("harmful", "1", "true", "yes", "block", "hate", "hate_speech"):
        return POSITIVE
    if s in ("safe", "0", "false", "no", "allow", "not_hate_speech"):
        return NEGATIVE
    return None


def compute_fpr_fnr(df, vcol):
    truth = df["truth"].apply(norm_truth)
    pred  = df[vcol]
    mask  = truth.notna() & pred.notna() & (pred != "ERROR")
    yt, yp = truth[mask], pred[mask]
    if len(yt) == 0:
        return float("nan"), float("nan")
    tp = int(((yt == POSITIVE) & (yp == POSITIVE)).sum())
    fn = int(((yt == POSITIVE) & (yp == NEGATIVE)).sum())
    fp = int(((yt == NEGATIVE) & (yp == POSITIVE)).sum())
    tn = int(((yt == NEGATIVE) & (yp == NEGATIVE)).sum())
    fpr = fp / (fp + tn) if (fp + tn) > 0 else float("nan")
    fnr = fn / (fn + tp) if (fn + tp) > 0 else float("nan")
    return float(fpr), float(fnr)


def flip_analysis(dfs, vcol):
    """Classify each text as stable-correct, stable-incorrect, or unstable across runs.

    Harmful texts:
      stable_tp        — always BLOCK  (robustly caught)
      stable_fn        — always ALLOW  (consistently missed)
      unstable_harmful — sometimes flips (contributes to FNR variance)

    Safe texts:
      stable_tn        — always ALLOW  (robustly passed)
      stable_fp        — always BLOCK  (consistently over-blocked)
      unstable_safe    — sometimes flips (contributes to FPR variance)
    """
    run_series = []
    for df in dfs:
        if "text" not in df.columns or vcol not in df.columns:
            continue
        run_series.append(df.set_index("text")[vcol])
    if len(run_series) < 2:
        return None

    combined = pd.concat(run_series, axis=1)
    combined.columns = [f"run_{i}" for i in range(len(combined.columns))]
    valid = combined[combined.apply(
        lambda r: r.isin([POSITIVE, NEGATIVE]).all(), axis=1
    )]

    always_block = valid.apply(lambda r: (r == POSITIVE).all(), axis=1)
    always_allow = valid.apply(lambda r: (r == NEGATIVE).all(), axis=1)
    unstable     = ~(always_block | always_allow)

    truth_map     = dfs[0].set_index("text")["truth"].apply(norm_truth)
    truth         = truth_map.reindex(valid.index)
    harmful       = truth == POSITIVE
    safe          = truth == NEGATIVE

    n_total    = int(len(valid))
    n_unstable = int(unstable.sum())

    return {
        "n_total":           n_total,
        "n_harmful":         int(harmful.sum()),
        "n_safe":            int(safe.sum()),
        "stable_tp":         int((always_block & harmful).sum()),
        "stable_fn":         int((always_allow & harmful).sum()),
        "unstable_harmful":  int((unstable     & harmful).sum()),
        "stable_tn":         int((always_allow & safe).sum()),
        "stable_fp":         int((always_block & safe).sum()),
        "unstable_safe":     int((unstable     & safe).sum()),
        "n_unstable":        n_unstable,
        "flip_rate":         round(n_unstable / n_total, 6) if n_total > 0 else 0.0,
    }


def export_unstable(dfs, model_keys, csv_paths, out_path):
    """Save a CSV of texts whose verdict changed across runs."""
    records = []
    for mk in model_keys:
        vcol = f"{mk}_verdict"
        if any(vcol not in df.columns for df in dfs):
            continue

        run_series = [df.set_index("text")[vcol] for df in dfs if vcol in df.columns]
        combined   = pd.concat(run_series, axis=1)
        combined.columns = [Path(p).name for p in csv_paths]
        valid    = combined[combined.apply(lambda r: r.isin([POSITIVE, NEGATIVE]).all(), axis=1)]
        unstable = valid[valid.apply(lambda row: row.nunique() > 1, axis=1)]

        truth_map = dfs[0].set_index("text")["truth"].apply(norm_truth)

        for text, row in unstable.iterrows():
            block_count = int((row == POSITIVE).sum())
            allow_count = int((row == NEGATIVE).sum())
            rec = {
                "model":       mk,
                "truth":       truth_map.get(text, "?"),
                "block_runs":  block_count,
                "allow_runs":  allow_count,
                "flip_direction": (
                    "harmful_missed"   if truth_map.get(text) == POSITIVE and allow_count > block_count else
                    "harmful_caught"   if truth_map.get(text) == POSITIVE else
                    "safe_overblocked" if truth_map.get(text) == NEGATIVE and block_count > allow_count else
                    "safe_passed"
                ),
                "text": text,
            }
            for col in unstable.columns:
                rec[col] = row[col]
            records.append(rec)

    if not records:
        print("  No unstable texts found.")
        return

    df_out = pd.DataFrame(records).sort_values(["truth", "flip_direction", "block_runs"])
    df_out.to_csv(out_path, index=False)
    print(f"  saved → {out_path.name}  ({len(df_out)} unstable texts)")


def plot_flip_analysis(result, out_path):
    """Stacked bar chart: stable-correct / stable-incorrect / unstable per truth class.

    Left bar  — Harmful texts:  stable TP | unstable | stable FN
    Right bar — Safe texts:     stable TN | unstable | stable FP

    Unstable texts are the source of FNR/FPR run-to-run variance.
    Stable-incorrect texts are consistent errors unrelated to stochasticity.
    """
    fa_all = result.get("flip_analysis", {})
    if not fa_all:
        print("  No flip analysis data — skipping plot.")
        return

    model_keys = list(fa_all.keys())
    n_models   = len(model_keys)
    n_runs     = result["n_runs"]
    label      = result["label"]

    fig, axes = plt.subplots(1, n_models, figsize=(5 * n_models, 6), squeeze=False)

    # Colour palette
    C = {
        "stable_tp":        "#22c55e",   # green   — robustly caught
        "unstable_harmful": "#f59e0b",   # amber   — borderline harmful
        "stable_fn":        "#ef4444",   # red     — consistently missed
        "stable_tn":        "#3b82f6",   # blue    — robustly passed
        "unstable_safe":    "#fbbf24",   # yellow  — borderline safe
        "stable_fp":        "#a855f7",   # purple  — consistently over-blocked
    }

    for ax, mk in zip(axes[0], model_keys):
        fa = fa_all[mk]

        # Two stacked bars: harmful (left) and safe (right)
        harmful_segs = [
            ("stable_tp",        "Stable TP\n(robustly caught)"),
            ("unstable_harmful", "Unstable\n(borderline harmful)"),
            ("stable_fn",        "Stable FN\n(consistently missed)"),
        ]
        safe_segs = [
            ("stable_tn",    "Stable TN\n(robustly passed)"),
            ("unstable_safe","Unstable\n(borderline safe)"),
            ("stable_fp",    "Stable FP\n(consistently over-blocked)"),
        ]

        for x_pos, segs, total_key in [(0, harmful_segs, "n_harmful"),
                                        (1, safe_segs,    "n_safe")]:
            bottom = 0
            total  = fa[total_key]
            for key, _ in segs:
                val = fa.get(key, 0)
                ax.bar(x_pos, val, bottom=bottom, color=C[key],
                       width=0.5, edgecolor="white", linewidth=0.8)
                if val > 0:
                    pct = val / total * 100
                    ax.text(x_pos, bottom + val / 2,
                            f"{val}\n({pct:.1f}%)",
                            ha="center", va="center",
                            fontsize=8, color="white", fontweight="bold")
                bottom += val

        ax.set_xticks([0, 1])
        ax.set_xticklabels([
            f"Harmful\n(n={fa['n_harmful']})",
            f"Safe\n(n={fa['n_safe']})",
        ], fontsize=10)
        ax.set_ylabel("Number of texts")
        ax.set_title(f"{mk}\n{label}  ({n_runs} runs)", fontsize=10)
        ax.set_ylim(0, max(fa["n_harmful"], fa["n_safe"]) * 1.12)

    # Shared legend
    handles = [
        mpatches.Patch(color=C["stable_tp"],        label="Stable TP — always blocked correctly"),
        mpatches.Patch(color=C["unstable_harmful"], label="Unstable harmful — flipped ≥1 run  →  FNR noise"),
        mpatches.Patch(color=C["stable_fn"],        label="Stable FN — always missed  →  consistent error"),
        mpatches.Patch(color=C["stable_tn"],        label="Stable TN — always passed correctly"),
        mpatches.Patch(color=C["unstable_safe"],    label="Unstable safe — flipped ≥1 run  →  FPR noise"),
        mpatches.Patch(color=C["stable_fp"],        label="Stable FP — always over-blocked  →  consistent error"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2,
               bbox_to_anchor=(0.5, -0.18), fontsize=8, framealpha=0.9)

    fig.suptitle(f"Classification stability across {n_runs} repeated runs", fontsize=12, y=1.01)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved → {out_path.name}")


def main():
    parser = argparse.ArgumentParser(
        description="Compute FPR/FNR statistics and flip counts from repeated benchmark runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("csvs", nargs="+",
                        help="Benchmark CSV files (same condition, different runs). Min 2.")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")
    parser.add_argument("--label", default=None,
                        help="Human-readable label for this condition (default: parent dir name)")
    parser.add_argument("--model", default=None,
                        help="Model key to include (default: all *_verdict columns)")
    parser.add_argument("--export-unstable", action="store_true",
                        help="Save a CSV of texts that flipped verdict across runs, "
                             "with their truth label and per-run verdicts.")
    args = parser.parse_args()

    if len(args.csvs) < 2:
        print("Need at least 2 CSV files to compute statistics.")
        sys.exit(1)

    print(f"\nLoading {len(args.csvs)} CSVs…")
    dfs = []
    for p in args.csvs:
        df = pd.read_csv(p)
        dfs.append(df)
        print(f"  {Path(p).name:<50}  {len(df)} rows")

    vcols = [c for c in dfs[0].columns if c.endswith("_verdict")]
    if not vcols:
        print("No *_verdict columns found in first CSV.")
        sys.exit(1)

    if args.model:
        model_keys = [args.model] if f"{args.model}_verdict" in dfs[0].columns else []
        if not model_keys:
            print(f"Column '{args.model}_verdict' not found.")
            sys.exit(1)
    else:
        model_keys = [c[:-8] for c in vcols]

    label = args.label or Path(args.csvs[0]).parent.name

    result = {
        "label":         label,
        "n_runs":        len(dfs),
        "csv_files":     [str(Path(p).name) for p in args.csvs],
        "models":        {},
        "flip_analysis": {},
    }

    print(f"\nComputing statistics  ({label})…")
    for mk in model_keys:
        vcol = f"{mk}_verdict"
        if any(vcol not in df.columns for df in dfs):
            print(f"  Skipping {mk} — column missing in some runs")
            continue

        fprs, fnrs = [], []
        for df in dfs:
            fpr, fnr = compute_fpr_fnr(df, vcol)
            fprs.append(fpr)
            fnrs.append(fnr)

        result["models"][mk] = {
            "fpr_mean": float(np.nanmean(fprs)),
            "fpr_sd":   float(np.nanstd(fprs, ddof=1)),
            "fnr_mean": float(np.nanmean(fnrs)),
            "fnr_sd":   float(np.nanstd(fnrs, ddof=1)),
            "fpr_runs": [round(v, 6) for v in fprs],
            "fnr_runs": [round(v, 6) for v in fnrs],
        }

        fa = flip_analysis(dfs, vcol)
        if fa:
            result["flip_analysis"][mk] = fa

    # ── Write output ──────────────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  {label}  ({result['n_runs']} runs)\n")
    for mk, m in result["models"].items():
        runs_fpr = "  ".join(f"{v:.4f}" for v in m["fpr_runs"])
        runs_fnr = "  ".join(f"{v:.4f}" for v in m["fnr_runs"])
        print(f"  {mk}")
        print(f"    FPR : {m['fpr_mean']:.4f} ± {m['fpr_sd']:.4f}  [{runs_fpr}]")
        print(f"    FNR : {m['fnr_mean']:.4f} ± {m['fnr_sd']:.4f}  [{runs_fnr}]")

    for mk, fa in result["flip_analysis"].items():
        print(f"\n  Flip analysis ({mk})  —  {fa['n_unstable']}/{fa['n_total']} texts unstable "
              f"({fa['flip_rate']:.1%})")
        print(f"    Harmful  ({fa['n_harmful']} texts)")
        print(f"      Stable TP        : {fa['stable_tp']:4d}  (robustly caught)")
        print(f"      Unstable harmful : {fa['unstable_harmful']:4d}  → FNR run-to-run variance")
        print(f"      Stable FN        : {fa['stable_fn']:4d}  (consistently missed)")
        print(f"    Safe  ({fa['n_safe']} texts)")
        print(f"      Stable TN        : {fa['stable_tn']:4d}  (robustly passed)")
        print(f"      Unstable safe    : {fa['unstable_safe']:4d}  → FPR run-to-run variance")
        print(f"      Stable FP        : {fa['stable_fp']:4d}  (consistently over-blocked)")

    print(f"\nSaved → {out_path}")

    # ── Export unstable texts ─────────────────────────────────────────────────
    if args.export_unstable:
        unstable_path = out_path.with_name(out_path.stem + "_unstable.csv")
        export_unstable(dfs, model_keys, args.csvs, unstable_path)

    # ── Plot ──────────────────────────────────────────────────────────────────
    if result["flip_analysis"]:
        img_dir = Path(__file__).parent.parent / "output-images"
        img_dir.mkdir(exist_ok=True)
        plot_path = img_dir / f"{out_path.stem}_flip_analysis.png"
        plot_flip_analysis(result, plot_path)

    print()


if __name__ == "__main__":
    main()
