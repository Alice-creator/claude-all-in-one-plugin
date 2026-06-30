#!/usr/bin/env python3
"""Measure a scripted/heuristic agent against a simple opponent (default: random) over N
episodes — the "number to beat" for the game-agent pipeline, plus a crash/timeout/illegal
HEALTH gate. Mirrors the `baseline` skill's job (establish a floor before complexity), here
for an agent instead of a tabular model.

Runs real episodes via kaggle_environments. Writes baseline_agent_metric.json + a report.
Exit codes: 0 ok · 2 dependency missing · 3 bad args/IO.

The recommendation it emits is a HYPOTHESIS (scripted vs search vs RL), never a guarantee —
only a Kaggle submission validates real standing.

NOTE: helpers here are deliberately self-contained (copied, not imported, across skills).
"""
import argparse
import json
import os
import sys


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def fmt(v):
    return "n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def agent_count(env):
    """kaggle_environments env.specification.agents is a list of VALID player counts (e.g. [2] or [2, 4]),
    not the count itself. Pick the first valid count; default to 2."""
    a = getattr(env.specification, "agents", None)
    if isinstance(a, (list, tuple)) and a and isinstance(a[0], int):
        return a[0]
    if isinstance(a, int):
        return a
    return 2


def outcome(rewards, idx):
    """win/draw/loss for agent `idx` from a list of final rewards (higher = better)."""
    vals = [r for r in rewards if r is not None]
    if not vals or rewards[idx] is None:
        return "unknown"
    best = max(vals)
    if rewards[idx] < best:
        return "loss"
    if sum(1 for r in vals if r == best) > 1:  # tied at the top
        return "draw"
    return "win"


def main():
    ap = argparse.ArgumentParser(description="Measure a game agent vs an opponent (the agent baseline + health gate).")
    ap.add_argument("--task-json", default="agent_task.json")
    ap.add_argument("--agent", default=None, help="path to the agent file to measure (default: <env>_submission/main.py)")
    ap.add_argument("--opponent", default="random", help="'random', a builtin name, or a path to another agent file")
    ap.add_argument("--episodes", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not os.path.exists(args.task_json):
        die(f"{args.task_json} not found — run frame-agent-task first.", 3)
    with open(args.task_json) as f:
        task = json.load(f)
    env_id = task.get("env_id")
    if not env_id or env_id == "unknown":
        die("env_id unknown in agent_task.json — cannot run episodes.", 3)

    agent = args.agent or os.path.join(f"{env_id}_submission", "main.py")
    if not os.path.exists(agent):
        die(f"agent file not found: {agent} — run scaffold-submission, or pass --agent.", 3)
    if args.opponent not in ("random", "reaction", "negamax") and os.path.exists(args.opponent) is False and "/" in args.opponent:
        die(f"opponent file not found: {args.opponent}", 3)

    try:
        from kaggle_environments import make
    except Exception:
        die("kaggle_environments not installed — pip install kaggle-environments (needed to run episodes).", 2)

    wins = draws = losses = unknown = 0
    crashes = timeouts = illegal = 0
    for i in range(args.episodes):
        try:
            env = make(env_id, debug=False)
            n = agent_count(env)
            slots = [agent] + [args.opponent] * (n - 1)
            env.reset(n)
            env.run(slots)
            final = env.steps[-1]
            rewards = [s.get("reward") for s in final]
            res = outcome(rewards, 0)
            wins += res == "win"; draws += res == "draw"; losses += res == "loss"; unknown += res == "unknown"
            status0 = final[0].get("status")
            if status0 == "TIMEOUT":
                timeouts += 1
            elif status0 in ("INVALID", "ERROR"):
                illegal += 1
        except Exception as e:
            crashes += 1
            if i == 0:
                print(f"  first-episode crash: {type(e).__name__}: {e}", file=sys.stderr)

    played = args.episodes
    decided = wins + draws + losses
    win_rate = wins / decided if decided else None
    health = "PASS" if (crashes == 0 and timeouts == 0) else "FAIL"

    if win_rate is None:
        rec = "inconclusive"
    elif win_rate >= 0.65:
        rec = "scripted_sufficient"
    elif win_rate >= 0.55:
        rec = "iterate_heuristic_or_search"
    else:
        rec = "weak_vs_random_fix_first"

    metric = {
        "agent_type": "scripted/heuristic (as written in the agent file)",
        "agent_file": os.path.abspath(agent),
        "opponent": args.opponent,
        "episodes": played,
        "win_rate": win_rate,
        "draw_rate": draws / decided if decided else None,
        "loss_rate": losses / decided if decided else None,
        "primary_metric": "win_rate",
        "value": win_rate,
        "health": {"crashes": crashes, "timeouts": timeouts, "illegal_caught": illegal,
                   "unknown_outcomes": unknown, "status": health},
        "recommendation": rec,
        "eval_on": "local",
        "notes": "win_rate is vs a simple opponent locally; NOT a Kaggle standing. Recommendation is a hypothesis.",
    }
    out_dir = os.path.dirname(os.path.abspath(agent))
    with open(os.path.join(out_dir, "baseline_agent_metric.json"), "w") as f:
        json.dump(metric, f, indent=2)

    rec_line = {
        "scripted_sufficient": "Scripted already wins most games vs random — scripted bots often beat RL under time limits, so weigh RL's training cost before reaching for it.",
        "iterate_heuristic_or_search": "Beats random but not decisively — iterate the heuristic or add lookahead/search before considering RL.",
        "weak_vs_random_fix_first": "Barely beats (or loses to) random — fix the heuristic/legal-action handling first; complexity won't rescue a broken policy.",
        "inconclusive": "Outcomes couldn't be read from rewards — check the env's reward field before trusting these numbers.",
    }[rec]
    health_line = ("✅ no crashes or timeouts" if health == "PASS"
                   else f"❌ {crashes} crashes / {timeouts} timeouts — FIX the legal-fallback before self-play")

    report = f"""# Agent baseline — {env_id}

## At a glance
```mermaid
flowchart LR
    AG["agent<br/>{os.path.basename(agent)}"] -->|{played} episodes| OPP["vs {args.opponent}"]
    OPP --> WR["win rate {fmt(win_rate)}"]
    WR --> REC["{rec}"]
    AG --> H["health: {health}"]
```

> ⚠️ This win rate is vs **{args.opponent}** locally. It is **not** a Kaggle ladder standing (different, much larger opponent pool). The recommendation below is a hypothesis — only a submission validates it.

**Win/draw/loss:** {wins}/{draws}/{losses} (unknown: {unknown}) over {played} episodes · **win rate {fmt(win_rate)}**
**Health:** {health_line} (illegal caught: {illegal})
**Recommendation:** `{rec}` — {rec_line}

## Next
- If health is FAIL → fix the agent's legal-fallback / policy, then re-run.
- → `self-play-eval` to rate it on a local ladder against multiple opponents/prior versions.
"""
    with open(os.path.join(out_dir, "baseline_agent_report.md"), "w") as f:
        f.write(report)

    print(f"win rate {fmt(win_rate)} vs {args.opponent} over {played} episodes · health {health} · rec {rec}")
    print(f"wrote baseline_agent_metric.json + baseline_agent_report.md in {out_dir}/")
    if health == "FAIL":
        print("HEALTH FAIL: crashes/timeouts present — fix before self-play-eval.", file=sys.stderr)


if __name__ == "__main__":
    main()
