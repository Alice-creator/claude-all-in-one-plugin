#!/usr/bin/env python3
"""Leakage-safe hyperparameter tuning for tabular models — claude-all-in-one-plugin.

Takes the splits + a model family, runs RandomizedSearchCV with the WHOLE
preprocessor inside the CV pipeline (so every transformer refits per fold — the
search never sees val/test), refits the best config on train, scores it on val,
logs the run, and emits predictions in the SAME schema baseline writes so
evaluate-model consumes it unchanged.

Bounded to scikit-learn + optional gradient-boosting libs on TABULAR data.
Deep learning / GPU / RL are explicitly out of scope and refused.
"""
import argparse
import datetime
import hashlib
import json
import os
import random
import subprocess
import sys

import numpy as np
import pandas as pd
from scipy.stats import loguniform, randint, uniform

# --- helpers kept byte-identical to baseline.py (must not drift — keeps the ----
# --- predictions schema and metrics directly comparable to baseline) -----------
def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def find_split(splits_dir, name):
    for f in os.listdir(splits_dir):
        if os.path.splitext(f)[0].lower() == name:
            return os.path.join(splits_dir, f)
    raise SystemExit(f"Could not find '{name}.*' in {splits_dir}")


def infer_task(y):
    # fractional float values are always regression (kept identical across all scripts)
    if pd.api.types.is_float_dtype(y) and not np.all(np.mod(y.dropna(), 1) == 0):
        return "regression"
    nun = y.nunique(dropna=True)
    if pd.api.types.is_float_dtype(y) and nun > 20:
        return "regression"
    if nun > max(20, int(0.05 * len(y))):
        return "regression"
    # A numeric target with a handful of ordered values (e.g. a 1-5 rating) is auto-classified here but is
    # often really ordinal REGRESSION — warn loudly so the wrong task/metric/stratify isn't picked silently.
    if pd.api.types.is_numeric_dtype(y) and 3 <= nun <= 20:
        print(f"WARNING infer_task: numeric target with {nun} distinct values auto-inferred as CLASSIFICATION; "
              "if it is an ordinal rating/score it is really regression — pass --task regression to override.",
              file=sys.stderr)
    return "classification"


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
        # sparse_output=False: HistGradientBoosting & other tree models reject sparse X
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
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.4g}"


def enforce_test_lock(splits_dir, eval_on, allow_test, consumer):
    """Mechanical guardrail (kept byte-identical across baseline/train-tune — must not drift):
    the test split may be scored EXACTLY ONCE, at the very end, and only with explicit
    --allow-test — never for tuning/selection. Writes a one-time lock so a second test
    evaluation is refused (delete the lock file to deliberately override)."""
    if eval_on != "test":
        return
    if not allow_test:
        raise SystemExit(
            "Refusing --eval-on test without --allow-test. The test split must be touched EXACTLY "
            "ONCE, after the model is locked (never for tuning/selection). If this is that final "
            "locked estimate, re-run with --allow-test.")
    lock = os.path.join(splits_dir, ".test_consumed.json")
    if os.path.exists(lock):
        raise SystemExit(
            f"Test split already consumed once (see {lock}). Touching it again invalidates the "
            "held-out estimate — re-split for a fresh test, or delete that file to override deliberately.")
    with open(lock, "w") as f:
        json.dump({"consumer": consumer, "eval_on": eval_on}, f, indent=2)
# -------------------------------------------------------------------------------

LOWER_BETTER = {"mae", "rmse", "mape"}
DL_RL_HINTS = ("nn", "neural", "mlp", "cnn", "rnn", "lstm", "transformer", "torch", "keras", "tensorflow", "rl", "dqn", "ppo")


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)


def make_estimator(model, task, seed):
    """Return (bare_estimator, note). Falls back to gbt if an optional lib is missing."""
    is_clf = task == "classification"
    if model in ("auto", "gbt"):
        from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
        Est = HistGradientBoostingClassifier if is_clf else HistGradientBoostingRegressor
        # early_stopping='auto' turns on only when n_samples>10k — right by data size
        # (forcing it True wastes scarce rows on an internal val split for small data).
        return Est(random_state=seed, early_stopping="auto", max_iter=500), None
    if model == "rf":
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        Est = RandomForestClassifier if is_clf else RandomForestRegressor
        return Est(random_state=seed, n_jobs=-1), None
    if model == "linear":
        if is_clf:
            from sklearn.linear_model import LogisticRegression
            return LogisticRegression(max_iter=1000, random_state=seed), None
        from sklearn.linear_model import ElasticNet
        return ElasticNet(random_state=seed), None
    if model in ("xgb", "lgbm", "catboost"):
        try:
            if model == "xgb":
                import xgboost
                Est = xgboost.XGBClassifier if is_clf else xgboost.XGBRegressor
                return Est(random_state=seed, verbosity=0, tree_method="hist"), None
            if model == "lgbm":
                import lightgbm
                Est = lightgbm.LGBMClassifier if is_clf else lightgbm.LGBMRegressor
                return Est(random_state=seed, verbose=-1), None
            import catboost
            Est = catboost.CatBoostClassifier if is_clf else catboost.CatBoostRegressor
            return Est(random_state=seed, verbose=0), None
        except ImportError:
            return make_estimator("gbt", task, seed)[0], f"{model} not installed — fell back to gbt (HistGradientBoosting)."
    raise SystemExit(f"Unknown --model '{model}'. Tabular families: gbt, rf, linear, xgb, lgbm, catboost.")


def search_space(model, task, n_train):
    """RandomizedSearch distributions per family (keys prefixed 'model__')."""
    if model in ("auto", "gbt"):
        # cap min_samples_leaf to the data size — a fixed 200 forces single-leaf
        # (majority-class) trees on small folds and collapses the model.
        leaf_hi = max(20, min(200, n_train // 20))
        return {
            "model__learning_rate": loguniform(1e-2, 3e-1),
            "model__max_leaf_nodes": randint(15, 255),
            "model__max_depth": [None, 3, 5, 8, 12],
            "model__min_samples_leaf": randint(1, leaf_hi),
            "model__l2_regularization": loguniform(1e-3, 10),
        }
    if model == "rf":
        return {
            "model__n_estimators": randint(200, 800),
            "model__max_depth": [None, 5, 10, 20, 40],
            "model__max_features": ["sqrt", "log2", 0.5, 1.0],
            "model__min_samples_leaf": randint(1, 50),
        }
    if model == "linear":
        if task == "classification":
            return {"model__C": loguniform(1e-3, 1e2)}
        return {"model__alpha": loguniform(1e-4, 1e2), "model__l1_ratio": uniform(0, 1)}
    # boosting libs (only reached if importable)
    return {
        "model__n_estimators": randint(200, 1000),
        "model__learning_rate": loguniform(1e-2, 3e-1),
        "model__max_depth": randint(3, 12),
        "model__subsample": uniform(0.6, 0.4),
    }


def baseline_bar(baseline_dir, task):
    """Read the number to beat from the machine-readable JSON; never scrape markdown.
    Falls back to recomputing from baseline's predictions on THIS run's resolved task
    (not a re-inferred one — re-inference could pick a different metric than the run uses)."""
    p = os.path.join(baseline_dir, "baseline_metric.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    pred = os.path.join(baseline_dir, "baseline_predictions.csv")
    if os.path.exists(pred):
        d = pd.read_csv(pred)
        if task == "classification":
            v = clf_metrics(d["y_true"], d["y_pred"], None)["f1_macro"]
            return {"primary": "f1_macro", "value": float(v), "lower_is_better": False, "eval_on": None}
        v = reg_metrics(d["y_true"], d["y_pred"])["mae"]
        return {"primary": "mae", "value": float(v), "lower_is_better": True, "eval_on": None}
    return None


def git_commit():
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL).decode().strip())
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def sha256_files(*paths):
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()[:16]


def main():
    import sklearn
    from sklearn.model_selection import KFold, RandomizedSearchCV, StratifiedKFold

    p = argparse.ArgumentParser(description="Leakage-safe tuning for tabular models.")
    p.add_argument("--splits-dir", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--task", choices=["auto", "classification", "regression"], default="auto")
    p.add_argument("--model", default="auto", help="gbt(default) | rf | linear | xgb | lgbm | catboost")
    p.add_argument("--n-iter", type=int, default=40)
    p.add_argument("--cv", type=int, default=5)
    p.add_argument("--scoring", default="auto")
    p.add_argument("--eval-on", choices=["val", "test"], default="val")
    p.add_argument("--allow-test", action="store_true",
                   help="confirm a one-time terminal evaluation on the test split (required for --eval-on test)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()

    if any(h in args.model.lower() for h in DL_RL_HINTS):
        raise SystemExit("train-tune is TABULAR-only (scikit-learn + gradient boosting). "
                         "Deep learning / neural nets belong to a different track; sequential-reward problems are RL — both out of scope.")
    enforce_test_lock(args.splits_dir, args.eval_on, args.allow_test, "train-tune")

    set_seed(args.seed)
    train_path, dev_path = find_split(args.splits_dir, "train"), find_split(args.splits_dir, args.eval_on)
    train, dev = load(train_path), load(dev_path)
    args.out_dir = args.out_dir or os.path.join(args.splits_dir, "train-tune")
    os.makedirs(args.out_dir, exist_ok=True)

    ytr, Xtr = train[args.target], train.drop(columns=[args.target])
    ydev, Xdev = dev[args.target], dev.drop(columns=[args.target])
    collide = {"y_true", "y_pred", "y_score"} & set(Xdev.columns)
    if collide:
        raise SystemExit(f"Feature column(s) {sorted(collide)} collide with reserved prediction columns; rename them before splitting.")
    task = args.task if args.task != "auto" else infer_task(ytr)
    binary = task == "classification" and ytr.nunique() == 2
    primary = "f1_macro" if task == "classification" else "mae"
    scoring = args.scoring if args.scoring != "auto" else ("f1_macro" if task == "classification" else "neg_mean_absolute_error")
    cv_metric_name = scoring[4:] if scoring.startswith("neg_") else scoring  # label the CV score by the ACTUAL scorer

    from sklearn.pipeline import Pipeline
    estimator, fallback_note = make_estimator(args.model, task, args.seed)
    family = "gbt" if args.model == "auto" else args.model
    pipe = Pipeline([("pre", build_preprocessor(Xtr)), ("model", estimator)])
    cv = (StratifiedKFold if task == "classification" else KFold)(args.cv, shuffle=True, random_state=args.seed)

    # The search wraps the WHOLE pipeline → preprocessor refits per CV fold (no leakage).
    # error_score=nan demotes a PARTIALLY-failing config; if EVERY fit fails sklearn still
    # raises, so we catch that and give an actionable message instead of a raw traceback.
    search = RandomizedSearchCV(pipe, search_space(args.model, task, len(Xtr)), n_iter=args.n_iter, cv=cv,
                                scoring=scoring, random_state=args.seed, refit=True, n_jobs=-1, error_score=np.nan)
    try:
        search.fit(Xtr, ytr)
    except ValueError as e:
        if "fits failed" in str(e).lower():
            raise SystemExit("All hyperparameter candidates failed to fit. Likely causes: NaN/inf in the "
                             f"target, a wrong --task, or an incompatible --model. First error: {str(e).splitlines()[0]}")
        raise

    best = search.best_estimator_
    pred = best.predict(Xdev)
    score = best.predict_proba(Xdev)[:, 1] if binary and hasattr(best, "predict_proba") else None
    val_metrics = clf_metrics(ydev, pred, score) if task == "classification" else reg_metrics(ydev, pred)

    # neg_* scorers return negative values; report in the metric's natural sign.
    raw_cv = float(search.best_score_)
    cv_select = -raw_cv if scoring.startswith("neg_") else raw_cv

    bar = baseline_bar(os.path.join(args.splits_dir, "baseline"), task)
    tuned_val = val_metrics[primary]
    same_split = bar and bar.get("eval_on", args.eval_on) in (None, args.eval_on)
    comparable = bool(bar and bar["primary"] == primary and same_split)
    if comparable:
        lower = bar["lower_is_better"]
        delta = (bar["value"] - tuned_val) if lower else (tuned_val - bar["value"])
        verdict = (f"✅ beats baseline by {fmt(abs(delta))}" if delta > 0
                   else f"⚠️ does NOT beat baseline (Δ {fmt(abs(delta))}) — keep the simpler model")
        bar_txt = f"baseline {primary} = {fmt(bar['value'])} ({'lower' if lower else 'higher'} is better)"
    elif bar and bar["primary"] == primary and not same_split:
        verdict = f"baseline measured on '{bar.get('eval_on')}', this run on '{args.eval_on}' — not directly comparable"
        bar_txt = f"re-run baseline with --eval-on {args.eval_on} for a comparable bar"
    else:
        verdict = "no comparable baseline found"
        bar_txt = "run `baseline` for a reference bar"

    # predictions — schema-compatible with baseline (same columns + order) → evaluate-model consumes unchanged
    out = pd.DataFrame({"y_true": ydev.values, "y_pred": pred})
    if score is not None:
        out["y_score"] = score
    out = pd.concat([out.reset_index(drop=True), Xdev.reset_index(drop=True)], axis=1)
    out.to_csv(os.path.join(args.out_dir, "tuned_predictions.csv"), index=False)

    # sidecar so evaluate-model uses the resolved task instead of re-guessing from the eval split
    with open(os.path.join(args.out_dir, "tuned_metric.json"), "w") as f:
        json.dump({"primary": primary, "value": float(tuned_val), "task": task,
                   "lower_is_better": primary in LOWER_BETTER, "eval_on": args.eval_on}, f, indent=2)

    # full sweep for auditability
    pd.DataFrame(search.cv_results_).to_csv(os.path.join(args.out_dir, "search_results.csv"), index=False)

    # append-only run manifest (MLflow-style keys; no mlflow dependency)
    commit, now = git_commit(), datetime.datetime.now()
    record = {
        "run_id": commit + "-" + now.strftime("%Y%m%dT%H%M%S"),
        "timestamp": now.isoformat(timespec="seconds"),
        "git_commit": commit,
        "dataset_sha256": sha256_files(train_path, dev_path),
        "train_path": train_path, "eval_on": args.eval_on,
        "seed": args.seed, "model_family": family, "fallback": fallback_note,
        "n_iter": args.n_iter, "cv": args.cv, "scoring": scoring,
        "best_params": {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v)) for k, v in search.best_params_.items()},
        "cv_select_score": cv_select, "val_metrics": val_metrics, "primary": primary,
        "versions": {"python": sys.version.split()[0], "sklearn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__},
    }
    with open(os.path.join(args.out_dir, "experiments.jsonl"), "a") as f:
        f.write(json.dumps(record) + "\n")

    metric_rows = "\n".join(f"| {k} | {fmt(v)} |" for k, v in val_metrics.items())
    params_block = "\n".join(f"{k} = {v}" for k, v in search.best_params_.items())
    mermaid = "\n".join([
        "```mermaid", "flowchart LR",
        f'    BASE["baseline simple<br/>{primary} = {fmt(bar["value"]) if comparable else "?"}"] --> TUNED["tuned {family} (n_iter={args.n_iter})<br/>{primary} = {fmt(tuned_val)}"]',
        f'    TUNED --> V["{verdict}"]', "```",
    ])
    report = f"""# Tuning report — `{args.target}` ({task}, {family})

> Leakage-safe RandomizedSearchCV on `train`; honest comparison on `{args.eval_on}`. Source not modified.

## At a glance
{mermaid}

**Verdict:** tuned {family} {primary} = {fmt(tuned_val)} vs {bar_txt} → {verdict}.
{fallback_note or ""}

## Setup
| field | value |
|---|---|
| model family | {family} |
| search | RandomizedSearchCV, n_iter={args.n_iter}, cv={args.cv}, scoring=`{scoring}` |
| eval split | {args.eval_on} |
| seed | {args.seed} |
| dataset sha256 | {record['dataset_sha256']} |
| git commit | {record['git_commit']} |

## Metrics on `{args.eval_on}`
| metric | value |
|---|---|
{metric_rows}

- **CV selection {cv_metric_name} = {fmt(cv_select)}** — this is the model-SELECTION score and is optimistic (biased toward 0 error for losses / high for scores); trust the `{args.eval_on}` number above for comparison (Cawley & Talbot 2010).

## Best params
```
{params_block}
```

## Leakage statement
The preprocessor (impute → scale → one-hot) lives INSIDE the CV pipeline, so it refits on each training fold only; the search never saw `{args.eval_on}` or `test`. (scikit-learn Common Pitfalls.)

## Reproducibility
seed={args.seed} · dataset sha256={record['dataset_sha256']} · sklearn {sklearn.__version__}. Re-run with the same flags to reproduce best_params (within the same library versions/platform). Run log appended to `experiments.jsonl`; full sweep in `search_results.csv`.

## Next step
`tuned_predictions.csv` → run `evaluate-model` on it for slice/error analysis (same val split, same primary metric as baseline → directly comparable).
"""
    with open(os.path.join(args.out_dir, "tune_report.md"), "w") as f:
        f.write(report)

    print(f"task={task} model={family} n_iter={args.n_iter}")
    if fallback_note:
        print(f"  NOTE: {fallback_note}")
    print(f"  tuned {primary}={fmt(tuned_val)} | CV-select {cv_metric_name}={fmt(cv_select)} | {verdict}")
    print(f"  written → {args.out_dir}/ (tune_report.md, tuned_predictions.csv, tuned_metric.json, experiments.jsonl, search_results.csv)")


if __name__ == "__main__":
    main()
