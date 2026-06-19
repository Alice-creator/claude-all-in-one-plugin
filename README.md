# claude-all-in-one-plugin

An all-in-one Claude Code plugin. **First focus: data analysis.**

## Skills

| Skill | What it does |
|-------|--------------|
| `frame-ml-problem` | **Upstream of any modeling** — turns a fuzzy business goal into a well-posed ML problem: separates the ideal outcome from the model's goal, gates on whether ML is even needed, and defines business success metrics vs. technical evaluation metrics. Writes a reviewable Problem Framing Brief. |
| `profile-dataset` | **Read-only** profiling of a data file — shape, types, missingness, duplicates, outliers, quality warnings. Run it first on any new dataset. |
| `clean-data` | Fixes data-quality issues (missing, duplicates, types, categories, outliers) by proposing a plan, generating + running a Python script, and writing a **new** cleaned file + change log. |
| `split-dataset` | Splits a cleaned dataset into **train/val/test the leakage-safe way** — picks the method (random+stratified · group/entity-aware · temporal), keeps dev & test same-distribution, verifies no row/entity leaks, and writes the splits + a `split_report.md` (with a Mermaid diagram). |
| `baseline` | Establishes the **number to beat** — trains a Dummy floor + one simple model (logistic/linear), scores on val, and writes a `baseline_report.md` (Mermaid metric ladder), a predictions file for `evaluate-model`, and a machine-readable `baseline_metric.json`. Tells you whether a complex model is even worth it. |
| `select-model` | **Advisory** — fingerprints the data (size, features, cardinality, task, modality) and applies a research-grounded decision tree to recommend classic ML vs deep learning (flags RL as a separate paradigm), bounded by the baseline number and interpretability/latency vetoes. Writes `model_recommendation.md` (Mermaid decision tree). Recommends; does not train. |
| `train-tune` | Tunes a **tabular** model the leakage-safe way — `RandomizedSearchCV` with the preprocessor INSIDE the CV pipeline (CV on train only), reports tuned-vs-baseline honestly, logs every run (params/seed/data-hash) to `experiments.jsonl`, and emits predictions in the same schema `evaluate-model` consumes. DL/GPU/RL refused. |
| `evaluate-model` | Evaluates a model from a **predictions file** (framework-agnostic) — overall metrics, confusion matrix / residuals, and a **slice-based error analysis** surfacing the worst subgroups. Honestly flags what offline eval can't measure (online performance, root cause). |
| `check-drift` | Detects **population drift** between two snapshots (reference vs current) — per-feature PSI (Laplace-smoothed) + TVD/optional KS, plus separate target P(y) and prediction P(y_pred) drift. Offline & label-free; refuses concept drift without labels, model-quality, and live monitoring. Writes `drift_report.md`. |
| `readiness-check` | **Pre-deployment audit** — scores the pipeline artifacts (leakage-safe split, beaten baseline, recorded tuning, reproducibility metadata, role-aware test-holdout) against an ML Test Score–style checklist. Read-only, pure stdlib; defers every check needing live telemetry. Writes `readiness_report.md`. |

They chain naturally: **frame → profile → (decide) → clean → re-profile → split → baseline → select-model → train-tune → evaluate**, then the offline deploy-monitor pair **check-drift** (new data batch) and **readiness-check** (pre-ship audit). Each is also useful on its own.

## Agents

Conductors that drive a whole lifecycle stage-by-stage using the skills above, **stopping at human-decision checkpoints** (they don't reinvent the skills, and a subagent can't spawn subagents — they inline each skill's steps).

| Agent | What it conducts |
|-------|------------------|
| `data-analyst` | The **analysis** lifecycle — profile → clean → EDA → validate → visualize → report — to turn a dataset into validated, reportable insight. Hands off to `model-builder` when the goal is a model. |
| `model-builder` | The **modeling** lifecycle — frame → split → baseline → select-model → train-tune → evaluate → (offline) readiness-check / check-drift. Enforces the disciplines (leakage-safe, baseline-before-complexity, offline≠online, test touched once) and stops at the *is-ML-worth-it*, *which-family*, *earns-its-keep*, and *deploy-ready* gates. Tabular only — refuses DL/RL. |

## Code quality (clean-code)

A pragmatic, **language-agnostic** clean-code ruleset (the "Part 7" rules: reader-first, intention-revealing names, low coupling/high cohesion, DRY by rule-of-three, one-level-of-abstraction functions, guard clauses, why-not-what comments, test-before-refactor, YAGNI — treated as heuristics with trade-offs, not dogma).

| Component | Type | What it does |
|-----------|------|--------------|
| `clean-code` | Skill | Invoke `/clean-code` for the **full ruleset** with each rule's trade-off and when *not* to apply it. Use before/while writing or refactoring code. |
| `clean-code-reviewer` | Agent | Audits a diff or set of files against the rules and returns prioritized findings (rule no. + location + fix). Pragmatic — flags real issues, not nitpicks. |
| clean-code reminder | Hook | `PostToolUse` on `Write\|Edit\|MultiEdit`: after a **source file** is changed, injects the compact 10-rule checklist into context. Filters by extension — config/docs/data files (`.md`, `.csv`, `.json`, …) stay silent. Script: `hooks/clean-code-reminder.py`. |

The three layers are deliberately split so the hook stays lightweight: a short nudge on every code edit, with the full detail one `/clean-code` (or agent) call away.

> **Activation:** for other users, the hook ships with the plugin and fires once the plugin is installed. The author also keeps a machine-wide copy under `~/.claude/` (skill, agent, and the hook in `~/.claude/settings.json` → `PostToolUse`) so it runs in **every** repo without installing the plugin. If you run both at once in the same repo, the reminder fires twice — keep only one source.

## Install

```
/plugin marketplace add Alice-creator/claude-all-in-one-plugin
/plugin install claude-all-in-one-plugin@claude-all-in-one
```

For local development from a clone (point at the clone's absolute path, then install):

```
/plugin marketplace add /path/to/claude-all-in-one-plugin
/plugin install claude-all-in-one-plugin@claude-all-in-one
```

Plugins install at the user level — once installed, the skills and agents are available in **every** repo (restart Claude Code so they register). The GitHub install above reads the repo's default branch, so push/merge to `main` before using it.

## Requirements

The data skills use Python with `pandas` (plus `openpyxl` for Excel, `pyarrow` for Parquet). The modeling skills (`baseline`, `select-model`, `train-tune`, `check-drift`) additionally need `scikit-learn` and `scipy` (`readiness-check` is stdlib-only):

```
pip install pandas numpy scikit-learn scipy openpyxl pyarrow
```

## Roadmap

Data analysis is the first domain. Planned components (grounded in research):

- **Skills:** `eda`, `transform-data`, `query-sql`, `build-chart`, `report`
- **Agents:** `data-analyst` (plan → code → execute), `verify-analysis` (re-runs code to catch errors)
- **MCP:** SQL / database connector
