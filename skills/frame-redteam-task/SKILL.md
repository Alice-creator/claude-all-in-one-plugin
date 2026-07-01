---
name: frame-redteam-task
description: Frame an agent-security red-team task BEFORE building any attack — establish the AUTHORIZATION boundary (sandbox/competition/owned-system only), read the target's real interface and scoring (the Kaggle "AI Agent Security - Multi-Step Tool Attacks" AttackAlgorithm, or a local AgentDojo/InjecAgent harness), pin the success predicates (Attack Success Rate, Targeted ASR, Utility-Under-Attack) and the replay-determinism + time-budget rules. Produces a reviewable Red-Team Brief + redteam_task.json. Use at the very start of any tool-using-agent red-team, and to gate that the target is authorized.
allowed-tools: Read, Write, Edit, Glob
---

# frame-redteam-task

Stage 1 of the **agent-security** pipeline: turn "I want to red-team a tool-using agent" into a **well-scoped, authorized task with the predicates and rules pinned down** — before any attack is built. This is offensive work, so the first job is to establish that the target is one you're allowed to test, and the second is to get the interface and scoring right so the later stages produce *reproducible* findings, not noise.

This skill does **not** build attacks. It runs the authorization gate, fills a **Red-Team Brief**, and emits `redteam_task.json` that `scaffold-attack`, `build-attack-chains`, and `run-redteam-eval` read (including the predicates that `build-attack-chains` is locked to).

## When to use
- Kicking off a red-team of a tool-using LLM agent — for the Kaggle agent-security competition, or a local AgentDojo/InjecAgent harness you control.
- Before writing a single attack — to confirm the target is authorized and to pin the success predicates and replay rules.

## Contract (important — authorization is the first gate)
- **Authorized scope ONLY.** A valid target is exactly one of: (a) the official Kaggle "AI Agent Security - Multi-Step Tool Attacks" sandbox (record its `comp_id`), (b) a local AgentDojo / InjecAgent / equivalent harness the user runs, or (c) a system the user **owns or has explicit written permission to test**. Record which, in `redteam_task.json`.
- **Mandatory refusals.** Refuse to frame a task whose target is: a production/live LLM service or named real product (ChatGPT, Gemini, Claude in production, a commercial API), any system the user doesn't control or have permission for, or **another competitor's submission/data**. On refusal, explain why and point at the legitimate paths (Kaggle rules, a local sandbox, responsible disclosure).
- **One-time attestation, recorded.** Before this stage completes, the user must confirm: *"This is authorized red-team research on a sandbox/competition/system I own or have permission to test; I will not target production systems or other competitors, exfiltrate data, or violate platform rules."* Record `authorization_confirmed: true` — downstream skills check it.
- **Predicates are pinned here, and they lock the attacks.** Record the exact `benign_task`, the `benign_success` predicate, and the `targeted_unsafe` predicate(s). `build-attack-chains` generates ONLY for these predicates — no open-ended "jailbreak for anything."
- **Determinism + budget are competition integrity, not optional.** Record the replay-determinism requirement (no randomness/external I/O/hard-coded state) and the time budget (e.g. 1800 s). These keep findings reproducible and the contest fair.
- **The exact comp interface may be unverifiable up front.** If you can't read the official `AttackAlgorithm`/`attack.py` interface from the comp's starter code, record `attack_interface: "confirm_from_starter_code"` and mark it in `unknowns[]` — `scaffold-attack` builds a thin adapter and the conductor gates on confirming it.

## Steps
Short conversation; read the comp/harness docs the user has locally (`Glob`/`Read`) or ask them to paste the interface + scoring.

1. **Run the authorization gate FIRST.** Identify the target and confirm it's in the authorized set (a/b/c above). If not → refuse and stop. Capture the one-time attestation.
2. **Identify the target + interface.** Kaggle comp (record `comp_id`, `runtime`) or local harness (AgentDojo/InjecAgent). Read the attack interface (e.g. an `AttackAlgorithm` interacting via `env.interact(prompt)`, returning replayable candidates) — or mark it `confirm_from_starter_code`.
3. **Pin the threat model + predicates.** Multi-step indirect prompt injection ("harmless in isolation, harmful when chained"). Record the `benign_task` (what the agent is legitimately doing), `benign_success` (the predicate that the legit task completed), and the `targeted_unsafe` predicate(s) (the specific unsafe tool action an attack tries to trigger).
4. **Pin scoring + rules.** The metrics: Benign Utility, Utility-Under-Attack, (Targeted) Attack Success Rate — computed by deterministic state predicates, **not an LLM judge** (a judge can itself be hijacked). Record the time budget and the replay-determinism requirement.
5. **Write the brief + JSON.** Fill `${CLAUDE_PLUGIN_ROOT}/skills/frame-redteam-task/templates/redteam-brief.md` → `redteam_brief.md`, and `${CLAUDE_PLUGIN_ROOT}/skills/frame-redteam-task/templates/redteam_task.json` → `redteam_task.json`. (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/frame-redteam-task/templates/…`.) Fill the "At a glance" Mermaid with real values; leave unknowns as `❓ OPEN` / in `unknowns[]`.
6. **Confirm & hand off.** Walk the user through the brief, confirm the authorization line and the predicates, and hand off to `scaffold-attack`.

## Output style
- Lead with authorization: state the target class (sandbox/harness/owned) and that attestation was captured — or refuse plainly.
- The brief is the artifact: authorization, interface, predicates, scoring, and rules in separate sections, opening with the filled Mermaid.
- End with the pinned predicates, the `unknowns[]`, and the next skill (`scaffold-attack`).

## Grounding
The threat model (indirect prompt injection: untrusted tool output hijacks a tool-using agent) and the formal, judge-free metrics (Benign Utility, Utility-Under-Attack, Targeted Attack Success Rate over deterministic state predicates) are from **AgentDojo** (Debenedetti et al., NeurIPS 2024) and **InjecAgent** (Zhan et al., ACL Findings 2024), the canonical agent-security benchmarks; multi-step "harmless-in-isolation" chaining follows the STAC line of work. The authorization-first posture is standard responsible-security-research practice: test only systems you own or are explicitly permitted to test (CFAA and equivalents make unauthorized access illegal).
