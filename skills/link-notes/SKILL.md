---
name: link-notes
description: Wire your paper notes into a connected knowledge base and keep retention honest — builds a Map-of-Content index.md (Mermaid knowledge graph + tables grouped by topic from [[wikilinks]]) and runs an active-recall scheduler over each note's Recall prompts (spaced repetition). Use as the RETAIN & CONNECT step after digest-paper, and weekly to resurface what's due for review. Notes are plain markdown in git (Foam/Obsidian style).
allowed-tools: Bash, Read, Write, Edit, Glob
---

# link-notes

Make the reading **stick** and **connect**. Two jobs: (1) turn a folder of literature notes into a navigable knowledge graph, and (2) schedule active recall so notes don't rot — because linking notes alone does *not* produce memory; retrieval practice does.

## When to use
- The RETAIN & CONNECT step after `digest-paper` writes a note.
- Weekly, to (a) refresh the `index.md` graph and (b) see which recall prompts are **due**.
- NOT for writing the note content (that's `digest-paper`) — this skill organizes and schedules.

## Contract (important)
- **Never edits your notes.** It only writes `index.md` / `index.json`, `recall.md`, and `recall_log.json`. Your notes are the source of truth.
- **Plain markdown in git.** Notes link via `[[wikilinks]]` (Foam/Obsidian convention) so the graph is portable and survives without any tool.
- **Recall is real spacing, not a vibe.** Each reviewed note advances along an expanding interval (1, 3, 7, 16, 35, 90 days) tracked in `recall_log.json`. A note is "due" if never reviewed or its next-due date has passed. (Honest scope: this is a lightweight scheduler over your own Q→A prompts, not a full Anki/SM-2 engine — but it implements genuine spaced retrieval, which is the part that drives retention.)

## Steps
1. **Connect — add `[[wikilinks]]`.** In each note's `## Links` section, link related notes by their slug or title (e.g. `[[attention-is-all-you-need]]`). Wire a new note to 1–3 prior ones (what it builds on / contradicts / relates to). This is a judgment step — do it as you file the note.
2. **Build the index:**
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/link-notes/scripts/link_notes.py" index \
     --notes-dir research/notes --out research/index.md
   ```
   Writes `index.md` (opens with `## At a glance` + a Mermaid graph of note↔note links, then tables grouped by tag) and `index.json`. (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/link-notes/scripts/link_notes.py`.)
3. **See what's due for recall:**
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/link-notes/scripts/link_notes.py" recall \
     --notes-dir research/notes --out research/recall.md --log research/recall_log.json
   ```
   Writes `recall.md` listing due notes' Q→A (answers hidden in `<details>`). Answer from memory first.
4. **Mark a note reviewed** (advances its interval) after you self-test:
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/link-notes/scripts/link_notes.py" recall \
     --reviewed <note-slug> --log research/recall_log.json
   ```

## Output style
- After `index`, give a one-line state of the graph: how many notes, topics, and links; flag orphan notes (no `[[wikilinks]]` yet) to wire up.
- After `recall`, say how many notes are due and nudge the user to actually answer before revealing — the testing is the point, not the reading.

## Grounding
- **Linked notes / Zettelkasten:** Foam (and Obsidian) store notes as plain markdown linked with `[[wikilinks]]`, forming a navigable knowledge graph — the standard implementation of networked, linked notes.
- **Spaced retrieval practice** beats rereading for long-term retention (Roediger & Karpicke, 2006: ~13% vs ~56% forgotten). The popular claim that *maintaining* linked notes alone approximates spaced repetition does **not** hold up — so this skill adds an explicit due-scheduled self-test, which is the mechanism the evidence actually supports.
