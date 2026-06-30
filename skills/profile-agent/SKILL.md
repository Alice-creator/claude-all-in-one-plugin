---
name: profile-agent
description: Profile a game agent from the self-play ladder — where it wins/loses per opponent (matchup win shares), how clean it is (invalid-move rate), and the recommended next direction (fix legality / iterate heuristic / add search / consider RL) as HYPOTHESES, not guarantees. The agent analog of evaluate-model's slice-based error analysis. Read-only; consumes ladder_summary.json (+ optional baseline_agent_metric.json). Writes agent_profile.json + a Mermaid-led report. Use after self-play-eval to decide what to change before the next submission.
allowed-tools: Bash, Read, Write, Glob
---

# profile-agent

A ladder rating tells you *whether* an agent is better; it doesn't tell you *where* it's weak or *what to do next*. This skill reads the self-play ladder and does the error analysis: which opponents your agent loses to, whether it ever plays illegal/late moves, and a prioritized list of next directions — each stated honestly as a **hypothesis** to test with a submission, not a guaranteed win.

It's the agent counterpart of `evaluate-model`'s slice analysis: find the worst slices (here, worst matchups), surface what offline eval can't tell you, and point at the highest-leverage next change.

## When to use
- After `self-play-eval`, to decide what to improve before spending the next submission.
- When a "smarter" change didn't raise the rating and you need to see *where* it regressed.
- To catch an agent that rates well overall but quietly makes illegal moves against one opponent.

## Contract (important)
- **Read-only analysis.** Consumes `ladder_summary.json` (+ optional `baseline_agent_metric.json`); writes a profile + report. Runs no episodes, edits nothing.
- **Recommendations are hypotheses.** It points at a next direction (fix legality, iterate heuristic, add search, consider RL); only a Kaggle submission validates any of them. It says so.
- **It does not train RL.** If the data suggests RL, it points at frameworks (SB3/CleanRL, PettingZoo self-play) and the cost — it does not (and a plugin cannot) run the training.
- **Offline ≠ Kaggle.** Carries the ladder's caveat forward — the matchup shares are vs your local pool, not the live ladder.
- **Legality first.** A non-zero invalid-move rate is the top recommendation regardless of rating — an agent that crashes/plays illegally bleeds rating online.

## Steps
1. **Need a ladder first.** Run `self-play-eval` to produce `ladder_summary.json`.
2. **Run:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/profile-agent/scripts/profile_agent.py" \
       --ladder ladder_summary.json [--metric <env>_submission/baseline_agent_metric.json] [--focus <agent name>]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/profile-agent/scripts/profile_agent.py`.) Default focus is the top-rated agent.
3. **Read the profile.** Lead with legality (any invalid rate?), then the weakest matchup, then the prioritized next-step hypotheses.
4. **Loop:** apply one change → `self-play-eval` again → confirm the rating moved the right way. The `game-agent-builder` conductor gates the final submission on a clean run.

## Output style
- Lead with the most actionable finding: e.g. *"v2 is clean (invalid 0) but loses to v1 (win share 0.38) — study those games; next hypothesis: add a counter-heuristic, not RL yet."*
- Frame every recommendation as a hypothesis to test with a submission.
- Restate that matchup shares are local (your pool), not Kaggle.

## Grounding
Slice/worst-group error analysis is standard model-evaluation practice (Andrew Ng, *Machine Learning Yearning*, error analysis), applied here per-opponent. The "scripted before RL, and weigh RL's cost" stance is grounded in RAISocketAI (IEEE CoG 2024). The framework pointers (Stable-Baselines3, CleanRL, PettingZoo self-play/curriculum tutorials) are the standard practice tooling for the RL path the plugin intentionally does **not** execute itself — honest about what it scaffolds vs. what needs real training compute.
