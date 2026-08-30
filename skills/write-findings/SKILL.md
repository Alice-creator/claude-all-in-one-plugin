---
name: write-findings
description: Assemble the research write-up from the pipeline's sidecars, with the headline taken from analysis.json rather than the author — it will not write a positive claim over a NOT_SUPPORTED / INCONCLUSIVE / BELOW_THRESHOLD / CONTRADICTED verdict, will not present an unvalidated failure taxonomy as a result, and refuses outright when the sidecars disagree about which hypothesis this was. Fills a reproducibility checklist from actual values and always emits a "What this does NOT show" section. Use as the final REPORT step of a research round.
allowed-tools: Bash, Read, Write, Glob
---

# write-findings

Write it up honestly, including the parts that did not work. The reproducibility checklist exists because a survey of 50 RL papers found significance testing in **5%** of them, and plots with shaded regions that never said whether the shading was a confidence interval or a standard deviation.

## When to use
- The last step of a research round, after `analyze-trials` (and `diagnose-failures` if it ran).
- When someone needs the result written down in a form another person could check or repeat.
- NOT for computing anything — every number comes from a sidecar, never recomputed here, never remembered.

## Contract (important)
- **The verdict comes from `analysis.json`, and is re-derived.** The script recomputes the verdict from the interval, `min_effect` and `direction`, and refuses if the stored string disagrees — so hand-editing the sidecar does not change the headline.
- **`--title` may not assert a result** the data did not show; a positive-sounding title over a non-SUPPORTED verdict is refused.
- **The headline arm is never chosen by sort order.** With more than one arm compared, `--primary-config` must name the preregistered treatment: picking the best arm is HARKing, and choosing alphabetically means renaming a config flips the conclusion.
- **`--task-validity` is required.** Omitting the audit used to yield a green report whose small print said "not audited".
- **Refuses when the sidecars disagree** about `prereg_hash` — that means the hypothesis moved partway through, so nothing here is confirmatory.
- **An unvalidated failure taxonomy is rendered as an observation**, explicitly labelled, never as a measured distribution.
- **"What this does NOT show" is mandatory** and auto-populated: the holdout ceiling, the validity items answered NO, every analysis warning, the exploratory secondary metrics, the power situation, and contamination.
- **Offline ≠ deployed.** Same boundary `evaluate-model`, `check-drift` and `evaluate-detection` hold: these are held-out offline scores, not production performance.
- **Blanks are reported as blanks.** An unrecorded checklist item shows as ❌ `_not recorded_`, never inferred.

## Steps
1. **Assemble:**
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/write-findings/scripts/findings.py" \
       --prereg <dir>/prereg.json --analysis <dir>/analysis.json \
       --design <dir>/experiment_design.json --task-validity <dir>/task_validity.json \
       --manifest <bundle>/trials_manifest.json --failures <dir>/failure_taxonomy.json \
       [--title "..."] [--primary-config <arm>] [--exploratory] --out-dir <dir>
   ```
2. **Read the reproducibility table for ❌ rows** and fill the real gaps rather than deleting the rows.
3. **⏸ CHECKPOINT — the human decides what to claim publicly.** The script fixes what the *data* supports; how much to say beyond that is theirs.
4. **If the verdict is not SUPPORTED, publish it anyway.** An unpublished preregistered null is what makes a literature look more positive than its evidence.

## Output style
- Lead with the verdict badge and one sentence, then the interval.
- Keep "What this does NOT show" adjacent to the result, not buried at the end.
- Never present a secondary metric as if it were confirmatory, however it came out.

## Grounding
Reproducibility checklist lineage: Pineau et al., *Improving Reproducibility in Machine Learning Research* (NeurIPS 2019 Reproducibility Program report, JMLR 22 / arXiv 2003.12206) for the checklist itself. The "5% of 50 RL papers used significance testing" and ambiguous-shading figures are reported from Pineau's NeurIPS 2018 invited talk *Reproducible, Reusable, and Robust Reinforcement Learning*, not from the JMLR paper; the closely related published survey is Henderson et al., *Deep Reinforcement Learning that Matters* (AAAI 2018, arXiv 1709.06560). Reporting requirements (open harness, contamination measures, construct validity, CIs, trivial and human baselines, interpretation guidance): ABC R.1–R.13 (arXiv 2507.02825). Contamination evidence for the "unexplained-high score is suspect" warning: *Does SWE-Bench-Verified Test Agent Ability or Model Memory?* (arXiv 2512.10218).
