"""
compare_prompts.py  —  Cross-prompt comparison for benchmark CSVs.

Takes one CSV per prompt preset and produces:
  1. Side-by-side metrics table (stdout + grouped bar chart)
  2. Policy fingerprint: FP rate vs FN rate scatter + TP/FP/TN/FN stacked bars
  3. Overlap: which combination of prompts correctly blocks each harmful text
  4. Disagreement: where prompts diverge and who was right per ground truth
  +  JSON export of all disagreement cases for manual review

Usage:
    python scripts/compare_prompts.py \\
        output-data/full_claude_x/benchmark_*.csv \\
        output-data/full_claude_truth_social/benchmark_*.csv \\
        output-data/full_claude_bluesky/benchmark_*.csv \\
        [--labels "X" "Truth Social" "Bluesky"] \\
        [--model claude-sonnet] \\
        [--prefix compare_platform]

    # Adversarial comparison (texts differ across CSVs — no inner join):
    python scripts/compare_prompts.py \\
        output-data/.../benchmark_normal.csv \\
        output-data/.../benchmark_typos.csv \\
        output-data/.../benchmark_leet.csv \\
        --labels "Normal" "Typos" "Leet" \\
        --independent \\
        --prefix compare_adversarial
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

POSITIVE = "BLOCK"
NEGATIVE = "ALLOW"

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor":   "white",
    "font.size":        10,
})


# ─── Helpers ──────────────────────────────────────────────────────────────────

def norm_truth(v):
    s = str(v).strip().lower()
    if s in ("harmful", "1", "true", "yes", "block", "hate", "hate_speech"):
        return "BLOCK"
    if s in ("safe", "0", "false", "no", "allow", "not_hate_speech"):
        return "ALLOW"
    return None


def save(fig, out_dir, prefix, name):
    path = out_dir / f"{prefix}_{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved → {path.name}")


def fmt(v, spec=".3f"):
    return f"{v:{spec}}" if isinstance(v, (int, float)) and not np.isnan(v) else "   —  "


def compute_metrics(y_true, y_pred):
    mask = y_true.notna() & y_pred.notna() & (y_pred != "ERROR")
    yt, yp = y_true[mask], y_pred[mask]
    n = len(yt)
    if n == 0:
        nan = float("nan")
        return dict(tp=nan, fp=nan, tn=nan, fn=nan,
                    accuracy=nan, precision=nan, recall=nan, f1=nan, fpr=nan, fnr=nan)
    tp = int(((yt == POSITIVE) & (yp == POSITIVE)).sum())
    fp = int(((yt == NEGATIVE) & (yp == POSITIVE)).sum())
    tn = int(((yt == NEGATIVE) & (yp == NEGATIVE)).sum())
    fn = int(((yt == POSITIVE) & (yp == NEGATIVE)).sum())
    acc  = (tp + tn) / n
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec  = tp / (tp + fn) if (tp + fn) else float("nan")
    f1   = (2 * prec * rec / (prec + rec)
            if not (np.isnan(prec) or np.isnan(rec) or prec + rec == 0)
            else float("nan"))
    fpr  = fp / (fp + tn) if (fp + tn) else float("nan")
    fnr  = fn / (fn + tp) if (fn + tp) else float("nan")
    return dict(tp=tp, fp=fp, tn=tn, fn=fn,
                accuracy=acc, precision=prec, recall=rec, f1=f1, fpr=fpr, fnr=fnr)


def load_csv(path, model_key=None):
    df = pd.read_csv(path)
    vcols = [c for c in df.columns if c.endswith("_verdict")]
    if not vcols:
        raise ValueError(f"No *_verdict columns in {path}")
    key = model_key if (model_key and f"{model_key}_verdict" in df.columns) else vcols[0][:-8]
    out = df[["text", "truth"]].copy()
    out["truth"]   = out["truth"].apply(norm_truth)
    out["verdict"] = df[f"{key}_verdict"]
    return out.dropna(subset=["text"])


def infer_label(path):
    name = Path(path).parent.name.lower()
    if "truth_social" in name: return "Truth Social"
    if "bluesky"      in name: return "Bluesky"
    if "x"  in name.split("_"): return "X"
    if "ethos"   in name: return "ETHOS"
    if "school"  in name: return "School"
    if "general" in name: return "General"
    return Path(path).parent.name or Path(path).stem


# ─── Plot 1: Metrics comparison ───────────────────────────────────────────────

def plot_metrics(mdf, labels, out_dir, prefix):
    cols    = ["accuracy", "precision", "recall", "f1"]
    colours = ["#3b82f6", "#f59e0b", "#10b981", "#a855f7"]
    n = len(labels)
    x = np.arange(n)
    w = 0.18
    offsets = np.linspace(-(len(cols) - 1) / 2, (len(cols) - 1) / 2, len(cols)) * w

    fig, ax = plt.subplots(figsize=(max(7, 1.6 * n), 5))
    for i, (col, colour) in enumerate(zip(cols, colours)):
        vals = [mdf.loc[lbl, col] for lbl in labels]
        bars = ax.bar(x + offsets[i], vals, w, label=col.capitalize(),
                      color=colour, alpha=0.85)
        for bar, val in zip(bars, vals):
            if not np.isnan(val):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.012,
                        f"{val:.3f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Score")
    ax.set_title("Classification metrics by prompt  (BLOCK = positive class)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0, framealpha=0.8)
    ax.axhline(0.5, color="grey", lw=0.6, ls="--", alpha=0.5)
    fig.tight_layout()
    save(fig, out_dir, prefix, "metrics")


# ─── Plot 2: Policy fingerprint ───────────────────────────────────────────────

def plot_policy_fingerprint(mdf, labels, out_dir, prefix,
                            stats_by_label=None, model_key=None):
    """
    Left:  each prompt as a point in FP-rate × FN-rate space.
           FP rate (x) = safe texts incorrectly blocked  (over-censorship)
           FN rate (y) = harmful texts missed            (under-moderation)
           Permissive platforms → top-left.  Strict → bottom-right.
           If stats_by_label is provided, crosshair error bars (±1 SD) are drawn
           and the point is placed at the mean across runs.
    Right: TP / FP / TN / FN stacked bars per prompt.
    """
    colours = plt.cm.tab10(np.linspace(0, 0.9, len(labels)))
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # Left: FPR vs FNR scatter
    ax = axes[0]
    for i, (lbl, colour) in enumerate(zip(labels, colours)):
        stats = (stats_by_label or {}).get(lbl)
        mk    = model_key or ""
        m     = (stats or {}).get("models", {}).get(mk) if stats else None

        if m:
            fpr, fnr = m["fpr_mean"], m["fnr_mean"]
        else:
            fpr = mdf.loc[lbl, "fpr"]
            fnr = mdf.loc[lbl, "fnr"]
        ax.scatter(fpr, fnr, s=70, color=colour, zorder=3)

        right = i > 0
        ax.annotate(lbl, (fpr, fnr), textcoords="offset points",
                    xytext=(9, 5) if right else (-9, 5),
                    ha="left" if right else "right",
                    fontsize=9, color=colour, fontweight="bold")
    ax.set_xlabel("FP rate  —  proportion of safe texts over-blocked")
    ax.set_ylabel("FN rate  —  proportion of harmful texts missed")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_title("Policy fingerprint")
    ax.text(0.02, 0.97, "permissive\n(misses harms, doesn't over-block)",
            transform=ax.transAxes, fontsize=7, color="grey", va="top")
    ax.text(0.98, 0.03, "strict\n(catches harms, but over-blocks)",
            transform=ax.transAxes, fontsize=7, color="grey", ha="right")
    ax.grid(True, alpha=0.3)

    # Borderline zone: rectangle showing max FPR/FNR shift achievable
    # by only flipping unstable (borderline) texts — any point inside
    # this zone may be explainable by stochasticity alone; points outside
    # require stable texts to have flipped (genuine attack effect).
    mk = model_key or ""
    for lbl, colour in zip(labels, colours):
        stats = (stats_by_label or {}).get(lbl)
        m     = (stats or {}).get("models", {}).get(mk) if stats else None
        fa    = (stats or {}).get("flip_analysis", {}).get(mk) if stats else None
        if m and fa and fa.get("n_harmful", 0) > 0 and fa.get("n_safe", 0) > 0:
            fpr_c    = m["fpr_mean"]
            fnr_c    = m["fnr_mean"]
            delta_fpr = fa["unstable_safe"]    / fa["n_safe"]
            delta_fnr = fa["unstable_harmful"] / fa["n_harmful"]
            rect = plt.Rectangle(
                (fpr_c - delta_fpr, fnr_c - delta_fnr),
                2 * delta_fpr, 2 * delta_fnr,
                linewidth=1.2, edgecolor=colour, linestyle="--",
                facecolor=colour, alpha=0.10, zorder=2,
            )
            ax.add_patch(rect)
            ax.annotate(
                "borderline ceiling",
                xy=(fpr_c + delta_fpr, fnr_c),
                textcoords="offset points", xytext=(6, 0),
                fontsize=7, color="grey", va="center",
            )

    # Right: stacked TP/FP/TN/FN
    ax2 = axes[1]
    cats   = [("tp", "TP", "#22c55e"), ("fp", "FP", "#ef4444"),
              ("tn", "TN", "#3b82f6"), ("fn", "FN", "#f59e0b")]
    bottom = np.zeros(len(labels))
    for key, cat, clr in cats:
        vals = np.array([mdf.loc[lbl, key] for lbl in labels], dtype=float)
        ax2.bar(labels, vals, bottom=bottom, color=clr, label=cat, alpha=0.85)
        for i, (val, bot) in enumerate(zip(vals, bottom)):
            if not np.isnan(val) and val > 8:
                ax2.text(i, bot + val / 2, f"{int(val)}",
                         ha="center", va="center", fontsize=8,
                         color="white", fontweight="bold")
        bottom += np.where(np.isnan(vals), 0, vals)
    ax2.set_ylabel("Count")
    ax2.set_title("TP / FP / TN / FN per prompt")
    ax2.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0, framealpha=0.8)

    fig.tight_layout()
    save(fig, out_dir, prefix, "policy_fingerprint")


# ─── Plot 3: Overlap of true positives ────────────────────────────────────────

def plot_overlap(merged, labels, out_dir, prefix):
    """
    For each harmful text: which combination of prompts correctly blocked it?
    Bars sorted by count; green = caught by all, red = missed by all, amber = partial.
    """
    harmful = merged[merged["truth"] == POSITIVE].copy()
    if len(harmful) == 0:
        print("  (no BLOCK ground-truth rows — skipping overlap plot)")
        return

    n_prompts = len(labels)
    for lbl in labels:
        harmful[f"_hit_{lbl}"] = (harmful[lbl] == POSITIVE).astype(int)

    combo_counts = {}
    for _, row in harmful.iterrows():
        key = tuple(int(row[f"_hit_{lbl}"]) for lbl in labels)
        combo_counts[key] = combo_counts.get(key, 0) + 1

    combos = sorted(combo_counts.items(), key=lambda x: -x[1])

    def combo_label(key):
        active = [labels[i] for i, v in enumerate(key) if v]
        if not active:       return "None"
        if len(active) == n_prompts: return "All"
        return " + ".join(active)

    xlabels  = [combo_label(k) for k, _ in combos]
    counts   = [c for _, c in combos]
    bar_clrs = []
    for k, _ in combos:
        s = sum(k)
        bar_clrs.append("#22c55e" if s == n_prompts else "#ef4444" if s == 0 else "#f59e0b")

    fig, ax = plt.subplots(figsize=(max(8, 1.1 * len(combos) + 2), 5))
    bars = ax.bar(xlabels, counts, color=bar_clrs, alpha=0.85, edgecolor="white", linewidth=0.6)
    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.4,
                str(count), ha="center", va="bottom", fontsize=9)
    ax.set_xlabel("Prompts that correctly blocked the text")
    ax.set_ylabel("Number of harmful texts")
    ax.set_title(f"True-positive overlap  ({len(harmful)} harmful texts total)")
    ax.tick_params(axis="x", rotation=15)

    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor="#22c55e", label="Caught by all"),
        Patch(facecolor="#f59e0b", label="Caught by some"),
        Patch(facecolor="#ef4444", label="Missed by all"),
    ], loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0, framealpha=0.8)
    fig.tight_layout()
    save(fig, out_dir, prefix, "overlap")


# ─── Plot 4: Disagreement analysis ────────────────────────────────────────────

def plot_disagreement(merged, labels, out_dir, prefix):
    """
    Texts where not all prompts give the same verdict.
    Left:  disagreement breakdown by ground truth class.
    Right: accuracy on disputed rows per prompt — who makes the better call?
    """
    valid = merged[merged["truth"].notna()].copy()

    valid["_all_agree"] = valid.apply(
        lambda row: len({row[lbl] for lbl in labels if row[lbl] in (POSITIVE, NEGATIVE)}) <= 1,
        axis=1,
    )
    disagree = valid[~valid["_all_agree"]]
    n_total    = len(valid)
    n_disagree = len(disagree)

    if n_disagree == 0:
        print("  All prompts agree on every row — skipping disagreement plot.")
        return pd.DataFrame()

    print(f"  Disagreement on {n_disagree}/{n_total} rows ({n_disagree/n_total:.1%})")
    d_block = disagree[disagree["truth"] == POSITIVE]
    d_allow = disagree[disagree["truth"] == NEGATIVE]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # Left: count breakdown
    ax = axes[0]
    cats   = ["Unanimous", "Disagree\n(truth=harmful)", "Disagree\n(truth=safe)"]
    values = [n_total - n_disagree, len(d_block), len(d_allow)]
    clrs   = ["#3b82f6", "#f59e0b", "#ef4444"]
    bars   = ax.bar(cats, values, color=clrs, alpha=0.85)
    for bar, val in zip(bars, values):
        pct = val / n_total
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{val}\n({pct:.1%})", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Number of texts")
    ax.set_title(f"Disagreement breakdown  (n={n_total})")
    ax.set_ylim(0, max(values) * 1.25)

    # Right: who gets it right on disputed rows?
    ax2 = axes[1]
    colours = plt.cm.tab10(np.linspace(0, 0.9, len(labels)))
    n_right_list = []
    for lbl in labels:
        n_right = int(
            ((disagree["truth"] == POSITIVE) & (disagree[lbl] == POSITIVE)).sum() +
            ((disagree["truth"] == NEGATIVE) & (disagree[lbl] == NEGATIVE)).sum()
        )
        n_right_list.append(n_right)
    bars2 = ax2.bar(labels, n_right_list, color=colours, alpha=0.85)
    for bar, val in zip(bars2, n_right_list):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val}\n({val/n_disagree:.0%})", ha="center", va="bottom", fontsize=9)
    ax2.set_ylim(0, n_disagree * 1.25)
    ax2.axhline(n_disagree / 2, color="grey", lw=0.8, ls="--", alpha=0.6,
                label="50% baseline")
    ax2.set_ylabel("Correct predictions on disputed rows")
    ax2.set_title("Who is right when prompts disagree?")
    ax2.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0,
               fontsize=8, framealpha=0.8)

    fig.tight_layout()
    save(fig, out_dir, prefix, "disagreement")
    return disagree


# ─── JSON export ──────────────────────────────────────────────────────────────

def export_disagreements(disagree, labels, out_dir, prefix):
    if disagree is None or len(disagree) == 0:
        return
    records = []
    for _, row in disagree.iterrows():
        verdicts = {lbl: row[lbl] for lbl in labels if row[lbl] in (POSITIVE, NEGATIVE)}
        correct  = [lbl for lbl in labels if row.get(lbl) == row["truth"]]
        records.append({
            "text":            row["text"],
            "truth":           row["truth"],
            "verdicts":        verdicts,
            "correct_prompts": correct,
        })
    # Harmful misses first (most important), then ties broken by fewest correct prompts
    records.sort(key=lambda r: (r["truth"] != POSITIVE, len(r["correct_prompts"])))

    out_path = out_dir / f"{prefix}_disagreements.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  saved → {out_path.name}  ({len(records)} disagreement cases)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compare benchmark CSVs across different prompt presets."
    )
    parser.add_argument("csvs", nargs="+", help="Benchmark CSV files (one per prompt)")
    parser.add_argument("--labels", nargs="*", default=None,
                        help="Short label for each CSV (default: inferred from parent directory)")
    parser.add_argument("--model", default=None,
                        help="Model key to use from each CSV (default: first verdict column)")
    parser.add_argument("--prefix", default="compare",
                        help="Output filename prefix (default: compare)")
    parser.add_argument("--independent", action="store_true",
                        help="Compute metrics per CSV without aligning on shared texts. "
                             "Use when comparing adversarial variants where text content differs. "
                             "Produces only metrics and fingerprint plots (overlap/disagreement "
                             "require row-aligned texts).")
    parser.add_argument("--stats", nargs="*", default=None, metavar="JSON",
                        help="Stats JSON files from compute_benchmark_stats.py, one per CSV "
                             "(positionally matched). Adds crosshair error bars (±1 SD) to "
                             "the fingerprint scatter for conditions that have stats.")
    args = parser.parse_args()

    if len(args.csvs) < 2:
        print("Provide at least 2 CSV files to compare.")
        sys.exit(1)

    labels = args.labels or [infer_label(p) for p in args.csvs]
    if len(labels) != len(args.csvs):
        print(f"--labels count ({len(labels)}) must match CSV count ({len(args.csvs)})")
        sys.exit(1)

    out_dir = Path(__file__).parent.parent / "output-images"
    out_dir.mkdir(exist_ok=True)

    # ── Load ──────────────────────────────────────────────────────────────────
    print(f"\nLoading {len(args.csvs)} CSVs…")
    dfs = []
    for path, label in zip(args.csvs, labels):
        df = load_csv(path, args.model)
        df = df.rename(columns={"verdict": label})
        print(f"  {label:<20}  {len(df)} rows  ({Path(path).name})")
        dfs.append(df)

    if args.independent:
        # ── Independent mode: metrics per CSV, no text alignment ──────────────
        print("\n  --independent: computing metrics per CSV without text alignment")
        metric_rows = {lbl: compute_metrics(df["truth"], df[lbl])
                       for df, lbl in zip(dfs, labels)}
    else:
        # ── Aligned mode: inner join on shared texts ───────────────────────────
        merged = dfs[0][["text", "truth", labels[0]]].copy()
        for df, label in zip(dfs[1:], labels[1:]):
            merged = merged.merge(df[["text", label]], on="text", how="inner")

        n = len(merged)
        print(f"\n  {n} rows in common across all CSVs")
        if n == 0:
            print("No overlapping texts — use --independent for adversarial comparisons.")
            sys.exit(1)

        metric_rows = {lbl: compute_metrics(merged["truth"], merged[lbl]) for lbl in labels}

    mdf = pd.DataFrame(metric_rows).T

    # ── Metrics table ─────────────────────────────────────────────────────────
    col_w = max(len(lbl) for lbl in labels) + 2
    header = f"{'Prompt':<{col_w}} {'Acc':>7} {'Prec':>7} {'Rec':>7} {'F1':>7}  {'TP':>5} {'FP':>5} {'TN':>5} {'FN':>5}  {'FPR':>7} {'FNR':>7}"
    print(f"\n{header}")
    print("─" * len(header))
    for lbl in labels:
        m = metric_rows[lbl]
        tp_s = f"{int(m['tp']):5d}" if not np.isnan(m['tp']) else "  nan"
        fp_s = f"{int(m['fp']):5d}" if not np.isnan(m['fp']) else "  nan"
        tn_s = f"{int(m['tn']):5d}" if not np.isnan(m['tn']) else "  nan"
        fn_s = f"{int(m['fn']):5d}" if not np.isnan(m['fn']) else "  nan"
        print(f"{lbl:<{col_w}} {fmt(m['accuracy']):>7} {fmt(m['precision']):>7} "
              f"{fmt(m['recall']):>7} {fmt(m['f1']):>7}  "
              f"{tp_s} {fp_s} {tn_s} {fn_s}  "
              f"{fmt(m['fpr']):>7} {fmt(m['fnr']):>7}")

    # ── Load stats JSONs (optional) ───────────────────────────────────────────
    stats_by_label = {}
    if args.stats:
        for label, stats_path in zip(labels, args.stats):
            try:
                with open(stats_path) as f:
                    stats_by_label[label] = json.load(f)
                n_runs = stats_by_label[label].get("n_runs", "?")
                print(f"  Stats loaded for '{label}': {n_runs} runs  ({Path(stats_path).name})")
            except FileNotFoundError:
                print(f"  Warning: stats file not found for '{label}': {stats_path}")

    # Determine effective model key (for stats lookup)
    effective_model = args.model
    if not effective_model:
        vcols = [c for c in pd.read_csv(args.csvs[0]).columns if c.endswith("_verdict")]
        effective_model = vcols[0][:-8] if vcols else ""

    # ── Plots ─────────────────────────────────────────────────────────────────
    print(f"\nPlotting…")
    prefix = args.prefix
    plot_metrics(mdf, labels, out_dir, prefix)
    plot_policy_fingerprint(mdf, labels, out_dir, prefix,
                            stats_by_label=stats_by_label or None,
                            model_key=effective_model)

    if not args.independent:
        plot_overlap(merged, labels, out_dir, prefix)
        disagree = plot_disagreement(merged, labels, out_dir, prefix)
        export_disagreements(disagree, labels, out_dir, prefix)
    else:
        print("  (overlap and disagreement plots skipped in --independent mode)")

    n_plots = len(list(out_dir.glob(f"{prefix}_*.png")))
    print(f"\nDone. {n_plots} images → {out_dir}/")


if __name__ == "__main__":
    main()
