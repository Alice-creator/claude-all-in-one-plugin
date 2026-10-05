---
name: frame-competition
description: Turn a new AI competition (Kaggle, DrivenData, AIcrowd, Zindi, CodaLab, Hugging Face, or any other platform) into a filled competition.json fact sheet and a one-page brief BEFORE any modeling — platform, track, metric and its direction, deadlines, rules (external data, pretrained models, team size), submission mechanics (daily limit, final-selection count, code-competition runtime/internet limits, format file), public-leaderboard fraction, and a validation scheme that mirrors how the test set was split. Unknowns stay null and are listed as open questions, never assumed. Routes to the right pipeline (tabular → model-builder, game/agent → game-agent-builder, object detection → cv-modeler). Use when starting a new competition, when competition.json is missing or incomplete, or when the rules change mid-competition.
allowed-tools: Bash, Read, Write, Edit, WebFetch
---

# frame-competition

Stage 0 of every competition. Most lost competitions are lost before the first model: external data that turns out to be banned, a validation split that does not resemble the test split, a notebook that needs internet in an offline code competition, a deadline that was a week earlier than assumed. This skill pins those facts down from the platform's own pages and stops the work until they are known.

## When to use
- Right after copying the competition template into a new folder.
- When `competition.json` is missing, has `null` in a required field, or `competition_check.json` says `INCOMPLETE`.
- When the organizers update the rules, the data or the deadline.

## Contract (important)
- **The platform's pages are the only authority.** Fill fields from the rules, overview, data and evaluation pages (fetched or pasted by the user). Never fill a field from memory of a similar competition.
- **Unknown = `null`, never a guess.** A `null` is reported as an open question. `rules.external_data_allowed: null` means "ask", not "allowed".
- **Required before modeling:** name, platform, track, metric name + direction, final-submission deadline, `rules.rules_accepted: true`, and a validation scheme. `check_competition.py` exits 1 until they are set.
- **The validation scheme must say why it mirrors the test split** (`validation.mirrors_test_because`): time-based test → time-based CV; test grouped by user/site/patient → group CV; random test → stratified K-fold.
- **Never modifies data.** Writes only `competition.json`, `competition_brief.md` and the `competition_check.json` sidecar.
- **Does not submit, accept rules or join teams on the user's behalf.** Those actions are the user's.

## Steps
1. **Collect the sources.** Ask for the competition URL. Fetch the overview, evaluation, data and rules pages when reachable; when a page needs login, ask the user to paste it.
2. **Fill `competition.json`** in the competition folder (the template ships one with every field `null`). Copy values exactly: the metric's exact name, the deadline in `YYYY-MM-DD` with its timezone, the format file's path under `data/raw/`.
3. **Pick the track:** `tabular`, `game-agent`, `cv-detection`, or `other` (other = no pipeline here yet; say so plainly).
4. **Design the validation scheme** from how the test set was built (the data page usually says). Write the scheme and the reason. If the page does not say, mark `mirrors_test_because: null` and list it as the first open question.
5. **Run the check:**
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_competition.py" --competition competition.json
   ```
   Exit 0 = `READY`, 1 = required fields missing or invalid, 3 = unreadable JSON.
6. **Write `competition_brief.md`** and hand off to the pipeline the check printed (`model-builder`, `game-agent-builder`, `cv-modeler`). Stop at this checkpoint: the user confirms the brief before any modeling.

## Output style
- `competition_brief.md` opens with `## At a glance` + a Mermaid flowchart: data → validation scheme → metric (direction) → submission format → deadline (days left).
- Then three short sections: **Facts** (from the platform), **Open questions** (every `null`, with why it matters), **Plan** (pipeline + first experiment = the baseline).
- Flag under 7 days to the deadline at the top.

## Grounding
- The public leaderboard is scored on a subset of the test data and the private leaderboard on the rest; final standing is the private one (Kaggle competition docs, https://www.kaggle.com/docs/competitions). That is why the local validation scheme, not the public score, is the primary signal.
- Each competition defines its own rules page (eligibility, external data, team size, submission limits) and those rules override any general habit; the same holds on DrivenData, AIcrowd and Zindi, whose rules are per-competition.
- Code competitions run the submitted notebook on hidden test data under platform-set runtime and internet limits (Kaggle code-competition docs, same page), so those fields are recorded up front.
