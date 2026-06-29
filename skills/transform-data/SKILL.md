---
name: transform-data
description: Reshape CLEAN tabular data into the exact shape a question needs — groupby + aggregate, pivot/melt (wide↔long), joins/merges, derived/computed columns, row filtering, and time resampling (daily→monthly). Generates a tailored pandas script, runs it with the project venv, and writes a NEW output file (parquet/csv) with before→after shapes. Use to prepare an analysis-ready table; NOT for fixing data defects (use clean-data) and NOT a SQL interface (use query-sql).
allowed-tools: Bash, Read, Write, Glob
---

# transform-data

Reshape a **clean** table into the precise shape one question needs. Transforms are *bespoke* — every question wants a different shape — so this skill has **no fixed script**: you generate a tailored `transform_<name>.py` each time, run it, and write a **new** output file.

Distinguish it from its neighbors:

- **clean-data** fixes *defects* (missing, dupes, wrong types, bad categories). transform-data assumes the data is already clean and changes its *shape*, not its quality.
- **query-sql** is an *ad-hoc SQL interface* for answering a question interactively. transform-data **persists** a reshaped table to disk for downstream EDA / charts / modeling.
- **eda** *reads* data to find patterns. transform-data *produces* the table EDA then reads.

## When to use
- You need an **analysis-ready** table that doesn't exist yet: "average Price per Brand × Year", "one row per customer with their order totals", "wide table of monthly revenue by region".
- The operation is one (or more) of: **groupby + aggregate**, **pivot / melt** (wide↔long), **join / merge** two tables, **derived / computed columns**, **filter** rows to a subset, **time resampling** (e.g. daily→monthly).
- The result will feed a chart, report, EDA notebook, or model — i.e. it's worth saving as a file, not just printing.

## Golden rules
- **Never overwrite the source.** Always write a NEW file (e.g. `<name>_agg.parquet`, `<name>_monthly.csv`).
- **Clean first.** Transforming messy data (wrong dtypes, dupes) silently corrupts aggregates. If it hasn't been profiled/cleaned this session, send the user to `profile-dataset` / `clean-data`.
- **State the target shape before writing code.** "What does ONE row of the output mean, and what are its columns?" is the whole design — agree on it first.
- **The script IS the log.** Keep the generated `transform_<name>.py`; it documents exactly how the output was produced and re-runs reproducibly.

## Steps
1. **Name the target shape.** Say it in one sentence: the **grain** (what one output row represents), the **columns**, and roughly how many rows you expect. Example: *"one row per (Brand, Year); columns = avg Price, median Kms_Driven, count."* Confirm before generating code.
2. **Propose the transform plan** — pick the operation(s) and state the choices, then **wait for confirmation**:
   - **Aggregate** → groupby key(s) + agg funcs per column (`mean`, `median`, `sum`, `count`, `nunique`, custom). Decide how to treat NaN groups and whether to keep counts.
   - **Pivot / melt** → index, columns, values, and the agg for duplicates (pivot_table); or id_vars / value_vars (melt). State what fills empty cells.
   - **Join / merge** → keys, join type (`inner` / `left` / `outer`), and how to handle many-to-many or unmatched rows. Name the expected row count and watch for accidental fan-out.
   - **Derived columns** → the formula and dtype (e.g. `price_per_km = Price / Kms_Driven`, `age = 2026 - Year`). Guard divide-by-zero.
   - **Filter** → the exact predicate (e.g. `Year >= 2015 and Fuel_Type == "Petrol"`).
   - **Time resample** → the datetime column, frequency (`D`/`W`/`M`/`Q`), and agg per column.
3. **Generate `transform_<name>.py`** (pandas) that applies *exactly* the confirmed plan. The script must: load the source read-only; apply the transform; **print before→after shape** (`rows×cols`) and a `.head()` of the result; write the NEW output file; and fail loudly with a clear message (incl. an `ImportError` hint) rather than silently. Example invocation it should support:
   ```bash
   .venv/bin/python transform_used_car_by_brand_year.py \
       data/extracted/used_car_clean.parquet \
       --out used_car_by_brand_year.parquet
   ```
4. **Run it with the project venv:**
   ```bash
   [ -x .venv/bin/python ] || python3 -m venv .venv
   .venv/bin/python -c "import pandas, pyarrow" 2>/dev/null || \
     .venv/bin/pip install -q pandas numpy pyarrow openpyxl
   .venv/bin/python transform_<name>.py "<clean-file>" --out "<new-output-file>"
   ```
5. **Verify the shape.** Read the printed before→after and `.head()`. Confirm the grain is right (one row per intended key — check for unexpected duplicates after a merge), row count matches your estimate, and no aggregate is silently all-NaN. Flag anything surprising before declaring done.

## Notes
- **Output format:** parquet by default (preserves dtypes, compact); csv only if a human/tool downstream needs plain text. Pass it via `--out`.
- **Merge fan-out is the classic trap.** A many-to-many join multiplies rows; if `after` rows ≫ either input, the keys aren't as unique as assumed — stop and re-check before saving.
- **Resampling needs a real datetime index.** Confirm the time column parsed to `datetime64` (clean-data's job) before resampling; resampling a string column fails or misorders.
- **Aggregates hide row loss.** Going from 1,000,000 rows to a few hundred groups is expected and fine — but note it explicitly so nobody mistakes the small output for lost data.
- **Chain, don't mutate the source.** Multiple transforms = multiple scripts/outputs (`*_agg`, then `*_agg_filtered`). Each step is re-runnable and the lineage stays auditable.
