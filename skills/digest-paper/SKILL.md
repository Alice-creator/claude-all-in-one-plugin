---
name: digest-paper
description: Read ONE paper deeply (Keshav's three-pass method) and produce a structured literature note — core claim, method, results, limitations, relevance to your work — plus a self-contained HTML visual of the paper's mechanism (for visual learners) and active-recall prompts. Scaffolds the note from a template with bibliographic fields pre-filled; YOU/the agent fill the comprehension. Use as the DIGEST step after discover-papers, on a chosen DOI/arXiv/OpenAlex id.
allowed-tools: Bash, Read, Write, Edit, WebFetch, Glob
---

# digest-paper

Turn one chosen paper into a **durable, visual literature note** — not a passive highlight dump. The skill does the mechanical fetch/scaffold; the comprehension (summary, method, critique) is done by *reading*, because writing it from understanding is what builds retention.

## When to use
- The DIGEST step, right after `discover-papers` hands you a paper to read (or any time you have a specific paper).
- When you want a consistent, searchable note + a visual mechanism explainer rather than ad-hoc scribbles.
- NOT for surface triage of many papers (that's `discover-papers`) and NOT for filing/linking (that's `link-notes`).

## Contract (important)
- **Reading is the point.** The script pre-fills only *objective* fields (title, authors, venue, links, abstract). The comprehension fields (Paper summary, Methodology, Limitations, Relation to own work, Recall prompts) are left as prompts to fill from actually reading — auto-summarizing the whole thing defeats the retention purpose. (Hybrid by design: machine does metadata, you/the agent do understanding.)
- **Never invent results or numbers.** Quote metrics/claims from the paper; if a field can't be filled from what you read, say "unclear — revisit" rather than guess. Be skeptical: state limitations and that offline results ≠ deployed performance.
- **HTML is self-contained.** The mechanism explainer must open from disk — inline CSS only, no external scripts/fonts/CDNs/images.
- **Never overwrites** an existing note (the script appends `-2`, `-3`).

## Steps
1. **Scaffold the note + HTML** from the paper id:
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/digest-paper/scripts/fetch_paper.py" \
     "<DOI | arxiv:NNNN.NNNNN | OpenAlex Wxxxx>" [--quartile Q1] [--tags topic1,topic2] \
     --out-dir research/notes --mailto "<your-email>"
   ```
   (Or `--title "..."` to resolve by title. If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/digest-paper/scripts/fetch_paper.py`.) It prints the metadata JSON and writes `<slug>.md` + `<slug>-mechanism.html`.
2. **Read with the three-pass method.** Pass 1 (5–10 min): title, abstract, intro, section headings, conclusions, glance references → fill the **five Cs** (Category, Context, Correctness, Contributions, Clarity) and the TL;DR. Pass 2: grasp the content → fill Paper summary, Issues, Results. Pass 3 (only if you need depth/will build on it): the methodology, assumptions, formulas. (Use WebFetch on the PDF/landing page if the abstract isn't enough.)
3. **Fill the literature note** (`research/notes/<slug>.md`) in your own words — especially **Relation to own work** (would you use this? where? what to try first?) and the **Recall prompts** (3–5 Q→A pairs you can self-test on later).
4. **Author the mechanism HTML** (`<slug>-mechanism.html`): replace each `{{TOKEN}}` / `<!-- EDIT -->` with this paper's specifics — turn the method into an ordered left-to-right **pipeline** of 3–7 stages (input → transform → core mechanism → output), the 1–3 key equations (explain every symbol), and the intuition/where-it-breaks panels. Keep it a *mechanism* picture, not a results table.
5. **Hand off to `link-notes`** to wire `[[wikilinks]]` to related notes and register the recall prompts.

## Output style
- After scaffolding, tell the user the two file paths and open with the **five Cs** read so they know what they're getting into before the deep read.
- The note's voice is yours/the reader's — concise, skeptical, practitioner-focused ("here's what I'd actually use").
- The HTML is for a visual learner: clear stages, minimal text per box, the equation that carries the idea.

## Grounding
- **Three-pass method + five Cs:** Keshav, *How to Read a Paper* (ACM SIGCOMM CCR, 2007) — pass 1 is a 5–10 min skim answering Category/Context/Correctness/Contributions/Clarity; later passes add content then depth.
- **Note fields:** adapted from the KaleabTessera *Research-Paper-Reading-Template* (Quick Look → Paper summary/What → Issues/Why → Detailed Information/How: Problem Setting, Methodology, Assumptions, Formulas, Results, Limitations → Relation to Own Work), which maps onto exactly the fields requested.
- **Recall prompts exist because linked notes ≠ retention.** Retrieval practice (self-testing) drives long-term memory far more than rereading (Roediger & Karpicke, 2006) — so the note ends with explicit Q→A recall items, not just backlinks.
