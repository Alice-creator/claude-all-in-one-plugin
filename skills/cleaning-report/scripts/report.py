#!/usr/bin/env python3
"""report.py — render a cleaning-run JSON log into a Mermaid-rich Markdown report.

Pure stdlib (no pandas). Visualizes each iteration: what was profiled and edited.

Usage:
    python3 report.py <cleaning_run.json> [-o cleaning_report.md]
"""
import argparse
import json
import sys


def esc(s):
    """Make a string safe inside a Mermaid label / table cell."""
    return str(s).replace('"', "'").replace("|", "\\|").replace("\n", " ")


def fmt(n):
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n) if n is not None else "?"


def main():
    ap = argparse.ArgumentParser(description="Render a cleaning run log into a Markdown report.")
    ap.add_argument("run", help="Path to cleaning_run.json")
    ap.add_argument("-o", "--out", default="cleaning_report.md")
    a = ap.parse_args()

    try:
        with open(a.run) as f:
            d = json.load(f)
    except Exception as e:
        print(f"ERROR reading {a.run}: {e}", file=sys.stderr)
        sys.exit(1)

    ds = d.get("dataset", "(dataset)")
    out = d.get("output", "")
    iters = d.get("iterations", [])
    res = d.get("result", {})
    gate = d.get("quality_gate", {})

    loss = res.get("row_loss_pct")
    loss_txt = f"{loss}" if isinstance(loss, (int, float)) else "?"

    L = []
    L.append(f"# 🧹 Data Cleaning Report — `{ds}`\n")

    # --- At a glance (project hard rule: open with `## At a glance` + a Mermaid block) ---
    L.append("## At a glance\n")
    L.append(f"**{len(iters)} round(s)** · {fmt(res.get('rows_in'))} → {fmt(res.get('rows_out'))} rows "
             f"({loss_txt}% removed) · quality gate {'✅ PASSED' if res.get('gate_passed') else '⚠️ NOT MET'}.\n")
    L.append("```mermaid")
    L.append("flowchart LR")
    first_rows = iters[0].get("before", {}).get("rows") if iters else res.get("rows_in")
    L.append(f'    S["📥 Raw<br/>{fmt(first_rows)} rows"]')
    prev = "S"
    for it in iters:
        r = it.get("round")
        nid = f"R{r}"
        nfix = len(it.get("edits", []))
        b = it.get("before", {}).get("rows")
        af = it.get("after", {}).get("rows")
        dtxt = ""
        if isinstance(b, (int, float)) and isinstance(af, (int, float)) and af - b:
            dtxt = f"<br/>{int(af - b):+,} rows"
        L.append(f'    {nid}["🔁 Round {r}<br/>{nfix} fixes{dtxt}"]')
        L.append(f"    {prev} --> {nid}")
        prev = nid
    gate_txt = "✅ Clean — gate passed" if res.get("gate_passed") else "⚠️ Gate not met"
    L.append(f'    DONE["{gate_txt}<br/>{fmt(res.get("rows_out"))} rows"]')
    L.append(f"    {prev} --> DONE")
    L.append("```")
    L.append("")

    # --- Summary ---
    L.append("## Summary\n")
    L.append("| Field | Value |")
    L.append("|---|---|")
    L.append(f"| Source | `{ds}` (unchanged) |")
    if out:
        L.append(f"| Output | `{out}` |")
    L.append(f"| Iterations | {len(iters)} |")
    L.append(f"| Rows in → out | {fmt(res.get('rows_in'))} → {fmt(res.get('rows_out'))} "
             f"({loss_txt}% removed) |")
    L.append(f"| Quality gate | {'✅ PASSED' if res.get('gate_passed') else '⚠️ NOT MET'} |")
    L.append(f"| Stopped because | {esc(res.get('stopped_because', '?'))} |")
    L.append("")

    # --- Per-round detail ---
    for it in iters:
        r = it.get("round")
        b, af = it.get("before", {}), it.get("after", {})
        found = it.get("found", [])
        edits = it.get("edits", [])
        L.append(f"## Round {r}\n")
        L.append(f"**Before → After:** {fmt(b.get('rows'))} → {fmt(af.get('rows'))} rows · "
                 f"duplicates {fmt(b.get('duplicates'))} → {fmt(af.get('duplicates'))} · "
                 f"missing {fmt(b.get('total_missing'))} → {fmt(af.get('total_missing'))}\n")

        # mini per-round diagram
        L.append("```mermaid")
        L.append("flowchart LR")
        L.append(f'    F{r}["🔍 Found<br/>{len(found)} issues"] --> '
                 f'E{r}["🧹 Edited<br/>{len(edits)} actions"] --> '
                 f'A{r}["✅ After<br/>{fmt(af.get("rows"))} rows<br/>{fmt(af.get("duplicates"))} dup"]')
        L.append("```")
        L.append("")

        if found:
            L.append("**🔍 Profiled — issues found:**\n")
            L.append("| Column | Issue | Detail | Action |")
            L.append("|---|---|---|---|")
            for f_ in found:
                act = "✅ fix" if f_.get("fixable") else "— keep"
                L.append(f"| `{esc(f_.get('column', ''))}` | {esc(f_.get('issue', ''))} "
                         f"| {esc(f_.get('detail', ''))} | {act} |")
            L.append("")
        if edits:
            L.append("**🧹 Edited — actions taken:**\n")
            L.append("| Action | Detail |")
            L.append("|---|---|")
            for e in edits:
                L.append(f"| `{esc(e.get('action', ''))}` | {esc(e.get('detail', ''))} |")
            L.append("")

    # --- Remaining ---
    rem = res.get("remaining_warnings", [])
    if rem:
        L.append("## Remaining (intentionally kept)\n")
        for w in rem:
            L.append(f"- {esc(w)}")
        L.append("")

    # --- Quality gate ---
    if gate:
        L.append("## Quality gate applied\n")
        L.append("```json")
        L.append(json.dumps(gate, indent=2))
        L.append("```")
        L.append("")

    with open(a.out, "w") as f:
        f.write("\n".join(L))
    print(f"Wrote {a.out}  ({len(iters)} iteration(s))")


if __name__ == "__main__":
    main()
