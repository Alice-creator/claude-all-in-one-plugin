---
name: report
description: Assemble the FINAL analysis deliverable — a structured `report.md` (optionally an `.ipynb`) from VALIDATED findings (with verdicts from verify-analysis), chart PNGs (from build-chart), and explicit caveats. Composes: executive summary, key findings (validated only, each with confidence/verdict), supporting charts + a Mermaid pipeline diagram, method & data lineage, and caveats/limitations. Use as the LAST step of an analysis to communicate results. Cardinal rule: NEVER presents unvalidated EDA patterns as conclusions.
---

# report

Stitch a finished analysis into one **trustworthy, visual deliverable**. This is a *composition* skill — it does no new analysis; it gathers what earlier steps produced (clean-data summary, **validated** findings, chart images) and arranges them so a reader sees the conclusions, the evidence, and — just as important — the limits.

The mechanical assembly is a deterministic script (`build_report.py`) that takes a JSON spec and writes the Markdown. Your job is the judgment: deciding what's a real finding, attaching the right verdict, and being honest in the caveats.

## Cardinal rule

**Never present an unvalidated EDA pattern as a conclusion.** A correlation you spotted in a chart is a *hypothesis* until `verify-analysis` returns a verdict. In the report:
- A finding goes in **Key findings** only if its verdict is validated (supported / confirmed / validated).
- Anything refuted, inconclusive, or never verified is **demoted to Caveats** — explored, not concluded.
- The script enforces this gate so it can't be skipped by accident; `--strict` makes a missing verdict a hard error.

## When to use
- The **last** step of an analysis: cleaning done, EDA done, findings re-checked by `verify-analysis`, charts rendered by `build-chart`.
- You need a shareable artifact (Markdown or notebook) that a non-analyst can read and trust.

## Steps
1. **Gather inputs** — collect, from this session:
   - the **clean-data** summary (what was cleaned, what was kept) for lineage,
   - the **validated findings** — each must carry a `verdict` from `verify-analysis` and a `confidence`,
   - the **chart PNGs** from `build-chart` (note their paths, relative to where `report.md` will live),
   - the **caveats**: kept outliers, assumptions, what was NOT validated.
2. **Triage the findings (the cardinal-rule step).** For each candidate finding, confirm there's a real verdict. If a pattern was never verified, either send it back to `verify-analysis` or list it as a caveat — do **not** promote it to a conclusion.
3. **Write the spec** — author a `report_spec.json` (schema in the script's header docstring) with: `title`, `dataset`, `executive_summary`, `findings[]` (claim + verdict + confidence + evidence + optional charts), global `charts[]`, the `pipeline` step list (drives the Mermaid diagram), `method`, `lineage[]`, and `caveats[]`.
4. **Render** with the project venv (stdlib-only, but use the venv for consistency):
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/report/scripts/build_report.py" \
     report_spec.json -o report.md
   ```
   - Add `--ipynb report.ipynb` to ALSO emit a notebook (only if asked).
   - Add `--strict` to hard-fail (exit 4) if any finding lacks a verdict — a good safety check before sharing.
   - The script prints how many findings were validated vs. demoted to caveats; read that line.
5. **Review & hand off** — open `report.md`, confirm the Key findings table shows only validated rows, the Mermaid pipeline matches what actually ran, charts resolve, and the Caveats are honest. Point the user at the file.

## Output structure (`report.md`)
1. **Executive summary** — 2–4 plain sentences a busy reader can act on.
2. **Key findings (validated only)** — table: finding · verdict · confidence · evidence.
3. **Supporting charts** — embedded PNG links **plus** a `flowchart LR` Mermaid diagram of the analysis pipeline (visual-first).
4. **Method & data lineage** — how it was run + a source→clean→analysis trail.
5. **Caveats & limitations** — kept outliers, assumptions, and every pattern that did *not* survive validation.

## Notes
- **Composition, not analysis.** If you find yourself computing a new number here, stop — that belongs upstream (eda / verify-analysis), then comes back as a validated finding.
- **Chart paths are relative** to the report file. Keep `report.md` and the chart PNGs in the same output folder so links resolve when shared.
- **Writes a NEW file** (`report.md` / `report.ipynb`); it never edits source data, charts, or upstream logs.
- **Honest caveats are the point.** An empty Caveats section is a red flag — almost every analysis kept outliers, assumed something, or left a thread unverified. Say so.
- Tóm tắt: skill này chỉ *lắp ráp* báo cáo cuối từ kết quả đã được kiểm chứng (validated) — luật vàng là KHÔNG bao giờ trình bày một mẫu hình EDA chưa kiểm chứng như một kết luận; cái chưa verify thì đưa xuống mục Caveats.
