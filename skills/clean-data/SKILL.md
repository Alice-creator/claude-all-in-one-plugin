---
name: clean-data
description: Clean a tabular dataset — fix missing values, remove duplicates, correct data types, standardize categories/encodings, handle outliers. Proposes a plan, applies it on confirmation by generating and running a Python script, and writes a NEW cleaned file plus an auditable change log. Use after profiling reveals quality issues, or when preparing raw/multi-source data for analysis.
allowed-tools: Bash, Read, Write, Glob
---

# clean-data

Turn a raw / messy dataset into a clean, trustworthy one — **transparently and reproducibly**. Unlike profiling, this skill *changes data*, so it works by proposing a plan, generating a script you can review, and writing a **new** file (never overwriting the original).

## When to use
- After `profile-dataset` surfaced issues that need fixing.
- Preparing raw / multi-source data for analysis, charts, or a report.
- Standardizing inconsistent values (dates, currencies, country names) or fixing encoding / whitespace from hand-entered data.

## Golden rules
- **Profile first.** If you haven't already, run `profile-dataset` so you know what you're fixing. Cleaning blind is like operating without a diagnosis.
- **Never overwrite the source.** Always write a new file (e.g. `<name>_clean.parquet`).
- **Every fix is the user's call.** Drop vs. impute, cap vs. remove outliers — these are trade-offs. Propose, don't assume.
- **Reproducible + machine-readable.** The generated script IS the log — keep it. Also emit a **`cleaning_run.json`** sidecar (project convention: a machine-readable sidecar next to any human report) in the schema `cleaning-report` consumes, so the same run renders to a visual report and is parseable downstream.

## Steps
1. **Review the profile.** Run `profile-dataset` first if it hasn't been done this session.
2. **Propose a cleaning plan** — for each issue, state the fix and its trade-off, then **wait for confirmation**:
   - Missing values -> drop rows / drop column / impute (mean · median · mode · forward-fill · constant)
   - Duplicates -> drop full-row, or by key column(s)
   - Wrong types -> cast text->number, string->date (state the expected format)
   - Inconsistent categories -> explicit mapping (e.g. "USA" / "us" / "U.S.A" -> "United States")
   - Outliers -> flag / cap (winsorize) / remove
   - Column names -> normalize to snake_case
3. **Generate the cleaning script** `clean_<name>.py` (pandas/polars) that applies *exactly* the confirmed plan, prints a before/after summary (row & column counts, what changed), and **writes a `cleaning_run.json`** sidecar (schema below).
4. **Run it with the project venv** to produce the cleaned file plus `cleaning_run.json`. Use `.venv/bin/python clean_<name>.py`; if the venv is missing, create it once: `python3 -m venv .venv && .venv/bin/pip install -q pandas numpy openpyxl pyarrow`. Then render the visual report with the **`cleaning-report`** skill (don't hand-write Markdown):
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/cleaning-report/scripts/report.py" cleaning_run.json -o cleaning_report.md
   ```
5. **Verify** — re-run `profile-dataset` on the cleaned file. Confirm the issues are resolved and that row counts changed only as expected. Flag anything surprising (e.g. dropped more rows than planned) before declaring done.

## `cleaning_run.json` schema (single-pass → one round)
This is the SAME schema the iterative `data-cleaner` agent uses, so both cleaning paths feed `cleaning-report` unchanged:
```json
{
  "dataset": "data/raw.csv", "output": "data/raw_clean.parquet",
  "iterations": [{
    "round": 1,
    "before": {"rows": 1000, "duplicates": 12, "total_missing": 240},
    "after":  {"rows": 985,  "duplicates": 0,  "total_missing": 0},
    "found":  [{"column": "price", "issue": "missing", "detail": "240 nulls (24%)", "fixable": true}],
    "edits":  [{"action": "impute_median", "detail": "price: filled 240 nulls with median 18000"}]
  }],
  "result": {"rows_in": 1000, "rows_out": 985, "row_loss_pct": 1.5,
             "gate_passed": true, "stopped_because": "all planned fixes applied",
             "remaining_warnings": ["outliers in price KEPT (flagged, not removed)"]},
  "quality_gate": {"max_missing_pct": 0, "max_duplicate_rows": 0}
}
```

## Output style
- Show the plan as a checklist **before** doing anything.
- After running, give a concise before -> after diff (rows, columns, issues fixed).
- Point to the new file, the kept script, and the rendered `cleaning_report.md` (reproducibility + a visual, parseable trail).
