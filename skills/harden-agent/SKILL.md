---
name: harden-agent
description: Defensive counterpart to the red-team — read which attack chains succeeded (redteam_summary.json), recommend mitigations mapped to the standard intervention stages (text-level / model-level / execution-level), and optionally emit a defended target wrapper (an execution-level tool-call allowlist) so you can re-run run-redteam-eval and measure RESIDUAL Attack Success Rate on the SAME target + SAME chains. Writes hardening_summary.json + a report. Use after run-redteam-eval, to close the find→fix loop.
allowed-tools: Bash, Read, Write, Glob
---

# harden-agent

Red-teaming finds the holes; this skill closes them. From the eval results it recommends concrete mitigations — organized by *where* they intervene: **text-level** (delimit/sanitize untrusted tool output), **model-level** (instruction hierarchy), and **execution-level** (tool-call allowlist, least privilege, human-in-the-loop) — and can emit a **defended target wrapper** so you re-run `run-redteam-eval` and see the residual ASR drop (or not). Find → fix → re-measure, in one loop.

It's the posture that keeps this pipeline defensible: the offensive skills exist to surface failures so they can be fixed, and `harden-agent` is where the fixing happens.

## When to use
- After `run-redteam-eval`, when one or more chains succeeded (or to harden proactively).
- To measure whether a mitigation actually reduces ASR against the tested attacks.

## Contract (important)
- **Recommends + optionally re-measures; never overclaims.** Mitigations raise the bar for the **tested** attacks only — not immunity from novel attacks. The report says so.
- **Same target + same chains.** Re-evaluation uses the identical chains and target; it does NOT claim the hardening generalizes to other attacks or to production.
- **Offline ASR ≠ production security.** Carried forward from the eval; a residual ASR of 0 here is not "secure in production."
- **The emitted defense is a demo.** `--emit-defense` writes a `defended_target.py` execution-level allowlist to close the loop — a demonstration mitigation, not a production-grade defense.
- **Writes new files.** `hardening_summary.json`, a report, and optionally `defended_target.py`; edits nothing.

## Steps
1. **Need `redteam_summary.json`** from `run-redteam-eval`.
2. **Run:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/harden-agent/scripts/harden_agent.py" \
       --summary redteam_summary.json --task-json redteam_task.json [--emit-defense]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/harden-agent/scripts/harden_agent.py`.)
3. **If you emitted a defense, re-measure:** run `run-redteam-eval --target defended_target.py` on the SAME chains and compare residual Targeted ASR to the baseline.
4. **Decide:** the choice to adopt a mitigation is the human's.

## Output style
- Lead with the baseline ASR and which chains succeeded, then the stage-mapped mitigations (execution-level first — it's strongest against multi-step tool attacks).
- If re-measured, report residual ASR as "against these chains on this target," never as general security.

## Grounding
The three-stage mitigation taxonomy (text-level / model-level / execution-level interventions) reflects the prompt-injection defense literature surveyed alongside AgentDojo (Debenedetti et al., NeurIPS 2024), which itself evaluates defenses, not just attacks. Execution-level controls (tool-call allowlists, least privilege, human-in-the-loop for high-impact actions) are the standard, strongest mitigations against multi-step tool attacks because they act at the action rather than the text. The "raises the bar, not immunity; re-eval is same-target-same-chains; offline ≠ production" honesty is the plugin's core discipline applied to security.
