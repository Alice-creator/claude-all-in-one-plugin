#!/usr/bin/env python3
"""Profile a game agent from the self-play ladder output: where does it win/lose (per
opponent), how clean is it (invalid-move rate), and what is the recommended next direction
(iterate heuristic / add search / consider RL) — as HYPOTHESES, not guarantees. The agent
analog of evaluate-model's slice-based error analysis.

Read-only: consumes ladder_summary.json (+ optional baseline_agent_metric.json). Writes
agent_profile.json + a report. Exit codes: 0 ok · 3 bad args/IO.

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


def matchup_shares(win_matrix, focus, pool):
    """For the focus agent, win share vs each opponent: wins_focus / (wins_focus + wins_opp)."""
    shares = {}
    for opp in pool:
        if opp == focus:
            continue
        fw = win_matrix.get(f"{focus}__vs__{opp}", 0)
        ow = win_matrix.get(f"{opp}__vs__{focus}", 0)
        total = fw + ow
        shares[opp] = (fw / total) if total else None
    return shares


def main():
    ap = argparse.ArgumentParser(description="Profile a game agent from the self-play ladder.")
    ap.add_argument("--ladder", default="ladder_summary.json")
    ap.add_argument("--metric", default=None, help="optional baseline_agent_metric.json for the health/recommendation")
    ap.add_argument("--focus", default=None, help="agent name to profile (default: top-rated)")
    args = ap.parse_args()

    if not os.path.exists(args.ladder):
        die(f"{args.ladder} not found — run self-play-eval first.", 3)
    with open(args.ladder) as f:
        lad = json.load(f)

    ratings = lad.get("ratings", {})
    if not ratings:
        die("ladder_summary.json has no ratings.", 3)
    pool = lad.get("pool", list(ratings.keys()))
    inv = lad.get("invalid_move_rate", {})
    win_rate = lad.get("win_rate", {})
    win_matrix = lad.get("win_matrix", {})

    focus = args.focus or max(ratings, key=lambda k: ratings[k])
    if focus not in ratings:
        die(f"focus agent '{focus}' not in the ladder pool {list(ratings.keys())}.", 3)

    shares = matchup_shares(win_matrix, focus, pool)
    decided = {k: v for k, v in shares.items() if v is not None}
    weakest = min(decided, key=lambda k: decided[k]) if decided else None
    strongest = max(decided, key=lambda k: decided[k]) if decided else None
    focus_inv = inv.get(focus)

    health_metric = None
    if args.metric and os.path.exists(args.metric):
        with open(args.metric) as f:
            health_metric = json.load(f)

    # Recommendations — HYPOTHESES, in priority order.
    recs = []
    if focus_inv:
        recs.append(("fix_legality_first",
                     f"{focus} has an invalid-move rate of {fmt(focus_inv)} — it sometimes plays illegal/late or crashes. "
                     "Fix the legal-fallback/time guard before anything else; this bleeds rating on Kaggle."))
    if weakest is not None and decided[weakest] < 0.45:
        recs.append(("target_weak_matchup",
                     f"Weakest vs {weakest} (win share {fmt(decided[weakest])}). Study those games and add a heuristic for that opponent's pattern."))
    base_rec = (health_metric or {}).get("recommendation")
    if base_rec == "scripted_sufficient":
        recs.append(("weigh_rl_cost",
                     "Scripted already wins most games. Scripted bots often beat RL under time limits — weigh RL's training cost (1000s of self-play games, GPU) before reaching for it. This plugin does not train RL; if you go that route, see SB3/CleanRL + PettingZoo self-play tutorials."))
    elif base_rec in ("iterate_heuristic_or_search", None):
        recs.append(("iterate_or_search",
                     "Beats the pool but not dominantly — iterate the heuristic, then add lookahead/search (e.g. MCTS for imperfect-info card games) before considering RL."))
    elif base_rec == "weak_vs_random_fix_first":
        recs.append(("fix_heuristic_first",
                     "Barely beats random — the policy or legal-action handling is the bottleneck, not model capacity. Fix that first."))
    if not recs:
        recs.append(("iterate", "Iterate the heuristic and re-rate; add a stronger opponent to the pool to keep the ladder honest."))

    profile = {
        "focus_agent": focus,
        "rating": ratings.get(focus),
        "win_rate": win_rate.get(focus),
        "invalid_move_rate": focus_inv,
        "matchup_win_share": shares,
        "weakest_matchup": weakest,
        "strongest_matchup": strongest,
        "recommendations": [{"key": k, "hypothesis": v} for k, v in recs],
        "offline_disclaimer": lad.get("offline_disclaimer", "Offline ladder vs your pool only; not a Kaggle standing."),
        "notes": "Recommendations are HYPOTHESES. Only a Kaggle submission validates any next-step claim.",
    }
    with open("agent_profile.json", "w") as f:
        json.dump(profile, f, indent=2)

    mk_rows = "\n".join(f"| {opp} | {fmt(s)} |" for opp, s in sorted(shares.items(), key=lambda kv: (kv[1] is None, kv[1])))
    rec_lines = "\n".join(f"{i+1}. **{k}** — {v}" for i, (k, v) in enumerate(recs))
    report = f"""# Agent profile — {focus}

> ⚠️ Built from a **local** ladder ({profile['offline_disclaimer']}) The recommendations below are **hypotheses** — only a Kaggle submission validates a next step.

## At a glance
```mermaid
flowchart LR
    F["{focus}<br/>rating {fmt(profile['rating'])}"] --> WK["weakest vs {weakest or 'n/a'}"]
    F --> INV["invalid rate {fmt(focus_inv)}"]
    F --> REC["next: {recs[0][0]}"]
```

**Rating:** {fmt(profile['rating'])} · **win rate (pool):** {fmt(profile['win_rate'])} · **invalid-move rate:** {fmt(focus_inv)}
**Strongest matchup:** {strongest or 'n/a'} · **weakest matchup:** {weakest or 'n/a'}

### Win share by opponent
| opponent | {focus} win share |
|---|---|
{mk_rows}

### Recommended next directions (hypotheses)
{rec_lines}

## Next
→ Apply one change, re-run `self-play-eval`, and confirm the rating moved the right way before submitting. The `game-agent-builder` conductor gates the final submission on a clean run.
"""
    with open("agent_profile_report.md", "w") as f:
        f.write(report)

    print(f"Profiled {focus}: rating {fmt(profile['rating'])}, invalid rate {fmt(focus_inv)}, weakest vs {weakest}.")
    print("wrote agent_profile.json + agent_profile_report.md")


if __name__ == "__main__":
    main()
