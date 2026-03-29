"""
analyse_results.py  —  Visualise benchmark CSV output from claude-moderator.

Usage:
    python scripts/analyse_results.py <path/to/results.csv>

All plots are saved to output-images/ with the CSV stem as filename prefix.
Requires: pandas, matplotlib, seaborn, scikit-learn
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                   # headless — no display needed
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import confusion_matrix

# ─── Config ───────────────────────────────────────────────────────────────────

VERDICT_COLOURS = {
    "BLOCK": "#ef4444",
    "ALLOW": "#22c55e",
    "ERROR": "#94a3b8",
}
METRICS  = ["accuracy", "precision", "recall", "f1"]
POSITIVE = "BLOCK"
NEGATIVE = "ALLOW"

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor":   "white",
    "font.size":        10,
})

# ─── Helpers ──────────────────────────────────────────────────────────────────

def norm_truth(value) -> str | None:
    s = str(value).strip().lower()
    if s in ("harmful", "1", "true", "yes", "block", "hate", "hate_speech"):
        return "BLOCK"
    if s in ("safe", "0", "false", "no", "allow", "not_hate_speech"):
        return "ALLOW"
    return None


def compute_metrics(y_true: pd.Series, y_pred: pd.Series) -> dict:
    """
    Binary metrics treating BLOCK as positive.
    Rows where either value is ERROR or NaN are excluded.
    """
    mask = (
        y_true.notna() & y_pred.notna() &
        (y_true != "ERROR") & (y_pred != "ERROR")
    )
    yt = y_true[mask]
    yp = y_pred[mask]
    n_valid = len(yt)
    n_total = len(y_true)

    if n_valid == 0:
        return {m: float("nan") for m in METRICS} | {"error_rate": float("nan"), "n_valid": 0}

    tp = ((yt == POSITIVE) & (yp == POSITIVE)).sum()
    fp = ((yt == NEGATIVE) & (yp == POSITIVE)).sum()
    tn = ((yt == NEGATIVE) & (yp == NEGATIVE)).sum()
    fn = ((yt == POSITIVE) & (yp == NEGATIVE)).sum()

    accuracy  = (tp + tn) / n_valid
    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall    = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    f1        = (2 * precision * recall / (precision + recall)
                 if not (np.isnan(precision) or np.isnan(recall) or precision + recall == 0)
                 else float("nan"))
    error_rate = (y_pred == "ERROR").sum() / n_total if n_total > 0 else float("nan")

    return dict(accuracy=accuracy, precision=precision, recall=recall,
                f1=f1, error_rate=error_rate, n_valid=n_valid)


def save(fig: plt.Figure, out_dir: Path, prefix: str, name: str):
    path = out_dir / f"{prefix}_{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved → {path.name}")


# ─── Plot 1: Verdict distribution ─────────────────────────────────────────────

def plot_verdict_distribution(df, verdict_cols, model_labels, out_dir, prefix):
    """Horizontal stacked bar: BLOCK / ALLOW / ERROR count per model."""
    counts = []
    for col in verdict_cols:
        vc = df[col].fillna("ERROR").value_counts()
        counts.append({v: vc.get(v, 0) for v in ("BLOCK", "ALLOW", "ERROR")})

    data   = pd.DataFrame(counts, index=model_labels)
    totals = data.sum(axis=1)

    fig, ax = plt.subplots(figsize=(9, max(3, 0.55 * len(model_labels) + 1.5)))
    left = np.zeros(len(data))
    for verdict in ("BLOCK", "ALLOW", "ERROR"):
        vals = data[verdict].values
        ax.barh(model_labels, vals, left=left,
                color=VERDICT_COLOURS[verdict], label=verdict, height=0.6)
        left += vals

    # Percentage labels inside bars
    for i, (row, total) in enumerate(zip(counts, totals)):
        x = 0
        for verdict in ("BLOCK", "ALLOW", "ERROR"):
            v = row[verdict]
            if v > 0 and v / total > 0.04:
                ax.text(x + v / 2, i, f"{v / total:.0%}",
                        ha="center", va="center",
                        fontsize=8, color="white", fontweight="bold")
            x += v

    ax.set_xlabel("Count")
    ax.set_title("Verdict distribution per model")
    ax.legend(loc="lower right", framealpha=0.8)
    ax.invert_yaxis()
    fig.tight_layout()
    save(fig, out_dir, prefix, "verdict_distribution")


# ─── Plot 2: Metrics vs ground truth ──────────────────────────────────────────

def plot_metrics_vs_truth(df, verdict_cols, model_labels, truth_col, out_dir, prefix):
    """Grouped bar: accuracy / precision / recall / F1 per model vs ground truth."""
    rows = []
    for col, label in zip(verdict_cols, model_labels):
        m = compute_metrics(df[truth_col], df[col])
        rows.append({"model": label, **{k: m[k] for k in METRICS}})

    data = pd.DataFrame(rows).set_index("model")
    n    = len(data)
    x    = np.arange(n)
    w    = 0.18
    offs = np.linspace(-(len(METRICS) - 1) / 2, (len(METRICS) - 1) / 2, len(METRICS)) * w
    clrs = ["#3b82f6", "#f59e0b", "#10b981", "#a855f7"]

    fig, ax = plt.subplots(figsize=(max(7, 1.2 * n), 5))
    for i, (metric, colour) in enumerate(zip(METRICS, clrs)):
        vals = data[metric].values
        bars = ax.bar(x + offs[i], vals, w, label=metric.capitalize(),
                      color=colour, alpha=0.85)
        for bar, val in zip(bars, vals):
            if not np.isnan(val):
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.01,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=7)

    ax.set_xticks(x)
    ax.set_xticklabels(data.index, rotation=25, ha="right", fontsize=9)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Score")
    ax.set_title("Classification metrics vs ground truth  (BLOCK = positive)")
    ax.legend(loc="upper right", framealpha=0.8)
    ax.axhline(0.5, color="grey", linewidth=0.6, linestyle="--", alpha=0.5)
    fig.tight_layout()
    save(fig, out_dir, prefix, "metrics_vs_truth")


# ─── Plot 3: Confusion matrices vs ground truth ───────────────────────────────

def plot_confusion_matrices(df, verdict_cols, model_labels, truth_col, out_dir, prefix):
    """Multi-panel confusion matrix heatmaps, one per model."""
    n     = len(verdict_cols)
    ncols = min(n, 4)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols,
                              figsize=(4.2 * ncols, 3.8 * nrows))
    axes = np.array(axes).reshape(-1)

    order = [POSITIVE, NEGATIVE, "ERROR"]

    for ax, col, label in zip(axes, verdict_cols, model_labels):
        mask = df[truth_col].notna()
        yt   = df.loc[mask, truth_col].fillna("ERROR")
        yp   = df.loc[mask, col].fillna("ERROR")

        present = [v for v in order if v in set(yt) | set(yp)]
        cm      = confusion_matrix(yt, yp, labels=present)
        cm_norm = cm.astype(float) / cm.sum(axis=1, keepdims=True).clip(min=1)

        sns.heatmap(cm_norm, annot=cm, fmt="d", ax=ax,
                    xticklabels=present, yticklabels=present,
                    cmap="Blues", vmin=0, vmax=1,
                    linewidths=0.5, cbar=False)
        ax.set_title(label, fontsize=9, fontweight="bold")
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")

    for ax in axes[n:]:
        ax.set_visible(False)

    fig.suptitle("Confusion matrices vs ground truth", fontsize=12, y=1.01)
    fig.tight_layout()
    save(fig, out_dir, prefix, "confusion_matrices")


# ─── Plot 4: Pairwise agreement ───────────────────────────────────────────────

def plot_pairwise_agreement(df, all_cols, all_labels, out_dir, prefix):
    """
    Symmetric heatmap of pairwise agreement rate.
    Rows/cols where both predictions are non-ERROR are used.
    """
    n      = len(all_cols)
    matrix = np.full((n, n), float("nan"))

    for i in range(n):
        for j in range(n):
            a    = df[all_cols[i]]
            b    = df[all_cols[j]]
            mask = a.notna() & b.notna() & (a != "ERROR") & (b != "ERROR")
            if mask.sum() > 0:
                matrix[i, j] = (a[mask] == b[mask]).mean()

    fig, ax = plt.subplots(figsize=(max(5, 0.7 * n + 2), max(4, 0.65 * n + 1.5)))
    im = ax.imshow(matrix, vmin=0, vmax=1, cmap="RdYlGn", aspect="auto")
    plt.colorbar(im, ax=ax, label="Agreement rate")

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(all_labels, rotation=35, ha="right", fontsize=8)
    ax.set_yticklabels(all_labels, fontsize=8)

    for i in range(n):
        for j in range(n):
            v = matrix[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                        fontsize=8,
                        color="black" if 0.25 < v < 0.75 else "white")

    ax.set_title("Pairwise agreement rate  (non-ERROR rows only)")
    fig.tight_layout()
    save(fig, out_dir, prefix, "pairwise_agreement")


# ─── Plot 5: Model-vs-model metric heatmaps ───────────────────────────────────

def plot_model_vs_model(df, verdict_cols, model_labels, out_dir, prefix):
    """
    2×2 grid of n×n heatmaps — one per metric (accuracy, precision, recall, F1).
    Cell (row=i, col=j) = metric when model i is treated as ground truth
    and model j is the predictor.

    Diagonal is always 1.0 (a model perfectly agrees with itself).
    Asymmetry is meaningful: precision of j w.r.t. i ≠ recall of j w.r.t. i.

    Interpretation:
      - High precision(i→j): when j says BLOCK, i agrees it's BLOCK
      - High recall(i→j):    j catches most of what i calls BLOCK
      - High F1(i→j):        j is a good proxy for i's judgment
    """
    n      = len(verdict_cols)
    metric_matrices = {m: np.full((n, n), float("nan")) for m in METRICS}

    for i, col_true in enumerate(verdict_cols):
        for j, col_pred in enumerate(verdict_cols):
            m = compute_metrics(df[col_true], df[col_pred])
            for metric in METRICS:
                metric_matrices[metric][i, j] = m[metric]

    fig, axes = plt.subplots(2, 2, figsize=(5.5 * 2, 5 * 2))
    axes = axes.flatten()

    for ax, metric in zip(axes, METRICS):
        mat = metric_matrices[metric]
        im  = ax.imshow(mat, vmin=0, vmax=1, cmap="RdYlGn", aspect="auto")
        plt.colorbar(im, ax=ax, shrink=0.85)

        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(model_labels, rotation=35, ha="right", fontsize=8)
        ax.set_yticklabels(model_labels, fontsize=8)
        ax.set_xlabel("Predictor model", fontsize=9)
        ax.set_ylabel("Reference model (treated as truth)", fontsize=9)
        ax.set_title(metric.capitalize(), fontsize=11, fontweight="bold")

        for i in range(n):
            for j in range(n):
                v = mat[i, j]
                if not np.isnan(v):
                    ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                            fontsize=8,
                            color="black" if 0.25 < v < 0.75 else "white")

    fig.suptitle(
        "Model-vs-model classification metrics\n"
        "Row = reference (truth), Column = predictor  |  BLOCK = positive class",
        fontsize=11, y=1.01,
    )
    fig.tight_layout()
    save(fig, out_dir, prefix, "model_vs_model")


# ─── Plot 6: Error rates ──────────────────────────────────────────────────────

def plot_error_rates(df, verdict_cols, model_labels, out_dir, prefix):
    """Horizontal bar: ERROR / missing rate per model."""
    rates = [
        (df[col].isna() | (df[col] == "ERROR")).sum() / len(df)
        for col in verdict_cols
    ]

    fig, ax = plt.subplots(figsize=(7, max(3, 0.5 * len(model_labels) + 1.5)))
    colours = ["#ef4444" if r > 0.15 else "#f97316" if r > 0.05 else "#22c55e"
               for r in rates]
    bars = ax.barh(model_labels, rates, color=colours, height=0.55)
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_width() + 0.005,
                bar.get_y() + bar.get_height() / 2,
                f"{rate:.1%}", va="center", fontsize=8)
    ax.set_xlim(0, max(max(rates) * 1.3, 0.12))
    ax.set_xlabel("Error / missing rate")
    ax.set_title("API error rate per model")
    ax.invert_yaxis()
    ax.axvline(0.05, color="orange", linewidth=0.8, linestyle="--",
               alpha=0.7, label="5% threshold")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save(fig, out_dir, prefix, "error_rates")


# ─── Plot 7: Latency ──────────────────────────────────────────────────────────

def plot_latency(df, model_keys, model_labels, out_dir, prefix):
    """Box plot of latency per model."""
    latency_data = {}
    for key, label in zip(model_keys, model_labels):
        col = f"{key}_latency_ms"
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(vals) > 0:
                latency_data[label] = vals.values

    if not latency_data:
        return

    labels = list(latency_data.keys())
    values = [latency_data[k] / 1000 for k in labels]   # ms → s

    fig, ax = plt.subplots(figsize=(max(6, 1.1 * len(labels)), 5))
    bp = ax.boxplot(values, patch_artist=True,
                    medianprops=dict(color="black", linewidth=2))
    colours = plt.cm.tab10(np.linspace(0, 0.9, len(labels)))
    for patch, colour in zip(bp["boxes"], colours):
        patch.set_facecolor(colour)
        patch.set_alpha(0.7)

    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=9)
    ax.set_ylabel("Latency (s)")
    ax.set_title("API latency per model")
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    save(fig, out_dir, prefix, "latency")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyse_results.py <results.csv>")
        sys.exit(1)

    csv_path = Path(sys.argv[1]).resolve()
    if not csv_path.exists():
        print(f"Error: file not found: {csv_path}")
        sys.exit(1)

    out_dir = Path(__file__).parent.parent / "output-images"
    out_dir.mkdir(exist_ok=True)

    prefix = csv_path.stem
    print(f"\nAnalysing: {csv_path.name}  →  prefix '{prefix}'")

    df = pd.read_csv(csv_path)
    print(f"  {len(df)} rows, {len(df.columns)} columns")

    verdict_cols = [c for c in df.columns if c.endswith("_verdict")]
    model_keys   = [c[: -len("_verdict")] for c in verdict_cols]
    model_labels = [k.replace("-", " ").replace("_", " ").title() for k in model_keys]

    if not verdict_cols:
        print("No '*_verdict' columns found — nothing to plot.")
        sys.exit(0)

    print(f"  Models found: {model_labels}")

    has_truth = "truth" in df.columns
    if has_truth:
        df["truth_verdict"] = df["truth"].apply(norm_truth)
        n_truth = df["truth_verdict"].notna().sum()
        print(f"  Ground-truth rows: {n_truth} / {len(df)}")
    else:
        print("  No 'truth' column — skipping ground-truth plots.")

    print("\nPlotting…")

    # 1. Verdict distribution
    plot_verdict_distribution(df, verdict_cols, model_labels, out_dir, prefix)

    # 2–3. Metrics + confusion matrices vs ground truth
    if has_truth and df["truth_verdict"].notna().any():
        plot_metrics_vs_truth(df, verdict_cols, model_labels,
                              "truth_verdict", out_dir, prefix)
        plot_confusion_matrices(df, verdict_cols, model_labels,
                                "truth_verdict", out_dir, prefix)
        plot_pairwise_agreement(df,
                                ["truth_verdict"] + verdict_cols,
                                ["Truth"] + model_labels,
                                out_dir, prefix)
    else:
        plot_pairwise_agreement(df, verdict_cols, model_labels, out_dir, prefix)

    # 5. Model-vs-model (only meaningful with ≥2 models)
    if len(verdict_cols) >= 2:
        plot_model_vs_model(df, verdict_cols, model_labels, out_dir, prefix)

    # 6. Error rates
    plot_error_rates(df, verdict_cols, model_labels, out_dir, prefix)

    # 7. Latency
    plot_latency(df, model_keys, model_labels, out_dir, prefix)

    print(f"\nDone. {len(list(out_dir.glob(prefix + '_*.png')))} images saved to {out_dir}/")


if __name__ == "__main__":
    main()
