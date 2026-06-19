---
name: readiness-check
description: Pre-deployment readiness audit of a modeling pipeline directory — scores the artifacts (split_summary.json, baseline_metric.json, tuned_metric.json, experiments.jsonl, evaluation report) against an ML Test Score-style checklist for leakage-safe splitting, a beaten baseline, recorded tuning, reproducibility metadata, and test-set holdout. Read-only; re-runs nothing. Honestly defers every check that needs live serving telemetry (monitoring, infra, latency) as not-auto-checkable. Writes readiness_report.md with a Mermaid diagram. Use after the full pipeline, before anyone says "ship it".
allowed-tools: Bash, Read, Write, Glob
---

# readiness-check

Turn *"the metric looks good"* into an **evidence-backed readiness verdict**. After the pipeline has run, this audits what's on disk — was the split leakage-safe? is there a baseline the tuned model beat? was the run reproducible (seed + data hash)? was the test set kept out of selection? — and scores it against an ML Test Score–style checklist (Breck et al. 2017). It checks **evidence that a step was done**, not whether the model is *good* (that's `evaluate-model`).

## When to use
- After `split-dataset → baseline → train-tune → evaluate-model`, as a **pre-deployment gate**.
- To audit a pipeline directory a teammate produced — it re-derives the verdict from the artifacts.
- For a handoff/review doc stating, per category, what's proven on disk vs. what needs production sign-off.

## Contract (important)
- **Read-only.** Parses existing artifacts; never re-runs, re-trains, or loads a model. Sole write: `readiness_report.md`.
- **Audits process evidence, not quality.** A PASS means "the artifact proving this step exists and is internally consistent" (e.g. a seed is logged; test wasn't used for selection) — **not** "the model is accurate." It does not re-judge metric values.
- **Reads JSON artifacts, not report prose.** Leakage status comes from `split_summary.json`, the baseline bar from `baseline_metric.json`, etc. — robust to wording changes in the human reports.
- **Test-holdout is role-aware.** `eval_on=test` in a **selection** artifact (baseline / tuned / experiments) is a FAIL (selecting on test contaminates the estimate). A terminal `evaluate-model` run on test is the **correct** final step and is **not** penalized.
- **Honest scoring.** The strict ML Test Score (min over all 4 sections) is ~0 offline because Monitoring is unobservable without production telemetry — so the headline is the fraction of *offline-auto-checkable* checks passed, with an **explicitly non-canonical** indicative label. Every monitoring/infra/fairness item that needs live data is marked NOT-AUTO-CHECKABLE, never silently passed or failed.
- **Trusts artifacts as-is.** It cannot re-verify that training was actually deterministic, only that the reproducibility metadata is present.

## Steps
1. **Run the pipeline first** (split → baseline → train-tune → evaluate-model). readiness-check audits their outputs.
2. **Run it** (pure stdlib — no extra deps):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/readiness-check/scripts/readiness_check.py" --pipeline-dir "<name>_splits"
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/readiness-check/scripts/readiness_check.py`. It globs the tree, so nested out-dirs like `train-tune/evaluation/` are found.)
3. **Read the verdict + gaps.** Lead with the offline-readiness fraction and label, then the **Gaps to close** list (each points back to the upstream skill to re-run). State plainly that a high score is **not** a deploy approval.
4. **Hand off:** point to `check-drift` as the only offline monitoring proxy once a new data batch exists.

## Output style
- One-liner first: e.g. *"offline-readiness: 7.0/7.0 (strong) | 0 FAIL, 0 PARTIAL."*
- Show the Mermaid (4 sections + offline-readiness + a "Monitoring deferred to production" node) and the per-category check tables.
- Always restate the offline limit: monitoring/serving/business readiness is unverifiable here and remains the human's responsibility.

## Grounding
The rubric, the four categories, and the scoring rule (0.5 manual / 1.0 automated per check, section sums, strict score = min of sections) are from the ML Test Score paper (Breck et al., Google, IEEE Big Data 2017). Monitoring and serving-infra tests require live production telemetry (Google MLOps), so an offline audit defers them. Leakage avoidance via learn-predict separation and test-holdout discipline are the verifiable offline practices it audits (Kapoor & Narayanan 2023).
