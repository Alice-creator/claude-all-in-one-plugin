---
name: discover-papers
description: Find Q1-journal or high-impact ML/AI papers for a keyword you give — searches OpenAlex (free, no key), keeps papers that are either in a Scimago Q1 journal OR high-impact by citations-per-year, and writes a ranked shortlist (Mermaid-led) + a JSON sidecar. Use as the DISCOVER step when you want the top papers on a topic to triage, e.g. "find me Q1 papers on diffusion models" — then hand a pick to the paper-researcher agent / digest-paper skill.
allowed-tools: Bash, Read, Glob
---

# discover-papers

Turn a keyword into a **shortlist of papers worth your time** — filtered to Q1 journals and/or high citation impact — so the weekly "what should I read?" question takes one command, not an afternoon of scrolling.

## When to use
- You have a topic/keyword and want the **best** papers on it ("Q1 papers on graph neural networks", "high-impact retrieval-augmented generation papers since 2023").
- The DISCOVER stage of the paper-reading habit, before `digest-paper` / the `paper-researcher` agent.
- NOT for finding a specific paper you already know (just open it) and NOT a literature review (this is a triage shortlist, not exhaustive).

## Contract (important)
- **Read-only.** Hits a public API (OpenAlex) and writes only the shortlist + JSON into `--out-dir`. Touches no source data.
- **Honest about "Q1".** Q1/Q2/Q3/Q4 are *journal* rankings (Scimago SJR) — arXiv preprints have **no** quartile. True-Q1 labelling needs a Scimago table you supply (see below); without it the skill ranks by **impact only** and says so in the report. Never claim a quartile it didn't actually look up.
- **A shortlist is triage, not judgment.** OpenAlex ranks by text relevance; citation counts **lag** for recent papers (a great 2026 paper may show 0 citations). State this; don't present the ranking as "the best science."

## Getting a Scimago table (one-time, optional but recommended for true Q1)
Scimago blocks scripted downloads, so download it by hand once: open <https://www.scimagojr.com/journalrank.php>, (optionally pick a subject category), click **Download data** → save the CSV. Pass it via `--scimago /path/scimagojr.csv` (or set `SCIMAGO_CSV`). The CSV is semicolon-delimited with `Title`, `Issn`, `SJR Best Quartile` columns — the script matches your results' ISSN/journal against it.

## Steps
1. **Ensure a Python** (stdlib only — no pip needed, but use the venv for consistency):
   ```bash
   [ -x .venv/bin/python ] || python3 -m venv .venv
   ```
2. **Run the search:**
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/discover-papers/scripts/discover.py" \
     "<your keyword>" --from-year 2023 --min-cites-per-year 5 \
     [--scimago /path/scimagojr.csv] [--require either|q1|impact] \
     --mailto "<your-email>" --out-dir research/candidates
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/discover-papers/scripts/discover.py`.)
   - `--require either` (default) keeps Q1 **OR** high-impact; `q1` / `impact` restrict to one.
   - `--min-cites-per-year` is the impact floor (citations ÷ years-since-publication). Lower it for niche/very recent topics that return nothing.
   - Exit 3 = no candidates passed the filter — loosen the floor, drop `--from-year`, or widen `--require`.
3. **Read the shortlist, don't dump it.** Open the generated `.md`, give a one-line read of the field (how many Q1 vs impact, what the top 2–3 are about), and recommend 1 to digest next.
4. **Hand off:** pass the chosen paper's **DOI or OpenAlex id** (in the JSON sidecar) to the `paper-researcher` agent or `digest-paper` skill.

## Output style
- Lead with the count and the standout: *"12 candidates (5 Q1, 7 high-impact); the Theodoris 2023 Nature paper on transfer learning in network biology is the obvious first read."*
- Always state whether quartiles are **real** (Scimago table used) or **unknown** (impact-only).
- Surface the honest caveat about citation lag for recent work.

## Grounding
- **OpenAlex** is a free, keyless scholarly API returning works with venue, ISSN, citation counts, and abstracts (`https://api.openalex.org`); usage is metered by a daily cost budget, generous for interactive use. It is the primary source here because one call yields everything the filter needs.
- **Scimago Journal Rank (SJR)** quartiles are the standard "Q1 journal" definition (top 25% of journals in a subject category by SJR); the downloadable Scimago table is the citable source for the labels.
- **High-impact ≠ Q1:** citations-per-year surfaces strong recent preprints/papers that have no journal quartile yet — which is why the default keeps the union, per the user's "Q1 OR high-impact" intent.
