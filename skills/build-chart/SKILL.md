---
name: build-chart
description: Build a single presentation-quality chart (PNG) from a tabular file for a final report or slide — bar, grouped-bar, line, hist, scatter, or box, with labels, title, top-N filtering, and mean/median/sum/count aggregation. Use when you need a polished, shareable figure to communicate a finding. For quick exploratory plots inside a notebook use the `eda` skill instead.
allowed-tools: Bash, Read, Glob
---

# build-chart

Turn one question into one clean, report-ready chart saved as a PNG. These are **presentation** figures — clear title, labeled axes, sensible size and dpi — meant for the final report or a slide. That is the opposite end from `eda`, whose plots are quick and exploratory ("what's going on here?"). Here you already know the finding; you're communicating it.

## When to use
- You have a specific finding to show (e.g. "luxury brands cost ~3x more") and want a polished figure for a report or deck.
- You want a deterministic, re-runnable chart command rather than hand-written matplotlib.
- The data is **clean** — profile/clean first if it isn't, or the chart will mislead.

## Pick the right chart for the question
- **Distribution** of one variable -> `hist` (numeric) or `box` (numeric, optionally split by a category via `--x`).
- **Comparison** across categories -> `bar` (one category) or `grouped-bar` (a category split by a second one via `--hue`).
- **Relationship** between two numerics -> `scatter`.
- **Trend** over an ordered axis (time, year) -> `line`.

## Steps
1. **Ensure the Python env** (with plotting deps):
   ```bash
   [ -x .venv/bin/python ] || python3 -m venv .venv
   .venv/bin/python -c "import matplotlib, pandas" 2>/dev/null || \
     .venv/bin/pip install -q pandas matplotlib pyarrow openpyxl
   ```
2. **Render the chart** with the bundled helper. Examples:
   ```bash
   # comparison — top 10 categories, aggregated
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/build-chart/scripts/chart.py" \
     "<clean-file>" --kind bar --x Brand --y Price --agg mean --top 10 \
     --title "Avg price by brand" -o avg_price_by_brand.png

   # distribution
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/build-chart/scripts/chart.py" \
     "<clean-file>" --kind hist --x Price -o price_dist.png

   # relationship
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/build-chart/scripts/chart.py" \
     "<clean-file>" --kind scatter --x Horsepower --y Price

   # multi-series comparison
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/build-chart/scripts/chart.py" \
     "<clean-file>" --kind grouped-bar --x Brand --y Price --hue Fuel_Type --agg mean --top 8
   ```
3. **Point the user at the saved PNG** (the script prints the absolute path) and state in one line what the chart shows.

## Notes
- `--agg` (`mean`·`median`·`sum`·`count`) applies to `bar`/`grouped-bar`/`line`; `--agg count` ignores `--y` and counts rows per category.
- `--top N` keeps the N largest categories so a `bar`/`grouped-bar`/`box` stays readable instead of cramming hundreds of ticks.
- Default output is `<kind>_chart.png`; pass `-o` to name it for the report. dpi is 110 — fine for slides and docs.
- Read-only on the data: the script never modifies the source file. One chart per call — make several calls for several figures.
- A missing/wrong column exits non-zero and prints the available columns, so check the name and re-run. `hist`/`scatter` coerce their columns to numeric and drop non-numeric values.
