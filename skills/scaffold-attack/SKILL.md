---
name: scaffold-attack
description: Generate the code scaffold for an AUTHORIZED agent-security red-team — an attack.py adapter (a thin shim to the Kaggle "Multi-Step Tool Attacks" AttackAlgorithm interface, confirmed from the comp's starter code since it isn't public) plus a target_adapter.py stub matching run-redteam-eval's protocol, both carrying an authorization header. Scaffolds the interface, not exploit content. Use after frame-redteam-task (which captures the authorization attestation), before build-attack-chains.
allowed-tools: Bash, Read, Write, Glob
---

# scaffold-attack

Get the plumbing right before the attacks: this skill emits the adapter code that connects predicate-locked attack chains to the target — an `attack.py` shim for the competition's `AttackAlgorithm` interface, and a `target_adapter.py` stub that `run-redteam-eval` calls. It scaffolds the **interface, not the exploit** (the chains come from `build-attack-chains`), and every generated file opens with an authorization header.

The Kaggle competition's exact `AttackAlgorithm` interface is **not public**, so the generated `attack.py` is a clearly-marked shim you complete from the competition's own starter code — the conductor gates on confirming it rather than guessing.

## When to use
- After `frame-redteam-task` (it reads `redteam_task.json` and requires the authorization attestation).
- To get the adapter files (`attack.py`, `target_adapter.py`) wired to the right interfaces before generating chains.

## Contract (important)
- **Authorized targets only.** Refuses (exit 4) unless `authorization_confirmed` is true in `redteam_task.json`. Every generated file carries the authorization header (sandbox/competition/owned-system only; no production/named-product targets; no other competitors).
- **Scaffolds interface, not exploits.** It writes shims + TODOs; the attack content is the predicate-locked output of `build-attack-chains`.
- **Deterministic & replayable.** The templates state the competition-integrity rule: no randomness / external I/O / hidden state, so candidates replay identically.
- **Honest about the unknown interface.** `attack.py` is a shim; it does not invent the competition's real `AttackAlgorithm` API — it tells you to confirm it from the starter code.
- **Never edits source/competition files.** Writes a new `<target>_attack/` dir.

## Steps
1. **Need `redteam_task.json` first** (with `authorization_confirmed: true`). If missing, run `frame-redteam-task`.
2. **Run:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/scaffold-attack/scripts/scaffold_attack.py" --task-json redteam_task.json
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/scaffold-attack/scripts/scaffold_attack.py`.)
3. **Point out the two TODOs:** confirm the real `AttackAlgorithm` interface in `attack.py` from the comp starter code; wire `target_adapter.py`'s `run(prompts, predicates)` to the authorized target (or use `run-redteam-eval --target mock` to smoke-test the harness first).
4. **Hand off:** → `build-attack-chains` (generate the predicate-locked chains the adapter replays).

## Output style
- Lead with authorization (it refused, or it scaffolded for the declared authorized target).
- Name the two files and the two TODOs; be explicit that `attack.py` is a shim until the real interface is confirmed.

## Grounding
The need for a thin, confirmed-from-starter-code adapter reflects that the competition's `AttackAlgorithm` interface is not publicly documented (verified during research — the comp page is gated). The `target_adapter.run(prompts, predicates)` protocol matches the judge-free, deterministic evaluation used by **AgentDojo** (Debenedetti et al., NeurIPS 2024) and **InjecAgent** (Zhan et al., ACL Findings 2024). The replay-determinism requirement is standard competition integrity (the evaluator replays candidates rather than trusting attacker traces).
