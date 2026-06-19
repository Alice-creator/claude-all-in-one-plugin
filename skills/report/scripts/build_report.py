#!/usr/bin/env python3
"""build_report.py — assemble a final analysis deliverable from a VALIDATED spec.

Reads a report spec (JSON) describing the executive summary, validated findings
(each WITH a verdict from verify-analysis), supporting chart images, the analysis
pipeline, method/lineage, and explicit caveats. Emits a structured `report.md`
(and optionally an executed-style `.ipynb` skeleton).

CARDINAL RULE — enforced here, not just in prose: a finding is rendered in the
"Key findings" section ONLY if its verdict is one of the validated verdicts
(default: supported / confirmed / validated). Anything else (refuted, unverified,
inconclusive, missing verdict) is moved to CAVEATS and never presented as a
conclusion. Use --strict to hard-fail instead if any finding lacks a verdict.

This is pure stdlib (no pandas) — it only stitches text/links the caller already
validated upstream. It NEVER touches source data.

Spec schema (JSON):
{
  "title": "Used-car pricing — what drives Price",
  "dataset": "data/extracted/used_car_clean.parquet",
  "executive_summary": "2-4 sentence plain-language takeaway.",
  "findings": [
    {
      "claim": "Newer cars sell for more — Price rises ~X with Year.",
      "verdict": "supported",                 # supported|confirmed|validated|refuted|inconclusive|unverified
      "confidence": "high",                   # high|medium|low (free text ok)
      "evidence": "Spearman r=0.62 (p<1e-9), holds within each Fuel_Type.",
      "charts": ["charts/price_vs_year.png"]  # optional; relative to report dir
    }
  ],
  "charts": [                                 # optional global gallery (besides per-finding)
    {"path": "charts/corr_heatmap.png", "caption": "Correlation heatmap"}
  ],
  "pipeline": [                               # optional; drives the Mermaid diagram
    "Raw CSV", "profile-dataset", "clean-data", "eda", "verify-analysis", "report"
  ],
  "method": "How the analysis was run (tools, env, key decisions).",
  "lineage": [                                # optional data-lineage rows
    {"step": "source", "detail": "Kaggle used-car dump, 1.0M rows"},
    {"step": "clean",  "detail": "clean_used_car.py — dropped 2.1k dups; median-imputed Mileage"}
  ],
  "caveats": [                                # explicit limitations / assumptions
    "Outliers KEPT (high-Price exotics) — not removed.",
    "Causation NOT established; relationships are associational."
  ]
}

Usage:
    python3 build_report.py <spec.json> [-o report.md] [--ipynb report.ipynb]
                            [--strict] [--validated-verdicts supported,confirmed,validated]
"""
import argparse
import json
import os
import sys

DEFAULT_VALIDATED = ("supported", "confirmed", "validated", "pass", "passed")


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def esc(s):
    """Make a string safe inside a Mermaid label."""
    return str(s).replace('"', "'").replace("\n", " ").strip()


def cell(s):
    """Make a string safe inside a Markdown table cell."""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def conf_badge(confidence):
    c = str(confidence or "").strip().lower()
    return {"high": "🟢 high", "medium": "🟡 medium", "low": "🟠 low"}.get(c, confidence or "—")


def pipeline_mermaid(steps):
    """Render the analysis pipeline as a left-to-right Mermaid flowchart."""
    if not steps:
        steps = ["Raw data", "clean-data", "eda", "verify-analysis", "report"]
    out = ["```mermaid", "flowchart LR"]
    ids = []
    for i, s in enumerate(steps):
        nid = f"P{i}"
        ids.append(nid)
        out.append(f'    {nid}["{esc(s)}"]')
    for a, b in zip(ids, ids[1:]):
        out.append(f"    {a} --> {b}")
    out.append("```")
    return out


def build_markdown(d, validated):
    title = d.get("title", "Analysis report")
    dataset = d.get("dataset", "")
    findings = d.get("findings", []) or []

    # Split findings by verdict — the cardinal-rule gate.
    keep, demoted = [], []
    for f in findings:
        v = str(f.get("verdict", "")).strip().lower()
        (keep if v in validated else demoted).append(f)

    L = []
    L.append(f"# {title}\n")
    if dataset:
        L.append(f"_Dataset: `{dataset}` (read-only source — never modified)._\n")

    # 1) Executive summary
    L.append("## 1. Executive summary\n")
    L.append((d.get("executive_summary") or "_(no summary provided)_").strip() + "\n")

    # 2) Key findings — ONLY validated
    L.append("## 2. Key findings (validated only)\n")
    if keep:
        L.append("> Every finding below carries a verdict from `verify-analysis`. "
                 "Unvalidated patterns are intentionally excluded — see Caveats.\n")
        L.append("| # | Finding | Verdict | Confidence | Evidence |")
        L.append("|---|---|---|---|---|")
        for i, f in enumerate(keep, 1):
            L.append(f"| {i} | {cell(f.get('claim', ''))} "
                     f"| ✅ {cell(f.get('verdict', 'validated'))} "
                     f"| {cell(conf_badge(f.get('confidence')))} "
                     f"| {cell(f.get('evidence', ''))} |")
        L.append("")
    else:
        L.append("> ⚠️ No findings passed validation. Nothing is presented as a conclusion. "
                 "See Caveats for what was explored but not confirmed.\n")

    # 3) Supporting charts + pipeline diagram
    L.append("## 3. Supporting charts\n")
    shown_any = False
    for f in keep:
        for c in f.get("charts", []) or []:
            shown_any = True
            L.append(f"**{cell(f.get('claim', 'finding'))}**\n")
            L.append(f"![{esc(f.get('claim', 'chart'))}]({c})\n")
    for c in d.get("charts", []) or []:
        shown_any = True
        path = c.get("path") if isinstance(c, dict) else c
        cap = c.get("caption", "") if isinstance(c, dict) else ""
        L.append(f"![{esc(cap or path)}]({path})")
        if cap:
            L.append(f"*{cell(cap)}*")
        L.append("")
    if not shown_any:
        L.append("_(no chart images supplied)_\n")

    L.append("### Analysis pipeline\n")
    L.extend(pipeline_mermaid(d.get("pipeline")))
    L.append("")

    # 4) Method & data lineage
    L.append("## 4. Method & data lineage\n")
    if d.get("method"):
        L.append(d["method"].strip() + "\n")
    lineage = d.get("lineage", []) or []
    if lineage:
        L.append("| Step | Detail |")
        L.append("|---|---|")
        for row in lineage:
            L.append(f"| {cell(row.get('step', ''))} | {cell(row.get('detail', ''))} |")
        L.append("")

    # 5) Caveats / limitations — incl. demoted (unvalidated) findings
    L.append("## 5. Caveats & limitations\n")
    wrote = False
    for c in d.get("caveats", []) or []:
        L.append(f"- {cell(c)}")
        wrote = True
    if demoted:
        wrote = True
        L.append("- **Explored but NOT validated** (do not treat as conclusions):")
        for f in demoted:
            v = f.get("verdict") or "no verdict"
            L.append(f"    - {cell(f.get('claim', ''))} — _verdict: {cell(v)}_")
    if not wrote:
        L.append("- _(none stated — confirm there really are no limitations before trusting this)_")
    L.append("")

    return "\n".join(L), keep, demoted


def build_ipynb(markdown_text, title):
    """Wrap the report Markdown into a minimal one-cell .ipynb (no execution needed)."""
    try:
        import nbformat as nbf
    except ImportError:
        eprint("ERROR: --ipynb needs nbformat. Run: .venv/bin/pip install nbformat")
        sys.exit(2)
    nb = nbf.v4.new_notebook()
    nb.cells = [nbf.v4.new_markdown_cell(markdown_text)]
    nb.metadata["title"] = title
    return nb


def main():
    ap = argparse.ArgumentParser(description="Assemble a validated analysis report (Markdown / ipynb).")
    ap.add_argument("spec", help="Path to the report spec JSON.")
    ap.add_argument("-o", "--out", default="report.md", help="Output Markdown path.")
    ap.add_argument("--ipynb", default=None, help="Also write a .ipynb at this path (optional).")
    ap.add_argument("--strict", action="store_true",
                    help="Hard-fail if any finding is missing a verdict.")
    ap.add_argument("--validated-verdicts", default=",".join(DEFAULT_VALIDATED),
                    help="Comma list of verdicts that count as validated.")
    a = ap.parse_args()

    if not os.path.exists(a.spec):
        eprint(f"ERROR: spec not found: {a.spec}")
        sys.exit(1)
    try:
        with open(a.spec) as f:
            d = json.load(f)
    except Exception as e:
        eprint(f"ERROR parsing spec JSON: {e}")
        sys.exit(3)

    validated = {v.strip().lower() for v in a.validated_verdicts.split(",") if v.strip()}

    if a.strict:
        missing = [f.get("claim", "?") for f in (d.get("findings") or [])
                   if not str(f.get("verdict", "")).strip()]
        if missing:
            eprint("ERROR (--strict): findings missing a verdict — cannot report:")
            for m in missing:
                eprint(f"  - {m}")
            eprint("Run verify-analysis to assign verdicts, or drop the finding.")
            sys.exit(4)

    md, keep, demoted = build_markdown(d, validated)

    with open(a.out, "w") as f:
        f.write(md)

    if a.ipynb:
        import nbformat as nbf  # noqa: F401  (import error handled in build_ipynb)
        nb = build_ipynb(md, d.get("title", "Analysis report"))
        nbf.write(nb, a.ipynb)

    print(f"Wrote {a.out}  (validated findings: {len(keep)}, demoted to caveats: {len(demoted)})")
    if a.ipynb:
        print(f"Wrote {a.ipynb}")
    if demoted:
        print(f"NOTE: {len(demoted)} unvalidated finding(s) were NOT presented as conclusions "
              f"(moved to Caveats).")


if __name__ == "__main__":
    main()
