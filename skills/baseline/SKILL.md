---
name: baseline
description: Establish a baseline before any serious modeling — train a Dummy predictor (the floor) and one deliberately simple model (logistic/linear regression) on the train split, score on val, and report the single number any fancier model must beat to be worth its cost. Writes a baseline_report.md (with a Mermaid metric ladder) and a predictions file for evaluate-model. Use right after split-dataset, before reaching for deep learning or gradient boosting.
allowed-tools: Bash, Read, Write, Glob
---

# baseline

Answer the question that saves projects: **"is a complex model even worth it?"** Before anyone trains a neural net or tunes XGBoost, you need two numbers — the **floor** (a dummy that ignores the features) and a **simple model** (logistic/linear regression). If the simple model barely beats the dummy, the signal is weak; if a future complex model barely beats the simple one, it isn't worth the cost. This is the cheapest, highest-information step in modeling.

This skill trains both, scores them on the dev split, and writes the "number to beat" plus a predictions file the `evaluate-model` skill can analyze.

## When to use
- Right after `split-dataset`, before any deep learning, boosting, or hyperparameter tuning.
- When someone proposes a complex model — get the baseline first so "better" has a reference.
- To sanity-check the pipeline end-to-end on something trivial before investing in modeling.

## Contract (important)
- **Reads splits; writes a report dir.** Never modifies the splits or source.
- **Preprocessing is fit on `train` only** (inside a sklearn Pipeline) — same leakage discipline as `split-dataset`. Scores are reported on `val` by default (keep `test` untouched until the very end).
- **Deliberately simple.** This skill does NOT tune or try fancy models — that's the point. It produces the bar, not the winner.

## Steps
1. **Need splits first.** If there's no `train/val` dir, run `split-dataset`. 
2. **Confirm target + task** (classification → F1/accuracy; regression → MAE/RMSE). `--task auto` infers it.
3. **Ensure deps & run:**
   ```bash
   python3 -c "import pandas, sklearn" 2>/dev/null || pip install pandas scikit-learn pyarrow
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/baseline/scripts/baseline.py" \
       --splits-dir "<dir from split-dataset>" --target <col> [--task auto] [--eval-on val]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/baseline/scripts/baseline.py`.)
4. **Read the result, don't just dump it.** Lead with the verdict: how far does the simple model beat the dummy, and what is the number to beat? Flag a weak signal (simple ≈ dummy → reconsider features or whether ML fits) or an already-strong simple model (a complex model may add little).
5. **Hand off:** the predictions file → `evaluate-model` for deeper analysis (slices, error buckets). The "number to beat" → the bar for any complex model in `train-tune`.

## Output style
- One-line verdict first: e.g. *"LogReg F1 0.96 vs dummy 0.32 — strong signal, ML justified; beat 0.96."*
- Show the dummy-vs-simple comparison (the report's Mermaid ladder + metric table).
- Always state the **number to beat** and which metric it's on.

## Grounding
"Keep the first model simple / build a basic system fast" — Google Rules of ML #4 and Andrew Ng, *Machine Learning Yearning* Ch.13. A dummy/most-frequent predictor is the standard floor for judging whether a model has learned anything beyond the class prior or target mean.
