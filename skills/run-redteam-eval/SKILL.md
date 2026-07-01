---
name: run-redteam-eval
description: Replay attack chains against a tool-using agent target and compute formal, judge-free agent-security metrics — Benign Utility, Utility-Under-Attack, and (Targeted) Attack Success Rate — using deterministic STATE predicates, never an LLM judge. Replays each chain N times to verify determinism. Ships a built-in naive mock target so it runs end-to-end; point it at the real Kaggle sandbox / AgentDojo target for real findings. Writes redteam_summary.json + a report that leads with "offline ASR ≠ production security". Use after build-attack-chains.
allowed-tools: Bash, Read, Write, Glob
---

# run-redteam-eval

This is the scoreboard for the agent-security pipeline: it replays the predicate-locked chains against the target and reports the standard metrics — **Benign Utility** (does the legit task work with no attack), **Utility-Under-Attack** (does it still work while attacked), and **(Targeted) Attack Success Rate** (how often a chain triggers the declared unsafe action). Crucially it scores with **deterministic state predicates, not an LLM judge** — because a judge can itself be hijacked by the very injection you're testing.

It ships a deliberately naive **mock** target so the whole pipeline runs end-to-end (and the metric math is verifiable); for real findings you wire `--target` to the competition sandbox / AgentDojo via the `target_adapter.py` from `scaffold-attack`.

## When to use
- After `build-attack-chains`, to measure how the chains do against the target.
- To verify your attacks are **deterministic** (replayable) before trusting any ASR number — a competition-integrity requirement.
- To get the before-number that `harden-agent` measures residual ASR against.

## Contract (important)
- **Judge-free metrics.** Success is decided by deterministic state predicates (did the targeted tool call happen? did the benign one still happen?), never by asking an LLM — a judge is itself injectable.
- **Authorized only.** Refuses (exit 4) unless `redteam_task.json` has `authorization_confirmed: true`.
- **Determinism is checked, not assumed.** Each chain is replayed N times (`--replays`); if outcomes vary, status is `FAIL` and the report warns that the ASR is unreliable.
- **Offline ASR ≠ production security — stated first, every report.** These numbers describe a sandboxed target under a known attack set; they do not characterize any production system's real-world robustness, and are necessary-but-not-sufficient for the Kaggle eval.
- **The mock is a demo, not a result.** With `--target mock` the report says so explicitly — replace it with the real target for real findings.
- **Writes a new summary + report.** Edits nothing.

## Steps
1. **Need `redteam_task.json` + `attack_chains.json`.** Run `frame-redteam-task` and `build-attack-chains` first.
2. **Run (smoke-test with the mock, then point at the real target):**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/run-redteam-eval/scripts/run_redteam_eval.py" \
       --task-json redteam_task.json --chains attack_chains.json --target mock [--replays 3]
   # real target: --target <target>_attack/target_adapter.py
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/run-redteam-eval/scripts/run_redteam_eval.py`.)
3. **Read the metrics, lead with the disclaimer + determinism.** If determinism is `FAIL`, the ASR is unreliable — fix the chains/target before trusting it. If using the mock, say the numbers are a harness demo.
4. **Hand off:** `redteam_summary.json` → `harden-agent` (mitigations + residual-ASR re-measurement).

## Output style
- Lead with the offline≠production disclaimer, then the three metrics + determinism status.
- If `--target mock`, label the numbers a harness demo, not a finding.
- Never present ASR as a statement about a production system's security.

## Grounding
The three metrics (Benign Utility, Utility-Under-Attack, Targeted Attack Success Rate) and the judge-free, deterministic-state-predicate scoring are AgentDojo's evaluation design (Debenedetti et al., NeurIPS 2024); the demonstrated reality of the threat is InjecAgent (Zhan et al., ACL Findings 2024 — ReAct GPT-4 attacked 24% of the time on 1,054 indirect-injection cases). Replaying candidates to verify determinism (rather than trusting attacker traces) mirrors the competition's own evaluator. The offline≠production caveat is the same honesty discipline the rest of the plugin enforces — an offline score is not a production measurement.
