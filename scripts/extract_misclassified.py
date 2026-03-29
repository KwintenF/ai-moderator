"""
extract_misclassified.py  —  Extract false negatives from benchmark CSV output.

A false negative is a row where truth=BLOCK (harmful) but a model predicted ALLOW.
Output is a JSON file per model (and one combined file) ready for re-benchmarking
or manual review.

Usage:
    python scripts/extract_misclassified.py output-data/benchmark_2026-03-22-19-14.csv
    python scripts/extract_misclassified.py output-data/benchmark_*.csv --models claude-sonnet
    python scripts/extract_misclassified.py output-data/results.csv --also-errors

Output:
    output-data/<stem>_fn_<model>.json      one file per model
    output-data/<stem>_fn_combined.json     union across all models (any model missed it)
    output-data/<stem>_fn_summary.txt       counts and rates
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def norm_truth(value) -> str | None:
    s = str(value).strip().lower()
    if s in ("harmful", "1", "true", "yes", "block"):
        return "BLOCK"
    if s in ("safe", "0", "false", "no", "allow"):
        return "ALLOW"
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Extract false negatives (truth=BLOCK, predicted=ALLOW) from benchmark CSV."
    )
    parser.add_argument("csv", nargs="+", help="Benchmark CSV file(s)")
    parser.add_argument(
        "--models", nargs="*", default=None,
        help="Limit to these model keys (default: all models in the CSV)"
    )
    parser.add_argument(
        "--also-errors", action="store_true",
        help="Also include rows where truth=BLOCK and model returned ERROR"
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Directory for output files (default: same directory as input CSV)"
    )
    args = parser.parse_args()

    for csv_path_str in args.csv:
        csv_path = Path(csv_path_str).resolve()
        if not csv_path.exists():
            print(f"Error: not found: {csv_path}", file=sys.stderr)
            continue

        out_dir = Path(args.output_dir).resolve() if args.output_dir else csv_path.parent
        stem = csv_path.stem

        df = pd.read_csv(csv_path)
        df["truth_norm"] = df["truth"].apply(norm_truth)

        verdict_cols = [c for c in df.columns if c.endswith("_verdict")]
        model_keys   = [c[: -len("_verdict")] for c in verdict_cols]

        if args.models:
            model_keys   = [k for k in model_keys if k in args.models]
            verdict_cols = [f"{k}_verdict" for k in model_keys]

        if not model_keys:
            print(f"No matching model columns in {csv_path.name}", file=sys.stderr)
            continue

        # Only rows where truth is known and is BLOCK
        harmful_mask = df["truth_norm"] == "BLOCK"
        harmful_df   = df[harmful_mask].copy()
        n_harmful    = len(harmful_df)

        if n_harmful == 0:
            print(f"{csv_path.name}: no BLOCK rows found — nothing to extract.")
            continue

        print(f"\n{csv_path.name}  ({n_harmful} harmful rows, {len(df)} total)")

        missed_allowed = "ALLOW"
        missed_values  = {"ALLOW", "ERROR"} if args.also_errors else {"ALLOW"}

        per_model_rows: dict[str, list[dict]] = {}
        summary_lines: list[str] = []

        for model_key, verdict_col in zip(model_keys, verdict_cols):
            fn_mask = harmful_df[verdict_col].isin(missed_values)
            fn_df   = harmful_df[fn_mask]
            n_fn    = len(fn_df)
            rate    = n_fn / n_harmful if n_harmful > 0 else 0.0

            label = f"  {model_key:<30s}  {n_fn:4d} / {n_harmful}  ({rate:.1%} miss rate)"
            print(label)
            summary_lines.append(label)

            rows = []
            for _, row in fn_df.iterrows():
                entry = {
                    "text":    row["text"],
                    "truth":   "harmful",
                    "source":  row.get("source", ""),
                    "missed_by": model_key,
                    "predicted": row[verdict_col],
                    "confidence": row.get(f"{model_key}_confidence", None),
                    "reason":    row.get(f"{model_key}_reason", None),
                }
                # carry over originalText and attack metadata if present (adversarial inputs)
                if "originalText" in df.columns:
                    entry["originalText"] = row.get("originalText", None)
                if "attack" in df.columns:
                    entry["attack"] = row.get("attack", None)
                rows.append(entry)

            per_model_rows[model_key] = rows

            if rows:
                out_path = out_dir / f"{stem}_fn_{model_key}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(rows, f, ensure_ascii=False, indent=2)
                print(f"    → {out_path.name}")

        # Combined: rows missed by at least one model (union, deduplicated by text)
        seen_texts: set[str] = set()
        combined: list[dict] = []
        for model_key, rows in per_model_rows.items():
            for row in rows:
                t = row["text"]
                if t not in seen_texts:
                    seen_texts.add(t)
                    # note all models that missed this row
                    row = dict(row)
                    row["missed_by"] = [
                        mk for mk, mr in per_model_rows.items()
                        if any(r["text"] == t for r in mr)
                    ]
                    combined.append(row)

        # Sort by number of models that missed it (most-missed first)
        combined.sort(key=lambda r: len(r["missed_by"]), reverse=True)

        if combined:
            combined_path = out_dir / f"{stem}_fn_combined.json"
            with open(combined_path, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, indent=2)
            print(f"\n  Combined ({len(combined)} unique texts missed by ≥1 model) → {combined_path.name}")

        # Summary text file
        summary_path = out_dir / f"{stem}_fn_summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"False negative summary: {csv_path.name}\n")
            f.write(f"Harmful rows in dataset: {n_harmful} / {len(df)}\n")
            f.write(f"Mode: {'ALLOW + ERROR' if args.also_errors else 'ALLOW only'}\n\n")
            f.write("Model                          FN    / harmful   miss rate\n")
            f.write("-" * 55 + "\n")
            for line in summary_lines:
                f.write(line.strip() + "\n")
            f.write(f"\nUnion (≥1 model missed):  {len(combined)}\n")
        print(f"  Summary → {summary_path.name}")

    print()


if __name__ == "__main__":
    main()
