---
name: train-tune
description: Tune a tabular model the leakage-safe, reproducible way — runs RandomizedSearchCV with the full preprocessor INSIDE the CV pipeline (CV on train only, never touching val/test), refits the best config, scores it on val against the baseline number, logs every run (params/seed/metrics/data-hash) to an append-only experiment log, and emits predictions in the same schema evaluate-model consumes. Scoped to scikit-learn + gradient boosting on tabular data; deep learning / GPU / RL are refused. Use after baseline/select-model, before evaluate-model.
allowed-tools: Bash, Read, Write, Glob
---

# train-tune

The workhorse step: turn "we have splits + a number to beat" into "we have a tuned model and a fair, reproducible result." It tunes the model family you give it with `RandomizedSearchCV`, keeps preprocessing **inside** the cross-validation so nothing leaks, and reports honestly whether tuning actually beat the baseline — then hands tuned predictions to `evaluate-model`.

Bounded to **tabular** models (scikit-learn + optional gradient-boosting libs). Deep learning, GPU training, and RL are out of scope and refused with a one-line reason.

## When to use
- After `baseline` (and optionally `select-model`), when you want real performance from a tabular model.
- When you need a **reproducible, auditable** tuning run — every config, seed, metric, and data hash logged.
- To produce a tuned predictions file that drops straight into `evaluate-model`, comparable apples-to-apples against the baseline on the same val split.

## Contract (important)
- **Leakage is non-negotiable.** The preprocessor (impute → scale → one-hot) lives inside the Pipeline that `RandomizedSearchCV` wraps, so every transformer refits on each CV training fold only. The search never sees val or test. (scikit-learn Common Pitfalls; Cawley & Talbot 2010.)
- **CV runs on train only.** val is held out for the honest comparison; test is never touched (`--eval-on test` is gated behind a warning — touch it once, at the very end, via evaluate-model).
- **Honest about the CV number.** `best_score_` is the model-*selection* score and is optimistically biased; the report leads with the val number and labels the CV score as biased. Reported in the metric's natural sign (neg-scorers negated back).
- **Tuned model must earn its keep.** The report shows tuned vs baseline (direction-aware) and says plainly whether it beat the bar and by how much (Google Rules of ML #4).
- **Tabular only.** sklearn-native + gradient boosting (`gbt` always; `xgb`/`lgbm`/`catboost` if importable, else falls back to `gbt` with a note). DL / GPU / RL refused.
- **Reproducible.** Fixed `--seed` (default 42) across Python/NumPy/estimator; logged with a dataset content-hash so a run ties to an exact data state.
- **Predictions schema matches the producer exactly** (`y_true, y_pred[, y_score]` + feature columns, same primary metric f1_macro/mae) so evaluate-model runs unchanged.

## Steps
1. **Need splits + a baseline.** Run `split-dataset` then `baseline` first (baseline writes `baseline_metric.json`, the machine-readable bar this skill reads). `select-model` can suggest the `--model` family.
2. **Ensure deps & run:**
   ```bash
   python3 -c "import pandas, sklearn" 2>/dev/null || pip install pandas scikit-learn pyarrow
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/train-tune/scripts/train_tune.py" \
       --splits-dir "<dir from split-dataset>" --target <col> \
       [--model gbt|rf|linear|xgb|lgbm|catboost] [--n-iter 40] [--cv 5] [--seed 42]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/train-tune/scripts/train_tune.py`. `--n-iter` ≈ 40–60 is a sane default; ~60 random draws give a high chance of sampling the top few % of the search *distribution* — Bergstra & Bengio 2012 — it's a budget, not an optimality proof.)
3. **Read the verdict.** Lead with: did the tuned model beat the baseline, and by how much? Surface the leakage statement and the biased-CV caveat so the number is understood correctly.
4. **Hand off:** `tuned_predictions.csv` → `evaluate-model` for slice/error analysis. The run is logged in `experiments.jsonl` (re-runnable with the same flags + seed).

## Output style
- One-line verdict first: e.g. *"tuned gbt mae=3.88e5 vs baseline 4.20e5 → beats by 3.2e4."*
- Show the Mermaid ladder (baseline → tuned → verdict) and the val-metrics table; state the best params briefly.
- Always include the leakage statement and label the CV-selection score as optimistically biased.

## Grounding
RandomizedSearch over grid (Bergstra & Bengio 2012); preprocessing inside the CV pipeline to prevent leakage (scikit-learn Common Pitfalls); the inner CV score is optimistically biased and nested CV gives an unbiased estimate (Cawley & Talbot 2010); GBDTs as the tabular default (Grinsztajn 2022; Shwartz-Ziv 2022); start-simple / earn-the-complexity (Google Rules of ML #4); content-hash data versioning (DVC) and per-run logging of params/metrics/git/seed (MLflow).
