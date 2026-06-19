---
name: query-sql
description: Answer a question about a CSV/Parquet/JSON file by writing SQL and running it directly with DuckDB (no database server) — aggregations, filters, GROUP BY, JOINs, window functions. Reads the file in place as a table named `data`, prints the result. Read-only on the source. Use when the question is a lookup/count/aggregate/ranking ("how many...", "average X by Y", "top N..."), or when the file is large and a pandas load would be slow.
---

# query-sql

Turn a data question into a SQL query and run it **directly against a file** — no server, no import step. DuckDB reads CSV / Parquet / JSON in place and is fast for aggregations, filters, GROUP BY, JOINs, and window functions even on files with millions of rows. This skill is **read-only**: it never writes to the source data.

## When to use
- The question is fundamentally a query: a count, sum, average, ranking, filter, or breakdown — e.g. *"how many rows per Brand?"*, *"average Price by Fuel_Type"*, *"top 10 models by mileage"*, *"rows where Accidents > 0"*.
- The file is **large** (hundreds of thousands of rows or more) and you just need an answer — DuckDB streams and aggregates without loading everything into a DataFrame.
- You need a JOIN or window function and SQL expresses it more clearly than pandas.

**Prefer `transform-data` (pandas) instead when** you need to *produce a new cleaned/reshaped file*, do row-wise feature engineering, or feed the result into matplotlib / sklearn. SQL is for **asking**; pandas transforms are for **building**. (Query first to understand, then transform if you need a new artifact.)

## Steps
1. **Know the columns.** If you haven't already seen the schema this session, peek first so column names in your SQL are exact:
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/query-sql/scripts/run_sql.py" "<file>" "SELECT * FROM data LIMIT 5"
   ```
2. **Write the SQL.** Reference the file as the table `data` (it is registered as a view). Express the question:
   - count / breakdown -> `SELECT col, COUNT(*) FROM data GROUP BY col ORDER BY ...`
   - aggregate -> `SELECT AVG(Price), MAX(Price) FROM data WHERE Fuel_Type = 'Petrol'`
   - ranking -> `... ORDER BY metric DESC LIMIT 10`
3. **Run it** with the project venv:
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/query-sql/scripts/run_sql.py" "<file>" "<SQL>" --limit 50
   ```
   - `--limit N` caps **printed** rows (default 50; `--limit 0` prints all). It does not alter your query — put `LIMIT` in the SQL if you want the query itself bounded.
   - Exit 3 = query or load error (stderr shows the message; binder errors list candidate column names — fix the SQL and re-run). Exit 1 = file not found. Exit 2 = duckdb missing.
4. **Interpret** — read the printed table and answer the user's question in words (don't just dump rows). State the numbers that matter and any caveat (e.g. nulls excluded by an aggregate, a filter that dropped most rows).

## Notes
- **Read-only.** The connection is in-memory and ephemeral; the source file is never modified.
- DuckDB **infers types and delimiters** automatically (CSV sniffing, Parquet schema). If a column comes through as text when you expect a number, `CAST(col AS DOUBLE)` in the query.
- Column names with spaces or punctuation must be **double-quoted** in SQL: `SELECT "Color intensity" FROM data`.
- For repeated drill-downs on the same large file, **Parquet is much faster than CSV** (columnar, no re-parsing) — consider converting once via `transform-data` if you'll query it many times.
- This runs a single query per call. For a multi-step analysis with charts and narrative, use the `eda` skill / `eda-analyst` agent instead.
