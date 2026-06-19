---
name: eda
description: Run exploratory data analysis (EDA) on a CLEAN tabular file and produce an executed Jupyter notebook (.ipynb) — distributions, correlations, categorical breakdowns, and (optionally) what relates to a target column. Use after the data is clean, when the question is "what does this data tell me?". For deeper, iterative, question-driven exploration use the data-analyst / eda-analyst agent instead.
---

# eda

Generate a baseline **exploratory data analysis** report as an executed Jupyter notebook. EDA answers *"what does this data tell me?"* — distributions, relationships, segments — as opposed to `profile-dataset` which answers *"is this data usable?"*. Run EDA on **clean** data (profile/clean first if needed).

## When to use
- The data is clean and you want to understand its patterns before reporting or modeling.
- You want a shareable, re-runnable `.ipynb` with charts, not just terminal output.

## Steps
1. **Ensure the Python env** (with notebook deps):
   ```bash
   [ -x .venv/bin/python ] || python3 -m venv .venv
   .venv/bin/python -c "import nbclient, matplotlib" 2>/dev/null || \
     .venv/bin/pip install -q pandas numpy pyarrow openpyxl nbformat nbclient ipykernel matplotlib
   ```
2. **Build the notebook** (un-executed):
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/eda/scripts/eda_notebook.py" "<clean-file>" --target "<target-col-or-omit>"
   ```
3. **Execute it** (runs every cell, embeds charts/outputs, reports any cell errors):
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/eda/scripts/run_notebook.py" "<clean-file-name>_eda.ipynb"
   ```
   - Exit 0 = clean. Exit 3 = a cell errored (stderr lists `CELL N ERROR: ...`) — fix that cell and re-run.
4. **Interpret** — read the executed outputs and summarize the key findings (top correlations, notable distributions, segment differences). Point the user at the `.ipynb`.

## Notes
- Input should be **clean** data; EDA on messy data gives misleading patterns.
- The baseline is deterministic boilerplate. For question-driven, deeper exploration that adapts to the data, use the **eda-analyst** agent (it extends this notebook and iterates on code errors).
