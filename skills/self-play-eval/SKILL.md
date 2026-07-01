---
name: self-play-eval
description: Stand up a LOCAL self-play ladder — run a pool of agents (your bot, prior versions, baselines, builtins) against each other over many matches and produce ELO (stdlib) or TrueSkill (optional) ratings, a win matrix, and a per-agent invalid-move rate. Lets you compare your own variants and iterate offline BEFORE spending scarce daily Kaggle submissions. Writes ladder_summary.json + a Mermaid-led report that leads with the offline≠Kaggle caveat. Use after baseline-agent (health PASS), to pick which variant to submit.
allowed-tools: Bash, Read, Write, Glob
---

# self-play-eval

Kaggle agent comps cap your submissions (often ~5/day), and the live ladder is the only true scoreboard — so you don't want to burn submissions discovering that v3 is worse than v2. This skill builds a **local ladder**: it plays your pool of agents against each other many times, rates them (ELO by default, TrueSkill if installed), and shows a win matrix and each agent's invalid-move rate. It's how you decide *which* variant is worth a submission.

It mirrors Kaggle's scoring *mechanism* (head-to-head, skill rating) but **not** its opponent pool — so the rating compares *your* variants, and is explicitly **not** a leaderboard prediction.

## When to use
- After `baseline-agent` reports health `PASS` — to rate your bot against baselines and prior versions.
- Whenever you have 2+ candidate agents and need to pick which to submit.
- To catch regressions (a "smarter" change that actually lowers win rate) before they cost a submission.

## Contract (important)
- **Runs real episodes; writes a summary + report.** Needs `kaggle_environments` (exit 2 if missing). Never edits agents or source.
- **Offline ≠ Kaggle — stated first, every time.** The rating is vs *your* pool only. The Kaggle ladder is far larger and shifts daily. Lead the report with this; never present the local rating as a leaderboard standing.
- **Compares variants, doesn't crown a winner.** A higher local rating means it beats *the rest of your pool* more — informative for picking a submission, not proof it ranks well online.
- **Tracks invalid-move rate.** Any agent with a non-zero rate made illegal/late moves or crashed — surface it; that bleeds rating on Kaggle too.
- **Reproducible.** Lineups are drawn from a seeded RNG (`--seed`).

## Steps
1. **Need a healthy agent + a pool.** Run `baseline-agent` first; gather a pool: your bot, prior versions, the random-legal floor, and any builtin opponents (e.g. `random`).
2. **Ensure deps & run:**
   ```bash
   python3 -c "import kaggle_environments" 2>/dev/null || pip install kaggle-environments
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/self-play-eval/scripts/self_play_eval.py" \
       --task-json agent_task.json --agents <env>_submission/main.py prior_v1.py random \
       [--matches 60] [--method elo|trueskill] [--seed 42]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/self-play-eval/scripts/self_play_eval.py`.) For n-player envs, lineups are sampled from the pool; for 2-player envs it's a full round-robin.
3. **Read the ladder, lead with the caveat.** Report the ranking and which of *your* variants is on top, then flag any non-zero invalid rate.
4. **Hand off:** `ladder_summary.json` → `profile-agent` (where the top agent wins/loses and what to try next).

## Output style
- Lead with the offline≠Kaggle caveat, then the ranking: e.g. *"(local pool only) v2 tops the ladder at ELO 1612 > v1 1498 > random 1390; v2 invalid rate 0 — submit v2."*
- Surface invalid rates explicitly; a "strong" agent that occasionally crashes is not submit-ready.
- Never translate a local rating into a Kaggle rank or percentile.

## Grounding
The head-to-head skill-rating mechanism mirrors how Kaggle scores simulation competitions (continuous episodes, TrueSkill/Gaussian ratings — wins raise, losses lower, only your best bot shows), per Kaggle's [simulation-competitions docs](https://github.com/Kaggle/kaggle-cli/blob/main/docs/simulation_competitions.md). ELO is the Elo (1978) rating system; TrueSkill is Herbrich, Minka & Graepel (NeurIPS 2006), a Bayesian generalization used for multiplayer. Self-play against prior versions as an evaluation/training pattern follows AlphaZero-style league play and the PettingZoo self-play tutorials. The offline≠online caveat is the same discipline the modeling pipeline enforces: a local score is not a measurement of the real, larger, shifting competition.
