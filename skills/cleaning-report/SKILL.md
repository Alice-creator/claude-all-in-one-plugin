---
name: cleaning-report
description: Render a data-cleaning run log (cleaning_run.json) into a Mermaid-diagram Markdown report that visualizes each iteration — what was profiled and what was edited. Used by the data-cleaner agent as its final step, or standalone to re-render a report from an existing run log.
---

# cleaning-report

Turn a structured cleaning run log into a **visual Markdown report** with Mermaid diagrams documenting every iteration (issues found -> edits applied -> result).

## When to use
- Automatically, as the final step of the `data-cleaner` agent.
- Standalone, to re-render a report from an existing `cleaning_run.json`.

## Usage
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cleaning-report/scripts/report.py" <cleaning_run.json> -o cleaning_report.md
```

The report contains:
- a **summary** table (source, output, rows in/out, gate pass/fail, stop reason),
- an **iteration-flow** Mermaid diagram across all rounds,
- per round: a **mini Mermaid diagram** (found -> edited -> result) plus *found* and *edited* tables,
- **intentionally-kept** issues (e.g. outliers) and why,
- the **quality gate** used.

The script is pure-Python (stdlib only — no pandas needed) and expects the JSON schema documented in the `data-cleaner` agent.
