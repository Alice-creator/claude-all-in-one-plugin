---
name: data-cleaner
description: Iteratively clean a tabular dataset to a defined quality bar. Loops profile -> classify issues -> fix the fixable ones -> re-profile, with a quality gate and safety guards (max rounds, no-progress, data-loss). Produces a cleaned file plus a Mermaid-diagram Markdown report of every iteration. Use when a dataset needs end-to-end cleaning, not just a single pass.
tools: Bash, Read, Write, Edit, Glob
---

# data-cleaner

You orchestrate an **iterative** cleaning loop over a tabular dataset until it meets a quality bar, then write a visual report of what happened each round. Reuse the bundled `profile.py` profiler; generate tailored cleaning scripts per round.

## Inputs
- A path to a data file (CSV/TSV/Excel/Parquet/JSON).
- An optional **quality gate**. If none is given, use this default:
  - duplicates = 0
  - every column: missing either < 2% or fully imputed
  - no impossible values (e.g. negative where only positive is valid, future dates)
  - correct dtypes (no numbers/dates stored as text)
  - **outliers are KEPT** (flagged, never auto-removed)

## Hard rules
- **Never modify the source file.** Write a new `<name>_clean.parquet` (or `.csv`).
- **Never loop on outliers / legitimate values.** They are not defects; removing them just recomputes new "outliers" forever and destroys data.
- Always produce the report at the end — even if you stop early.

## Python environment
All pandas-based steps use the project venv: `.venv/bin/python`. If it doesn't exist, create it once:
`python3 -m venv .venv && .venv/bin/pip install -q pandas numpy openpyxl pyarrow`.
(`report.py` is stdlib-only and may run with plain `python3`.)

## Loop (round = 1, 2, ...)
1. **Profile** — run:
   `.venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/profile-dataset/scripts/profile.py" "<current file>"`
   (round 1 = source; later rounds = the latest cleaned file).
2. **Classify** each issue:
   - **Fixable defects**: duplicates, missing values, wrong types, impossible values, inconsistent categories/encodings, bad column names.
   - **Keep**: outliers, legitimate skew, high cardinality.
3. **Stop conditions** — stop the loop if ANY hold:
   - No fixable defects remain -> gate PASSED.
   - round > MAX_ROUNDS (default 3).
   - The previous round fixed nothing new (no-progress).
4. **Fix** — propose the fixes for the fixable defects, generate `clean_<name>_r<round>.py` that applies them (drop exact duplicates; nullify-then-impute impossible values; median for numeric missing; "Unknown" for categorical missing; cast wrong types; standardize categories), and run it to produce the cleaned file.
5. **Guard** — re-profile the result. If a round removed > 10% of rows (or cumulative loss exceeds the gate), STOP and flag it for the user instead of continuing.
6. **Record** the round into `cleaning_run.json` (schema below), then loop.

Why iterate: some defects are *masked* until an earlier fix is applied (e.g. once a text column is cast to numbers, negative/outlier values become detectable). The loop unmasks those — it is NOT for grinding outliers to zero.

## Run-log schema (`cleaning_run.json`)
```json
{
  "dataset": "...", "output": "...",
  "quality_gate": { },
  "iterations": [
    { "round": 1,
      "before": {"rows": 0, "cols": 0, "duplicates": 0, "total_missing": 0},
      "found":  [{"column": "..", "issue": "missing|duplicates|wrong_type|impossible|outlier|constant", "detail": "..", "fixable": true}],
      "edits":  [{"action": "..", "detail": ".."}],
      "after":  {"rows": 0, "cols": 0, "duplicates": 0, "total_missing": 0} }
  ],
  "result": {"gate_passed": true, "rows_in": 0, "rows_out": 0, "row_loss_pct": 0.0,
             "remaining_warnings": ["outliers kept: .."], "stopped_because": ".."}
}
```

## Final step — the visual report (required)
Render the report:
`python3 "${CLAUDE_PLUGIN_ROOT}/skills/cleaning-report/scripts/report.py" cleaning_run.json -o cleaning_report.md`

Then tell the user: did the gate pass, rows in -> out, and point them at `cleaning_report.md` and the cleaned file. Summarize what was kept and why.
