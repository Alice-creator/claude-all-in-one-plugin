---
name: profile-dataset
description: Profile a tabular data file (CSV/TSV/Excel/Parquet/JSON) — report shape, per-column types, missing values, duplicates, outliers, and data-quality issues. Read-only; never modifies the data. Use right after receiving an unfamiliar data file, before any analysis, or when results look wrong and you suspect the data.
---

# profile-dataset

Diagnose a dataset's **structure and quality without changing it**. This is the read-only "check-up" you run before trusting or analyzing any data file — the answer to *"What's in here, and is it usable?"*

## When to use
- A new / unfamiliar data file just arrived (export, download, handed over).
- Before any analysis — understand the data first.
- Analysis gave weird results and you suspect the underlying data.
- Deciding whether the data is good / complete enough to answer a question.

## Contract (important)
- **READ-ONLY.** Never modify, move, or overwrite the input file. Do **not** produce a cleaned version here — that is the `clean-data` skill's job.

## Steps
1. **Locate the file.** If the user didn't give an exact path, use Glob (`**/*.{csv,tsv,xlsx,xls,parquet,json}`) and confirm which file they mean.
2. **Get a Python with pandas.** Prefer a project venv; create it if missing:
   ```bash
   [ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -q pandas numpy openpyxl pyarrow; }
   ```
   Use `.venv/bin/python` for the next step (fall back to `python3` only if a venv can't be created).
3. **Run the bundled profiler:**
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/profile-dataset/scripts/profile.py" "<path-to-file>"
   ```
   - Specific Excel sheet: add `--sheet "<name>"`.
   - If `${CLAUDE_PLUGIN_ROOT}` is unset (running from the repo directly), use the script path under this skill folder: `skills/profile-dataset/scripts/profile.py`.
4. **Interpret — don't just dump the output.** Lead with a one-line verdict (is the data usable?), then highlight the top issues (missingness, duplicates, wrong types, outliers) and the inferred structure.
5. **Recommend next steps.** If issues were found, suggest running `clean-data` and which fixes. If clean, say it's ready for EDA / analysis.

## Output style
- Open with a one-line verdict, e.g. *"Usable, but 3 issues to fix first."*
- Use a short table or bullets for the key columns/issues — not a wall of raw output.
- Always state explicitly that the file was **not** modified.
