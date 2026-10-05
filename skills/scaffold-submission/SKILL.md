---
name: scaffold-submission
description: Generate a ready-to-submit Kaggle simulation-competition bundle from agent_task.json — a main.py exposing agent(obs, config), wrapped in a never-crash legal-fallback and a best-effort cumulative time guard, packaged as submission.tar.gz with a machine-readable submission_manifest.json, and smoke-tested locally if kaggle_environments is installed. Bakes in the exact guardrails these comps enforce (no crash, legal action, time budget). Use right after frame-agent-task, before writing any real policy — it produces the immediately-submittable "does it run" floor.
allowed-tools: Bash, Read, Write, Glob
---

# scaffold-submission

The fastest way to lose rating on a Kaggle agent ladder is a bundle that **crashes, returns an illegal move, or busts the time budget** — before strategy even matters. This skill generates the submission scaffold that eliminates crashes and packaging errors by construction, and *catches* illegal-move failures with a multi-episode smoke test: a `main.py` with the right `agent(obs, config)` interface, a try/except that falls back to a legal move **when the observation exposes the legal set**, a best-effort **cumulative** time guard, and `submission.tar.gz` with `main.py` at the archive root.

It scaffolds the **interface and safety wrapper, not the strategy** — the default policy is random-legal, an immediately-submittable floor. You drop your heuristic in next (`baseline-agent`).

## When to use
- Right after `frame-agent-task` (it reads that stage's `agent_task.json`).
- To get a bundle that **provably runs (never crashes)** and is checked for illegal moves across a multi-episode smoke test, before investing in a policy.
- When you want the packaging (`submission.tar.gz`, `main.py` at root) handled correctly so a submission isn't rejected on format.

## Contract (important)
- **Reads `agent_task.json`; writes a new bundle dir.** Never edits competition files or source.
- **Never-crash always; legal-only when the obs exposes legality.** The generated `agent()` wraps the policy in try/except and validates the action against the observation's legal set *when it can find one* (via `legal_move_field`, a common key, or an `action_mask`); on failure it falls back to a legal move (a losing position beats a crash). **If the env encodes legality implicitly** (e.g. ConnectX: a column is legal iff `board[c]==0`), the wrapper can't see it and the fallback may be illegal — you must derive the legal set in `_legal_actions`/your policy. The multi-episode smoke test flags exactly this; **don't submit on a red smoke test.**
- **Time guard is best-effort, the env is the real enforcer.** It tracks the *cumulative* budget (the model + budget + overage come from `agent_task.json`, e.g. episode-level `runTimeout`, not a naive per-move alarm). Don't present it as a guarantee.
- **Runs out of the box only for index-style action spaces.** For structured-action envs (Orbit Wars `[from_planet, angle, num_ships]`, deck-of-60 selection), the generated `main.py` has a clearly marked `TODO` block — say so, don't pretend it plays meaningfully unfilled.
- **Refuses custom runtimes.** If `agent_task.json` says `runtime: "custom"`, it refuses (exit 4) and points at the competition's own starter code — this scaffold targets `kaggle_environments`.

## Steps
1. **Need `agent_task.json` first.** If it's missing, run `frame-agent-task`.
2. **Ensure deps (optional but recommended) & run:**
   ```bash
   python3 -c "import kaggle_environments" 2>/dev/null || pip install kaggle-environments
   python3 "${CLAUDE_SKILL_DIR}/scripts/scaffold_submission.py" \
       --task-json agent_task.json [--out-dir <env>_submission] [--policy random_legal|first_legal]
   ```
   `kaggle_environments` is only needed for the local smoke test — the bundle still generates without it.
3. **Read the smoke-test result, don't just dump it.** If installed + env id known, the script runs several episodes of `[main.py, "random"]` and reports the illegal/timeout rate. A clean run is a strong check (not a proof); **any illegal move means the fallback can't see this env's legality — fix it before going further** (don't submit on a red smoke test). Tune coverage with `--smoke-episodes`.
4. **Point out the two TODOs that matter:** the `=== YOUR POLICY ===` block (random-legal until you fill it) and, for structured-action envs, the action-construction `TODO`.
5. **Hand off:** the bundle → `baseline-agent` (drop in a heuristic + measure it with a crash/timeout health check).

## Output style
- Lead with whether the bundle **runs**: e.g. *"Bundle generated; smoke test ✅ 10 episodes vs random, all legal. Default policy is random-legal — replace it."* If the smoke test flags illegal moves, lead with THAT — the env encodes legality implicitly and the bundle isn't submittable yet.
- Give the bundle path and that `main.py` is at the archive root (so the format is correct).
- Always restate: the fallback is legal but suboptimal; the time guard is best-effort; **test on the competition's own harness before trusting it.**

## Grounding
The interface (`agent(obs, config)`, also `agent(obs)`) and packaging (`main.py` at the root of `submission.tar.gz`) are from Kaggle's [simulation-competitions docs](https://github.com/Kaggle/kaggle-cli/blob/main/docs/simulation_competitions.md) and the [`kaggle_environments`](https://github.com/Kaggle/kaggle-environments) source. The never-crash / legal-fallback / cumulative-time-budget guardrails are the failure modes those envs penalize (illegal/late actions are marked `INVALID`); the timeout model (episode-level `runTimeout` vs per-move, plus an overage buffer) is read per-competition from `agent_task.json` rather than assumed.
