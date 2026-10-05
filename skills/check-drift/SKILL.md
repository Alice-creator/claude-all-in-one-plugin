---
name: check-drift
description: Detect population drift between two data snapshots — a reference (what the model trained on, e.g. the train split) and a current batch. Computes per-feature PSI (primary) plus TVD / optional KS, and separately reports target drift P(y) and prediction drift P(y_pred). Offline and label-free. Honestly flags what it cannot do — it cannot detect concept drift without labels, measure model quality, or watch live traffic. Writes drift_report.md with a Mermaid diagram. Use when you have a new batch and want to know if the input population moved away from training.
allowed-tools: Bash, Read, Write, Glob
---

# check-drift

The honest, offline half of "monitoring": given the data the model was trained on (**reference**) and a **current** batch, measure how far the input population has moved. It answers the label-free question *"is the model still operating in a familiar environment?"* — it does **not** watch live traffic or prove the model got worse.

Primary metric is **PSI** (Population Stability Index), which is bounded and stable across sample size; the Siddiqi bands (0.1 moderate / 0.25 major) flag the most-drifted features.

## When to use
- A model is trained and you have a **new batch of input rows** — check whether the population shifted before trusting predictions on it.
- As a label-free **retraining-decision input** (drift is *evidence*, not a mandate — see below).
- Periodic re-checks driven by an **external** scheduler (cron) that re-exports a snapshot — each run is stateless.

## Contract (important)
- **Two snapshots, not a model.** Reference defaults to the train split (`--splits-dir`); current is a new batch in the same schema. Never loads a `.pkl`. Read-only on both.
- **Bins are frozen on the reference.** PSI quantile bins and the categorical category set are computed once on reference and reused on current — re-binning on current makes PSI meaningless. Out-of-range numeric values fold into the edge bins; current-only categories become `(unseen)` and their share is reported separately.
- **PSI is the verdict; bands are a heuristic.** The 0.1/0.25 cut-points are a credit-scoring rule of thumb with no inherent statistical meaning, sensitive to bin choice. Read the **top features by PSI**, not the count of flags (per-feature PSI is not multiple-testing corrected). KS p-values are opt-in (`--pvalues`) and secondary (they over-trigger on large n).
- **Target vs prediction drift are distinct.** Target drift = shift in P(y) (true outcomes, a real label-shift signal). Prediction drift = shift in P(y_pred) (model outputs) — **not** a model-quality measure and **not** a reliable proxy for input drift in either direction.
- **Honest limits, in writing.** The report's "What this CANNOT tell you" section states: no concept drift without labels, no model-quality/accuracy, no online/business/serving metrics, no live monitoring, no control loop. Drift ≠ degradation.

## Steps
1. **Get a current batch** in the same schema as training. Reference is the train split (pass `--splits-dir`) or any file (`--reference`).
2. **Ensure deps & run:**
   ```bash
   python3 -c "import pandas, scipy" 2>/dev/null || pip install pandas scipy pyarrow
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_drift.py" \
       --splits-dir "<dir from split-dataset>" --current "<new batch>" \
       [--target <col>] [--pred-col y_pred] [--pvalues] [--psi-thresholds 0.1,0.25]
   ```
3. **Read the verdict.** Lead with overall (stable / moderate / major) and the **top-PSI features**. Treat a big PSI as *possibly an upstream data-pipeline/schema bug*, not necessarily a real-world shift — check the feeding pipeline.
4. **Decide, honestly.** If major drift and labels later arrive → run `evaluate-model` on the labelled batch to confirm actual degradation. Drift alone never justifies a retrain.

## Output style
- One-liner first: e.g. *"drift: MAJOR — 2/19 features major; top: Brand PSI=1.72."* Prefix with "input population, label-free" so it isn't read as a model verdict.
- Show the Mermaid (reference → current → verdict + top feature) and the per-feature table sorted by PSI.
- Always restate: this is environment shift, not proof the model degraded.

## Grounding
PSI formula + frozen quantile bins + Siddiqi 0.1/0.25 bands (Fiddler, Coralogix); bands are a heuristic with no statistical interpretation (ORiON); KS/chi-square over-trigger on large n so distance metrics (PSI/TVD) are preferred (EvidentlyAI, NannyML); covariate & prediction drift are detectable offline but concept drift P(y|X) needs labels (Cloudera FFL; Huyen Chip); drift is one retraining trigger among several, and online/serving signals need live telemetry (Google MLOps).
