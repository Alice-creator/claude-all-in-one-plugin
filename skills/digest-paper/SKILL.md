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
1. **Classify the paper type, then scaffold** — the type decides the visual archetype (see step 4). Pass it via `--type`:
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/digest-paper/scripts/fetch_paper.py" \
     "<DOI | arxiv:NNNN.NNNNN | OpenAlex Wxxxx>" --type method|survey|benchmark|analysis \
     [--quartile Q1] [--tags topic1,topic2] --out-dir research/notes --mailto "<your-email>"
   ```
   (Or `--title "..."` to resolve by title. If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/digest-paper/scripts/fetch_paper.py`.) It prints the metadata JSON and writes `<slug>.md` + `<slug>-mechanism.html`. **`--type survey` uses the taxonomy/landscape template; the others use the mechanism/pipeline template** — picking the wrong one (e.g. method for a survey) collapses a whole field into one diagram, so classify honestly first.
2. **Read with the three-pass method.** Pass 1 (5–10 min): title, abstract, intro, section headings, conclusions, glance references → fill the **five Cs** (Category, Context, Correctness, Contributions, Clarity) and the TL;DR. Pass 2: grasp the content → fill Paper summary, Issues, Results. Pass 3 (only if you need depth/will build on it): the methodology, assumptions, formulas. (Use WebFetch on the PDF/landing page if the abstract isn't enough.)
3. **Fill the literature note** (`research/notes/<slug>.md`) in your own words — especially **Relation to own work** (would you use this? where? what to try first?) and the **Recall prompts** (3–5 Q→A pairs you can self-test on later).
4. **Author the visual** (`<slug>-mechanism.html`) — and **match the archetype to the paper type**, because the right picture differs:
   - **method / empirical → a pipeline/architecture diagram** (`mechanism.html`): grouped boxes (offline/training vs inference, encoder/decoder, modules, stores), labelled arrows (`marker-start`+`marker-end` for bidirectional; a down-and-back path for a feedback loop), numbered badges → legend, the key equation, and intuition/where-it-breaks panels.
   - **survey → a taxonomy/landscape MAP** (`landscape.html`): the survey's contribution is the *map of the field*, so compare the **approaches/paradigms** it organizes (one card each, mini-flow showing what each adds) and catalog the **technique families** it covers (columns of chips) + how the field is evaluated. **Do NOT draw one pipeline for a survey** — that throws away the point.
   - **benchmark → tasks × metrics / what's measured;** **analysis → claim → evidence → caveat.** Adapt the mechanism template's boxes accordingly.
   The test: *reading the visual should teach what the paper actually contributes.* Keep any `<svg>` well-formed XML (close every tag, escape `&` as `&amp;`), everything inside the viewBox, and the file self-contained (inline CSS+SVG, no external resources).
5. **Hand off to `link-notes`** to wire `[[wikilinks]]` to related notes and register the recall prompts.

## Output style
- After scaffolding, tell the user the two file paths and open with the **five Cs** read so they know what they're getting into before the deep read.
- The note's voice is yours/the reader's — concise, skeptical, practitioner-focused ("here's what I'd actually use").
- The HTML is for a visual learner: a labelled architecture diagram (grouped boxes + arrows + numbered legend) that conveys the mechanism at a glance, the equation that carries the idea, and minimal text per box.

## Grounding
- **Three-pass method + five Cs:** Keshav, *How to Read a Paper* (ACM SIGCOMM CCR, 2007) — pass 1 is a 5–10 min skim answering Category/Context/Correctness/Contributions/Clarity; later passes add content then depth.
- **Note fields:** adapted from the KaleabTessera *Research-Paper-Reading-Template* (Quick Look → Paper summary/What → Issues/Why → Detailed Information/How: Problem Setting, Methodology, Assumptions, Formulas, Results, Limitations → Relation to Own Work), which maps onto exactly the fields requested.
- **Recall prompts exist because linked notes ≠ retention.** Retrieval practice (self-testing) drives long-term memory far more than rereading (Roediger & Karpicke, 2006) — so the note ends with explicit Q→A recall items, not just backlinks.
