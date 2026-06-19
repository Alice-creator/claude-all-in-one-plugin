---
name: evaluate-model
description: Evaluate a model from a PREDICTIONS file (y_true, y_pred, optional y_score + features) — framework-agnostic, never loads a model. Reports overall metrics, the confusion matrix / residual stats, and a slice-based error analysis that surfaces the subgroups where the model is worst. Honestly flags what offline evaluation cannot tell you (online performance, root cause). Use after baseline or any model that can emit predictions; composes directly with the baseline skill's output.
allowed-tools: Bash, Read, Write, Glob
---

# evaluate-model

Go past a single accuracy number to **where and how the model fails**. This skill takes a predictions table and reports the overall metrics, the confusion matrix (classification) or residual profile (regression), and — the valuable part — a **slice-based error analysis** that ranks the subgroups where the model is worst, so you know where to dig.

It is **framework-agnostic on purpose**: it never loads a `.pkl`/checkpoint, so it works for sklearn, XGBoost, PyTorch, an LLM, or a hand-written heuristic — anything that can write `y_true, y_pred` to a file.

## When to use
- After `baseline` (it consumes `baseline_predictions.csv` directly) or after any model you can get predictions out of.
- To compare two models fairly on the same dev/test set.
- When a single metric looks fine but you suspect the model is bad on an important subgroup.

## Contract (important)
- **Input is a predictions file, not a model.** Columns: `y_true`, `y_pred`, optional `y_score` (probability for the positive class, binary), plus any feature columns to slice on.
- **Offline only — and it says so.** The report has a standing section on what it *cannot* measure: online/production performance and root cause. Do not let a good offline number be read as business success.
- **Scaffolds error analysis, doesn't replace it.** Slices point you at the worst subgroups; the manual read of those errors is still yours to do.

## Steps
1. **Get a predictions file.** From `baseline`, or export `y_true,y_pred[,y_score]` (+ feature cols for slicing) from your model on the dev/test split.
2. **Ensure deps & run:**
   ```bash
   python3 -c "import pandas, sklearn" 2>/dev/null || pip install pandas scikit-learn pyarrow
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/evaluate-model/scripts/evaluate.py" "<predictions-file>" \
       [--task auto] [--y-true y_true] [--y-pred y_pred] [--score-col y_score] \
       [--slice-by col1,col2] [--min-slice-n 20]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/evaluate-model/scripts/evaluate.py`. Slice columns are auto-picked if `--slice-by` is omitted.)
3. **Interpret — lead with the story, not the table.** State the headline metric, then the *worst slice* and how far it lags the overall — that's the actionable finding. Compare against the `baseline` number to beat.
4. **Direct the next move.** Recommend reading ~100 errors from the worst slice by hand to find fixable categories (→ targeted data collection / feature work), or re-running on `test` once model choice is locked.

## Output style
- One-line headline: e.g. *"R² 0.48, MAE 407k; worst on Fuel_Type=Hybrid (MAE 422k, n=6.4k)."*
- Surface the **worst slices** explicitly — that's the point, more than the overall table.
- Always restate the offline↔online caveat; never imply the offline number equals production quality.

## Grounding
Single-number optimizing metric + error analysis by inspecting the worst cases comes from Andrew Ng, *Machine Learning Yearning* (Ch.9, Ch.14: "use error analysis to identify the most promising directions"). Slice/subgroup evaluation is standard production-readiness practice (the offline metric can hide systematic failure on a minority slice). The offline↔online gap — good offline metrics need not yield business impact — is documented across Google's ML guidance and MLOps practice.
