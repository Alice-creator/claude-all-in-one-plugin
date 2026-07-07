---
name: baseline-agent
description: Establish the "number to beat" for a game agent — measure a scripted/heuristic policy against a simple opponent (random) over N episodes, with a crash/timeout/illegal HEALTH gate, and emit a recommendation (scripted-sufficient vs iterate vs consider-RL). The agent analog of the `baseline` skill: a strong scripted floor before any RL, because scripted bots often beat RL under competition time limits. Writes baseline_agent_metric.json + a Mermaid-led report. Use after scaffold-submission, before self-play-eval and before any RL.
allowed-tools: Bash, Read, Write, Glob
---

# baseline-agent

Answer the question that saves agent projects: **"is a scripted policy already good enough?"** Before anyone trains an RL agent, you need two facts about a heuristic bot — does it **win** more than it loses against a trivial opponent, and is it **healthy** (no crashes, no timeouts, no illegal moves)? Research is blunt here: even the first deep-RL agent to win a major RTS competition was *beaten* by hand-written scripted bots when compute was unconstrained — RL only won under the time limit. So a strong scripted baseline is both the right first move and the bar RL must clear.

This skill measures whatever policy is in your agent file (the one `scaffold-submission` generated, after you fill the `=== YOUR POLICY ===` block with a heuristic) and gates the pipeline on its health.

## When to use
- After `scaffold-submission`, once you've written a heuristic into the agent's policy block (or to measure the random-legal floor itself).
- Before any RL — get the scripted number so "better" has a reference.
- To verify the agent is **healthy** (zero crashes/timeouts/illegal moves) before spending episodes on a self-play ladder.

## Contract (important)
- **Runs real episodes; writes a metric + report.** Needs `kaggle_environments` (exit 2 if missing). Never edits the agent or source.
- **Health is a gate, not a footnote.** If the agent crashes, times out, or plays an illegal move even once, status is `FAIL` — fix the legal-fallback/policy before `self-play-eval`. A forfeiting agent bleeds rating on the ladder. (Forfeited episodes also count as **losses** in the win rate, so a broken agent can't hide behind the games it didn't forfeit.)
- **The win rate is local and vs a simple opponent.** It is **not** a Kaggle standing (the live ladder has a far larger, shifting opponent pool). Never present it as predictive of leaderboard position.
- **The recommendation is a hypothesis.** `scripted_sufficient` / `iterate_heuristic_or_search` / `weak_vs_random_fix_first` (or `fix_health_first` when health FAILs — a forfeiting agent can't be rated on strategy) point at a next direction; only a Kaggle submission validates any of them.

## Steps
1. **Need a scaffold first.** If there's no agent bundle, run `scaffold-submission`. Write a heuristic into its `=== YOUR POLICY ===` block (or measure the random-legal floor as a sanity check).
2. **Ensure deps & run:**
   ```bash
   python3 -c "import kaggle_environments" 2>/dev/null || pip install kaggle-environments
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/baseline-agent/scripts/baseline_agent.py" \
       --task-json agent_task.json [--agent <env>_submission/main.py] [--opponent random] [--episodes 50] [--seed 42]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/baseline-agent/scripts/baseline_agent.py`.)
3. **Read the verdict, lead with health.** If `FAIL`, STOP — report the crash/timeout counts and fix the agent before anything else. If `PASS`, report the win rate and the recommendation.
4. **Hand off:** the agent + `baseline_agent_metric.json` → `self-play-eval` (rate it on a local ladder vs multiple opponents).

## Output style
- Lead with health, then the number: e.g. *"Health PASS (0 crashes); heuristic wins 0.62 vs random over 50 episodes — `iterate_heuristic_or_search`."*
- Always restate that the win rate is local/vs-simple and not a ladder standing.
- If health is FAIL, the win rate is moot — say so and point at the fix.

## Grounding
The "strong simple baseline before complexity" discipline is Google Rules of ML #4 and Andrew Ng's *Machine Learning Yearning* (build a basic system first), adapted from tabular models to agents. The specific "scripted beats RL under time limits" evidence is RAISocketAI (IEEE CoG 2024), the first deep-RL agent to win the IEEE microRTS competition — which still lost to scripted bots (2L, Mayari) when compute was unconstrained. The health gate reflects how `kaggle_environments` scores agents: crashes/illegal/late actions are marked `INVALID`/`ERROR`/`TIMEOUT` and forfeit the episode.
