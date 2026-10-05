---
name: frame-agent-task
description: Translate a Kaggle "submit-an-agent" simulation competition into a well-posed agent-building task BEFORE writing any policy — read the competition's REAL interface (observation/action shape, legal-move structure, the cumulative time budget + overage, daily submission cap, the skill-rating scoring) from its rules/starter code, and run the "start scripted, not RL" gate. Produces a reviewable Agent Task Brief + a machine-readable agent_task.json the rest of the game-agent pipeline reads. Use at the very start of building a bot for Pokemon TCG AI Battle, Orbit Wars, ConnectX, Lux, or any kaggle_environments agent-vs-agent contest.
allowed-tools: Read, Write, Edit, Glob
---

# frame-agent-task

Stage 1 of the **game-agent** pipeline: turn "I want to compete in this Kaggle agent comp" into a **well-posed agent task with the interface pinned down and an approach chosen** — *before* anyone writes a policy. The single most common way these submissions fail is a wrong assumption about the interface (the agent crashes, returns an illegal move, or busts the time budget) — so this stage's job is to get the facts right, from the competition's own rules and starter code, and write them down.

This skill does **not** write a policy or train anything. It interrogates the competition, fills an **Agent Task Brief**, and emits `agent_task.json` that `scaffold-submission`, `baseline-agent`, and `self-play-eval` all read.

## When to use
- Kicking off a bot for any Kaggle agent-vs-agent simulation competition (the first thing you do).
- When you don't yet know the exact `agent(obs, config)` interface, the legal-move format, or the time budget for the target comp.
- Before deciding **whether to reach for RL at all** (this skill includes the "start scripted" gate).

## Contract (important)
- **Facts come from the competition, not from memory.** Read them from the comp's rules page, its starter notebook, or the `kaggle_environments` env spec the user provides/points at. **Do NOT hardcode** an env name or observation schema — env ids differ from competition titles (e.g. Pokemon TCG AI Battle's `kaggle_environments` env is named **`cabt`**, not `pokemon_tcg`; if the comp uses a custom runtime, record `runtime: "custom"`).
- **Mark unknowns as unknown.** Anything you can't verify from a source goes in `unknowns[]` and `❓ OPEN` in the brief — never guessed. `scaffold-submission` will scaffold conservatively around an unknown.
- **Timeouts are usually cumulative/episode-level + overage, not per-move.** Record the model explicitly (`episode` vs `per_move`, the budget, and any overage buffer) — e.g. `cabt` is a 2000 ms episode `runTimeout` with `actTimeout: 0`; Orbit Wars is ~1 s/turn plus a 60 s overage buffer. Getting this wrong makes the time guard either useless or trigger-happy.
- **Feasibility ≠ competitiveness.** "RL is feasible under this budget" does NOT mean RL will win. Scripted/heuristic bots frequently beat RL agents in time-limited comps. The default verdict is **start scripted**; RL is a later escalation only if the scripted baseline plateaus.
- **No modeling, no source edits.** The deliverable is two files (brief + JSON), written to the working dir.

## Steps
Work through these as a short conversation; fill the brief as you go. Read the comp's starter code if the user has it locally (`Glob`/`Read`); otherwise ask them to paste the relevant rules/observation spec.

1. **Identify the competition and runtime.** Name + URL. Does it run on `kaggle_environments` (most agent comps) or a custom runtime? If `kaggle_environments`, find the **env id** (the string passed to `make("…")`) — confirm it, don't infer it from the title.
2. **Pin the agent interface.** The entry point is a function `agent(obs, config)` in `main.py` (both `agent(obs)` and `agent(obs, config)` are accepted — the framework truncates args via `co_argcount`). Record: what fields the observation carries, where the **legal moves / legal action set** live in it, and the exact **action format** the function must return (e.g. an action *index* for `cabt`; `[from_planet_id, angle_radians, num_ships]` for Orbit Wars; a 60-card deck list at deck-selection).
3. **Pin the hard constraints.** The competition env enforces: the agent must **never crash**, must return a **legal** action, and must stay within the **time budget**. Record the timeout *model* (episode vs per-move), the budget, the overage buffer, memory limit if any, and how illegal/late actions are penalized (kaggle_environments marks them `INVALID`).
4. **Pin the scoring + submission rules.** Continuous head-to-head **skill-rating ladder** (TrueSkill/Gaussian, ELO-style) — wins raise, losses lower, only your best bot shows. Record the **daily submission cap** (e.g. 5/day) — the conductor warns against it before submitting.
5. **Run the "start scripted, not RL" gate.** Given the interface and budget: is a scripted/heuristic policy enough to start? (Almost always yes.) Record `approach_gate` as `scripted` (default), `search` (if the game rewards lookahead/MCTS and the budget allows), or `rl` (only if you have the training budget AND a scripted baseline has plateaued). Note explicitly that this is a *starting* choice, revisited after `baseline-agent`.
6. **Write the brief + JSON.** Fill the template at `${CLAUDE_SKILL_DIR}/templates/agent-task-brief.md` → save as `agent_task_brief.md`, and fill `${CLAUDE_SKILL_DIR}/templates/agent_task.json` → save as `agent_task.json`. **Fill the "At a glance" Mermaid diagram** with real values — never leave placeholders. Leave unknowns as `❓ OPEN` / in `unknowns[]`.
7. **Confirm & hand off.** Walk the user through the brief, flag `unknowns[]`, and hand off to `scaffold-submission` to generate a submittable bundle around these facts.

## Output style
- Short, pointed questions during steps 1–5; push back on a guessed interface ("what's the source for that?").
- The brief is the artifact: the interface, constraints, scoring, and approach in clearly separated sections, opening with the filled Mermaid.
- End with the chosen `approach_gate` (and why it's "scripted" by default), the list of `❓ OPEN` unknowns, and the next skill (`scaffold-submission`).

## Grounding
Submission format and the agent entry point are from Kaggle's own simulation-competitions docs ([kaggle-cli/docs/simulation_competitions.md](https://github.com/Kaggle/kaggle-cli/blob/main/docs/simulation_competitions.md)) and the [`kaggle_environments`](https://github.com/Kaggle/kaggle-environments) source (the `co_argcount` arg-truncation in `agent.py`; the `cabt` / `orbit_wars` env specs for action shape and `runTimeout`/`actTimeout`/overage). The "start scripted, not RL" default is grounded in competition-winning practice: even the first deep-RL agent to win the IEEE microRTS competition (RAISocketAI, IEEE CoG 2024) was beaten by hand-written scripted bots when compute was unconstrained — RL won only under the competition's time limits, so a strong scripted baseline is the right first move and the bar RL must clear.
