#!/usr/bin/env python3
"""Evaluate a model from a PREDICTIONS file — claude-all-in-one-plugin.

Framework-agnostic by design: it never loads a model. It takes a table with
y_true, y_pred (and optionally y_score + feature columns) and reports overall
metrics, the confusion matrix / residual stats, and a SLICE-based error
analysis that surfaces the subgroups where the model is worst.

It deliberately does NOT measure online/production performance (impossible
offline) and does NOT replace manual error analysis — it scaffolds it.
"""
import argparse
import json
import os

import numpy as np
import pandas as pd


def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def infer_task(y):
    # fractional float values are always regression (kept identical across all scripts)
    if pd.api.types.is_float_dtype(y) and not np.all(np.mod(y.dropna(), 1) == 0):
        return "regression"
    nun = y.nunique(dropna=True)
    if pd.api.types.is_float_dtype(y) and nun > 20:
        return "regression"
    return "classification" if nun <= max(20, int(0.05 * len(y))) else "regression"


def resolve_task(pred_file, task_arg, yt):
    """Prefer the producer's recorded task (sibling *_metric.json) over re-inferring from
    the eval split — re-inference on a different sample can silently flip the task."""
    if task_arg != "auto":
        return task_arg, f"--task {task_arg}"
    d = os.path.dirname(os.path.abspath(pred_file))
    for f in sorted(os.listdir(d)):
        if f.endswith("_metric.json"):
            try:
                with open(os.path.join(d, f)) as fh:
                    meta = json.load(fh)
                if meta.get("task"):
                    return meta["task"], f
            except (OSError, ValueError):
                pass
    return infer_task(yt), "inferred from y_true"


def overall_clf(y, pred, score):
    from sklearn.metrics import (accuracy_score, f1_score, precision_score,
                                 recall_score, roc_auc_score)
    m = {
        "accuracy": accuracy_score(y, pred),
        "precision_macro": precision_score(y, pred, average="macro", zero_division=0),
        "recall_macro": recall_score(y, pred, average="macro", zero_division=0),
        "f1_macro": f1_score(y, pred, average="macro", zero_division=0),
        "f1_weighted": f1_score(y, pred, average="weighted", zero_division=0),
    }
    if score is not None and y.nunique() == 2:
        try:
            m["roc_auc"] = roc_auc_score(y, score)
        except ValueError:
            pass
    return m


def overall_reg(y, pred):
    from sklearn.metrics import (mean_absolute_error, mean_absolute_percentage_error,
                                 mean_squared_error, r2_score)
    resid = pred - y
    nonzero = bool((np.asarray(y) != 0).all())  # MAPE explodes to ~1e15 on zero targets
    return {
        "mae": mean_absolute_error(y, pred),
        "rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "mape": float(mean_absolute_percentage_error(y, pred)) if nonzero else float("nan"),
        "r2": r2_score(y, pred),
        "bias (mean resid)": float(resid.mean()),
    }


def primary_metric(yt, yp, task):
    from sklearn.metrics import f1_score, mean_absolute_error
    if task == "classification":
        return f1_score(yt, yp, average="macro", zero_division=0)
    return mean_absolute_error(yt, yp)


def make_groups(s):
    """Bucket a feature column into a small number of comparable groups."""
    if pd.api.types.is_numeric_dtype(s) and s.nunique() > 12:
        return pd.qcut(s, q=min(5, s.nunique()), duplicates="drop").astype(str)
    top = s.value_counts().index[:12]
    return s.where(s.isin(top), other="(other)").astype(str)


def pick_slice_cols(df, reserved, k=4):
    """Auto-pick up to k sliceable feature columns (categorical / low-card numeric)."""
    cands = []
    for c in df.columns:
        if c in reserved:
            continue
        s = df[c]
        nun = s.nunique(dropna=True)
        if 1 < nun <= 12 or (pd.api.types.is_numeric_dtype(s) and nun > 12):
            cands.append((c, nun))
    cands.sort(key=lambda t: (pd.api.types.is_numeric_dtype(df[t[0]]), t[1]))
    return [c for c, _ in cands[:k]]


def fmt(v):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.4g}"


def confusion_md(y, pred):
    from sklearn.metrics import confusion_matrix
    labels = sorted(pd.unique(pd.concat([y, pred])))
    cm = confusion_matrix(y, pred, labels=labels)
    header = "| true ⧵ pred | " + " | ".join(str(l) for l in labels) + " |"
    sep = "|" + "---|" * (len(labels) + 1)
    body = "\n".join("| **" + str(labels[i]) + "** | " + " | ".join(str(x) for x in row) + " |"
                     for i, row in enumerate(cm))
    return "\n".join([header, sep, body])


def slice_table(df, slice_cols, yt_col, yp_col, task, min_n):
    rows = []
    for col in slice_cols:
        groups = make_groups(df[col])
        for g, idx in df.groupby(groups).groups.items():
            sub = df.loc[idx]
            if len(sub) < min_n:
                continue
            rows.append({"feature": col, "group": str(g), "n": len(sub),
                         "metric": primary_metric(sub[yt_col], sub[yp_col], task)})
    if not rows:
        return None, []
    worst = sorted(rows, key=lambda r: r["metric"], reverse=(task != "classification"))[:8]
    return rows, worst


def main():
    p = argparse.ArgumentParser(description="Evaluate a model from a predictions file.")
    p.add_argument("pred_file", help="table with y_true, y_pred[, y_score, features]")
    p.add_argument("--task", choices=["auto", "classification", "regression"], default="auto")
    p.add_argument("--y-true", default="y_true")
    p.add_argument("--y-pred", default="y_pred")
    p.add_argument("--score-col", default="y_score")
    p.add_argument("--slice-by", default=None, help="comma-separated feature columns; auto if omitted")
    p.add_argument("--min-slice-n", type=int, default=20)
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()

    df = load(args.pred_file)
    for col in (args.y_true, args.y_pred):
        if col not in df.columns:
            raise SystemExit(f"Column '{col}' not in {args.pred_file}. Columns: {list(df.columns)}")

    yt, yp = df[args.y_true], df[args.y_pred]
    score = df[args.score_col] if args.score_col in df.columns else None
    task, task_src = resolve_task(args.pred_file, args.task, yt)
    args.out_dir = args.out_dir or os.path.join(os.path.dirname(os.path.abspath(args.pred_file)), "evaluation")
    os.makedirs(args.out_dir, exist_ok=True)

    overall = overall_clf(yt, yp, score) if task == "classification" else overall_reg(yt, yp)
    primary_name = "f1_macro" if task == "classification" else "mae"

    reserved = {args.y_true, args.y_pred, args.score_col}
    slice_cols = args.slice_by.split(",") if args.slice_by else pick_slice_cols(df, reserved)
    slice_cols = [c for c in slice_cols if c in df.columns]
    all_slices, worst = slice_table(df, slice_cols, args.y_true, args.y_pred, task, args.min_slice_n) if slice_cols else (None, [])

    # report
    overall_tbl = "| metric | value |\n|---|---|\n" + "\n".join(f"| {k} | {fmt(v)} |" for k, v in overall.items())

    mermaid_worst = ""
    if worst:
        wt = "| feature | group | n | " + primary_name + " |\n|---|---|---|---|\n" + \
             "\n".join(f"| {r['feature']} | {r['group']} | {r['n']:,} | {fmt(r['metric'])} |" for r in worst)
        worst_md = f"Sliced on: `{', '.join(slice_cols)}` (groups with n ≥ {args.min_slice_n}).\n\n" \
                   f"**Worst-performing slices** (where to focus error analysis):\n\n{wt}"
        w0 = worst[0]
        mermaid_worst = f' --> W["worst slice<br/>{w0["feature"]}={w0["group"]}<br/>{primary_name}={fmt(w0["metric"])} (n={w0["n"]:,})"]'
    elif slice_cols:
        worst_md = f"_Sliced on `{', '.join(slice_cols)}`, but no group reached n ≥ {args.min_slice_n} " \
                   f"({len(df):,} rows total) — slices aren't meaningful here. Lower `--min-slice-n` or evaluate on a larger split._"
    else:
        worst_md = "_No feature columns in the predictions file to slice on._"

    detail = "### Confusion matrix\n" + confusion_md(yt, yp) if task == "classification" \
        else "### Residuals\n" + f"- mean (bias): {fmt(float((yp-yt).mean()))}\n- std: {fmt(float((yp-yt).std()))}\n- worst over-prediction: {fmt(float((yp-yt).max()))}\n- worst under-prediction: {fmt(float((yp-yt).min()))}"

    report = f"""# Evaluation report — {os.path.basename(args.pred_file)} ({task})

> Offline evaluation on a fixed predictions set ({len(df):,} rows). Framework-agnostic.

## At a glance
```mermaid
flowchart LR
    O["overall<br/>{primary_name}={fmt(overall[primary_name])}"]{mermaid_worst}
```

## Overall metrics
{overall_tbl}

{detail}

## Slice-based error analysis
{worst_md}

## ⚠️ What this report does NOT tell you
- **Online / production performance.** This is offline on one frozen split. The
  offline↔online gap is real — good offline metrics ≠ business impact. Only a
  live A/B test against real traffic measures that.
- **Root cause.** Slices show *where* the model is worst; they don't say *why*.
  Do the manual pass — read ~100 of the worst-slice errors by hand (Ng, *ML
  Yearning* Ch.14) — to find fixable categories and direct targeted data collection.
"""
    with open(os.path.join(args.out_dir, "evaluation_report.md"), "w") as f:
        f.write(report)

    print(f"task={task} ({task_src})  rows={len(df):,}  primary={primary_name}={fmt(overall[primary_name])}")
    for k, v in overall.items():
        print(f"  {k:18s} {fmt(v)}")
    if worst:
        w0 = worst[0]
        print(f"  worst slice: {w0['feature']}={w0['group']} {primary_name}={fmt(w0['metric'])} (n={w0['n']:,})")
    print(f"  written → {args.out_dir}/evaluation_report.md")


if __name__ == "__main__":
    main()
