#!/usr/bin/env python3
"""Establish a baseline for a split dataset — claude-all-in-one-plugin.

Trains the floor (a Dummy predictor) and one deliberately simple real model
(LogisticRegression / LinearRegression) on `train`, scores them on `val`, and
reports the number any fancier model must beat. All preprocessing is fit on
`train` only (inside a Pipeline) — the leakage-safe discipline.

Also writes a predictions file (y_true, y_pred[, y_score] + features) so the
`evaluate-model` skill can analyze it. Reads split files; writes a report dir.
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd


def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def find_split(splits_dir, name):
    for f in os.listdir(splits_dir):
        stem = os.path.splitext(f)[0].lower()
        if stem == name:
            return os.path.join(splits_dir, f)
    raise SystemExit(f"Could not find '{name}.*' in {splits_dir}")


def infer_task(y):
    # fractional float values are always regression — guard BEFORE the cardinality check
    # so low-cardinality ratings/scores/prices aren't misrouted to classification (which
    # then crashes the classification metrics on a continuous target).
    if pd.api.types.is_float_dtype(y) and not np.all(np.mod(y.dropna(), 1) == 0):
        return "regression"
    nun = y.nunique(dropna=True)
    if pd.api.types.is_float_dtype(y) and nun > 20:
        return "regression"
    return "classification" if nun <= max(20, int(0.05 * len(y))) else "regression"


def build_preprocessor(X):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    num = X.select_dtypes(include=np.number).columns.tolist()
    cat = [c for c in X.columns if c not in num]
    num_pipe = Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())])
    cat_pipe = Pipeline([
        ("imp", SimpleImputer(strategy="most_frequent")),
        # sparse_output=False keeps this preprocessor reusable by tree models (e.g.
        # HistGradientBoosting in train-tune) which reject sparse X; linear models are fine either way
        ("oh", OneHotEncoder(handle_unknown="ignore", max_categories=20, sparse_output=False)),
    ])
    return ColumnTransformer([("num", num_pipe, num), ("cat", cat_pipe, cat)])


def clf_metrics(y, pred, score):
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
    m = {"accuracy": accuracy_score(y, pred), "f1_macro": f1_score(y, pred, average="macro")}
    if score is not None:
        try:
            m["roc_auc"] = roc_auc_score(y, score)
        except ValueError:
            pass
    return m


def reg_metrics(y, pred):
    from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error, r2_score
    nonzero = bool((np.asarray(y) != 0).all())  # MAPE divides by |y| → explodes to ~1e15 on zero targets
    return {
        "mae": mean_absolute_error(y, pred),
        "rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "mape": float(mean_absolute_percentage_error(y, pred)) if nonzero else float("nan"),
        "r2": r2_score(y, pred),
    }


def fmt(v):
    return f"{v:,.4g}"


def main():
    p = argparse.ArgumentParser(description="Establish a baseline (dummy + simple model).")
    p.add_argument("--splits-dir", required=True, help="dir with train/val[/test] files from split-dataset")
    p.add_argument("--target", required=True)
    p.add_argument("--task", choices=["auto", "classification", "regression"], default="auto")
    p.add_argument("--eval-on", choices=["val", "test"], default="val")
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()

    train = load(find_split(args.splits_dir, "train"))
    dev = load(find_split(args.splits_dir, args.eval_on))
    args.out_dir = args.out_dir or os.path.join(args.splits_dir, "baseline")
    os.makedirs(args.out_dir, exist_ok=True)

    ytr, ydev = train[args.target], dev[args.target]
    Xtr, Xdev = train.drop(columns=[args.target]), dev.drop(columns=[args.target])
    task = args.task if args.task != "auto" else infer_task(ytr)

    collide = {"y_true", "y_pred", "y_score"} & set(Xdev.columns)
    if collide:
        raise SystemExit(f"Feature column(s) {sorted(collide)} collide with reserved prediction columns; rename them before splitting.")
    if task == "classification" and ytr.nunique() < 2:
        raise SystemExit(f"Target '{args.target}' has only one class in train — nothing to learn. Check your split/filter, or pass --task regression if it's numeric.")

    from sklearn.pipeline import Pipeline
    pre = build_preprocessor(Xtr)

    if task == "classification":
        from sklearn.dummy import DummyClassifier
        from sklearn.linear_model import LogisticRegression
        models = {
            "dummy (most_frequent)": DummyClassifier(strategy="most_frequent"),
            "dummy (stratified)": DummyClassifier(strategy="stratified", random_state=42),
            "simple (logreg)": Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=1000))]),
        }
        primary = "f1_macro"
    else:
        from sklearn.dummy import DummyRegressor
        from sklearn.linear_model import LinearRegression
        models = {
            "dummy (mean)": DummyRegressor(strategy="mean"),
            "dummy (median)": DummyRegressor(strategy="median"),
            "simple (linreg)": Pipeline([("pre", pre), ("reg", LinearRegression())]),
        }
        primary = "mae"

    LOWER_BETTER = {"mae", "rmse", "mape"}
    rows, preds_for_file, score_for_file, simple_name = {}, None, None, None
    binary = task == "classification" and ytr.nunique() == 2
    for name, model in models.items():
        model.fit(Xtr, ytr)  # dummies ignore the features; the pipeline fits on train only
        pred = model.predict(Xdev)
        score = model.predict_proba(Xdev)[:, 1] if binary and hasattr(model, "predict_proba") else None
        rows[name] = clf_metrics(ydev, pred, score) if task == "classification" else reg_metrics(ydev, pred)
        if "simple" in name:
            preds_for_file, score_for_file, simple_name = pred, score, name

    metric_keys = list(next(iter(rows.values())).keys())
    header = "| model | " + " | ".join(metric_keys) + " |"
    sep = "|" + "---|" * (len(metric_keys) + 1)
    body = "\n".join(
        "| " + n + " | " + " | ".join(fmt(rows[n][k]) for k in metric_keys) + " |" for n in rows
    )

    dummy_vals = [rows[n][primary] for n in rows if "dummy" in n]
    dummy_best = min(dummy_vals) if primary in LOWER_BETTER else max(dummy_vals)
    simple_val = rows[simple_name][primary]

    mermaid = "\n".join([
        "```mermaid",
        "flowchart LR",
        f'    DUM["floor: best dummy<br/>{primary} = {fmt(dummy_best)}"] --> SIM["{simple_name}<br/>{primary} = {fmt(simple_val)}"]',
        f'    SIM --> GATE["🎯 a complex model must<br/>beat {primary} = {fmt(simple_val)}<br/>to be worth it"]',
        "```",
    ])

    # write predictions for evaluate-model
    out = pd.DataFrame({"y_true": ydev.values, "y_pred": preds_for_file})
    if score_for_file is not None:
        out["y_score"] = score_for_file
    out = pd.concat([out.reset_index(drop=True), Xdev.reset_index(drop=True)], axis=1)
    preds_path = os.path.join(args.out_dir, "baseline_predictions.csv")
    out.to_csv(preds_path, index=False)

    # Machine-readable "number to beat" — select-model / train-tune read THIS, not the
    # pretty-printed report (fmt() comma-groups & uses sci notation, which is unparseable).
    with open(os.path.join(args.out_dir, "baseline_metric.json"), "w") as f:
        json.dump({"primary": primary, "value": float(simple_val), "task": task,
                   "lower_is_better": primary in LOWER_BETTER, "eval_on": args.eval_on}, f, indent=2)

    report = f"""# Baseline report — `{args.target}` ({task})

> Trained on `train`, scored on `{args.eval_on}`. Preprocessing fit on **train only**.

## At a glance
{mermaid}

## Metrics on `{args.eval_on}`
{header}
{sep}
{body}

- **Primary metric:** `{primary}`  ·  lower-is-better: {primary in LOWER_BETTER}
- **The number to beat:** `{primary} = {fmt(simple_val)}` (the simple model). If a complex
  model can't clearly beat this, it isn't worth its cost (Rules of ML #4 / Ng Ch.13).
- **Predictions written:** `{os.path.basename(preds_path)}` → feed to `evaluate-model`.
"""
    with open(os.path.join(args.out_dir, "baseline_report.md"), "w") as f:
        f.write(report)

    print(f"task={task}  eval_on={args.eval_on}  primary={primary}")
    for n in rows:
        print(f"  {n:24s} {primary}={fmt(rows[n][primary])}")
    print(f"  number to beat: {primary}={fmt(simple_val)}")
    print(f"  written → {args.out_dir}/ (baseline_report.md + baseline_predictions.csv)")


if __name__ == "__main__":
    main()
