#!/usr/bin/env python3
"""Leakage-safe train/val/test splitter for claude-all-in-one-plugin.

Splits a (cleaned) tabular dataset into train/val/test using a method chosen to
avoid the common leakage traps:
  - temporal : sort by a time column, train=past / val,test=future (no random)
  - group    : keep every row of an entity (user, VIN, patient...) in ONE split
  - random   : i.i.d. random split, stratified on the target for classification

READ-ONLY on the input file; writes new split files + split_report.md.
Never overwrites the source.
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

SUPPORTED = (".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".json")


def load(path, sheet=None):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, sheet_name=sheet or 0)
    if ext == ".json":
        return pd.read_json(path)
    raise SystemExit(f"Unsupported file type: {ext} (supported: {', '.join(SUPPORTED)})")


def write(df, path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)


def infer_task(y):
    """Classification if few distinct non-float values, else regression."""
    if y is None:
        return "unknown"
    yc = y.dropna()
    # fractional float values are always regression (kept identical to baseline/train-tune)
    if pd.api.types.is_float_dtype(y) and len(yc) and not np.all(np.mod(yc, 1) == 0):
        return "regression"
    nun = y.nunique(dropna=True)
    if pd.api.types.is_float_dtype(y) and nun > 20:
        return "regression"
    if nun <= max(20, int(0.05 * len(y))):
        return "classification"
    return "regression"


def temporal_split(df, time_col, r):
    s = df.sort_values(time_col, kind="mergesort")
    n = len(s)
    n_tr = int(round(n * r[0]))
    n_va = int(round(n * r[1]))
    return s.iloc[:n_tr], s.iloc[n_tr:n_tr + n_va], s.iloc[n_tr + n_va:]


def group_split(df, groups, r, seed):
    from sklearn.model_selection import GroupShuffleSplit
    if groups.nunique() < 3:
        raise SystemExit(f"Group split needs ≥3 distinct groups for train/val/test; found {groups.nunique()}. "
                         "Use more groups or a random split.")
    gss1 = GroupShuffleSplit(n_splits=1, test_size=r[1] + r[2], random_state=seed)
    tr_idx, tmp_idx = next(gss1.split(df, groups=groups))
    train, tmp = df.iloc[tr_idx], df.iloc[tmp_idx]
    tmp_groups = groups.iloc[tmp_idx]
    if tmp_groups.nunique() < 2:
        raise SystemExit(f"Too few distinct groups ({groups.nunique()}) to populate both val and test in a 3-way "
                         "group split. Use more groups, or a random split.")
    test_frac = r[2] / (r[1] + r[2])
    gss2 = GroupShuffleSplit(n_splits=1, test_size=test_frac, random_state=seed)
    va_idx, te_idx = next(gss2.split(tmp, groups=tmp_groups))
    return train, tmp.iloc[va_idx], tmp.iloc[te_idx]


def random_split(df, y, r, seed, stratify):
    from sklearn.model_selection import train_test_split

    def split2(frame, strat, size):  # retry without stratify if a tiny class makes it impossible
        try:
            return train_test_split(frame, test_size=size, random_state=seed, stratify=strat)
        except ValueError:
            if strat is None:
                raise
            print("WARN: stratification failed (class too small for the split); splitting without stratify.", file=sys.stderr)
            return train_test_split(frame, test_size=size, random_state=seed, stratify=None)

    train, tmp = split2(df, y if stratify else None, r[1] + r[2])
    strat2 = tmp[y.name] if (stratify and y is not None) else None
    val, test = split2(tmp, strat2, r[2] / (r[1] + r[2]))
    return train, val, test


def class_balance(splits, target):
    rows = []
    for name, d in splits.items():
        vc = d[target].value_counts(normalize=True).sort_index()
        rows.append((name, {str(k): f"{v:.1%}" for k, v in vc.items()}))
    classes = sorted({c for _, m in rows for c in m})
    header = "| split | " + " | ".join(classes) + " |"
    sep = "|" + "---|" * (len(classes) + 1)
    body = "\n".join("| " + n + " | " + " | ".join(m.get(c, "-") for c in classes) + " |" for n, m in rows)
    return "\n".join([header, sep, body])


def target_stats(splits, target):
    header = "| split | count | mean | std | min | max |"
    sep = "|---|---|---|---|---|---|"
    body = []
    for name, d in splits.items():
        s = d[target]
        body.append(f"| {name} | {len(d):,} | {s.mean():.3g} | {s.std():.3g} | {s.min():.3g} | {s.max():.3g} |")
    return "\n".join([header, sep] + body)


def build_report(args, df_n, splits, method, task, dup_n, dropped_dups, group_overlap, target):
    n = sum(len(d) for d in splits.values())
    pct = {k: len(v) / n for k, v in splits.items()}
    mermaid = "\n".join([
        "```mermaid",
        "flowchart LR",
        f'    D["dataset<br/>{n:,} rows"] --> TR["train<br/>{len(splits["train"]):,} ({pct["train"]:.0%})"]',
        f'    D --> VA["val<br/>{len(splits["val"]):,} ({pct["val"]:.0%})"]',
        f'    D --> TE["test<br/>{len(splits["test"]):,} ({pct["test"]:.0%})"]',
        "```",
    ])
    if task == "classification" and target:
        dist = "### Class balance per split\n" + class_balance(splits, target)
    elif target:
        dist = "### Target distribution per split\n" + target_stats(splits, target)
    else:
        dist = "_No target column given — distribution check skipped._"

    checks = [
        f"- **No row overlap between splits:** {'✅ verified' if _disjoint(splits) else '❌ OVERLAP FOUND'}",
        f"- **Full-duplicate rows in source:** {dup_n:,}" + (f" → dropped before split ✅" if dropped_dups else (" → **NOT dropped** (risk: same row in train & test)" if dup_n else "")),
    ]
    if method == "group":
        checks.append(f"- **Group/entity overlap across splits (`{args.group}`):** {'✅ none' if not group_overlap else f'❌ {group_overlap} shared groups'}")
    if method == "temporal":
        checks.append(f"- **Temporal order (`{args.time}`):** train = earliest, test = latest ✅ (no future→past leakage)")

    return f"""# Split report — {os.path.basename(args.input)}

> Produced by `split-dataset`. Source file was **not** modified.

## At a glance
{mermaid}

- **Method:** `{method}`  ·  **Task:** `{task}`  ·  **Seed:** `{args.seed}`  ·  **Ratios (train/val/test):** {args.ratios}
- **Output dir:** `{args.out_dir}`

## Leakage checks
{chr(10).join(checks)}

{dist}

## ⚠️ Downstream discipline (do NOT skip)
Fit every transform — scalers, encoders, imputers, target encoders, vectorizers —
**on `train` ONLY**, then apply (transform) to `val`/`test`. Fitting on the full
data before/after splitting leaks val/test statistics into training and inflates
your metrics. The split files keep this possible; preserving it is on the modeling step.
"""


def _disjoint(splits):
    idx = [set(d.index) for d in splits.values()]
    return len(idx[0] | idx[1] | idx[2]) == sum(len(s) for s in idx)


def main():
    p = argparse.ArgumentParser(description="Leakage-safe train/val/test split.")
    p.add_argument("input", help="path to the (cleaned) dataset")
    p.add_argument("--target", help="target column (enables stratify / distribution checks)")
    p.add_argument("--task", choices=["auto", "classification", "regression"], default="auto")
    p.add_argument("--group", help="entity column to keep within one split (group-aware split)")
    p.add_argument("--time", help="time column for a temporal split (train=past, test=future)")
    p.add_argument("--ratios", default="0.7,0.15,0.15", help="train,val,test (sum≈1)")
    p.add_argument("--stratify", choices=["auto", "on", "off"], default="auto")
    p.add_argument("--drop-duplicates", action="store_true", help="drop full-duplicate rows before split")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--sheet", default=None)
    args = p.parse_args()

    r = [float(x) for x in args.ratios.split(",")]
    if len(r) != 3 or abs(sum(r) - 1.0) > 1e-6:
        raise SystemExit(f"--ratios must be 3 numbers summing to 1, got {args.ratios}")

    df = load(args.input, args.sheet)
    df = df.reset_index(drop=True)
    base, ext = os.path.splitext(args.input)
    args.out_dir = args.out_dir or (base + "_splits")
    os.makedirs(args.out_dir, exist_ok=True)

    dup_n = int(df.duplicated().sum())
    if args.drop_duplicates and dup_n:
        df = df.drop_duplicates().reset_index(drop=True)

    y = df[args.target] if args.target and args.target in df.columns else None
    task = args.task if args.task != "auto" else infer_task(y)

    if args.time and args.time in df.columns:
        method = "temporal"
        train, val, test = temporal_split(df, args.time, r)
    elif args.group and args.group in df.columns:
        method = "group"
        train, val, test = group_split(df, df[args.group], r, args.seed)
    else:
        method = "random"
        stratify = (args.stratify == "on") or (args.stratify == "auto" and task == "classification" and y is not None)
        if stratify and y is not None and y.isna().any():
            print("WARN: target has missing values; disabling stratification.", file=sys.stderr)
            stratify = False
        if stratify and y is not None and y.value_counts().min() < 2:
            print("WARN: a class has <2 members; disabling stratification.", file=sys.stderr)
            stratify = False
        train, val, test = random_split(df, y, r, args.seed, stratify)

    splits = {"train": train, "val": val, "test": test}

    group_overlap = 0
    if method == "group":
        gs = {k: set(v[args.group]) for k, v in splits.items()}
        group_overlap = len((gs["train"] & gs["val"]) | (gs["train"] & gs["test"]) | (gs["val"] & gs["test"]))

    # write() only emits parquet or CSV — name the file to MATCH the actual content,
    # not the (possibly .json/.xlsx) input extension, which would mislabel CSV bytes.
    out_ext = ".parquet" if ext == ".parquet" else ".csv"
    for name, d in splits.items():
        write(d.reset_index(drop=True), os.path.join(args.out_dir, f"{name}{out_ext}"))

    report = build_report(args, len(df), splits, method, task, dup_n, args.drop_duplicates and dup_n > 0, group_overlap, args.target)
    with open(os.path.join(args.out_dir, "split_report.md"), "w") as f:
        f.write(report)

    # machine-readable summary — readiness-check audits leakage from THIS, not by grepping the report
    with open(os.path.join(args.out_dir, "split_summary.json"), "w") as f:
        json.dump({"method": method, "task": task, "seed": args.seed,
                   "sizes": {k: len(v) for k, v in splits.items()},
                   "no_row_overlap": _disjoint(splits),
                   "group_overlap": group_overlap if method == "group" else None,
                   "duplicates_in_source": dup_n, "dropped_duplicates": bool(args.drop_duplicates and dup_n > 0)}, f, indent=2)

    print(f"method={method} task={task} seed={args.seed}")
    for name, d in splits.items():
        print(f"  {name:5s}: {len(d):>10,} rows  ({len(d)/len(df):.1%})")
    print(f"  overlap: {'NONE ✅' if _disjoint(splits) else 'FOUND ❌'}")
    if method == "group":
        print(f"  group overlap: {'none ✅' if not group_overlap else str(group_overlap)+' ❌'}")
    print(f"  written → {args.out_dir}/ (train/val/test + split_report.md)")


if __name__ == "__main__":
    main()
