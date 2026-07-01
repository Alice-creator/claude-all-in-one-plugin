#!/usr/bin/env python3
"""Local self-play ladder: run a pool of agents (your bot, prior versions, baselines,
builtins) against each other over many matches and produce ELO (stdlib) or TrueSkill
(optional) ratings + a win matrix + per-agent invalid-move rate. Lets you iterate offline
BEFORE spending daily Kaggle submissions.

Runs real episodes via kaggle_environments. Writes ladder_summary.json + a report.
Exit codes: 0 ok · 2 dependency missing · 3 bad args/IO.

HONEST LIMIT (stated in every report): this offline rating is vs YOUR pool only. The Kaggle
ladder has a far larger, daily-shifting opponent pool — offline rating is NOT a leaderboard standing.

NOTE: helpers here are deliberately self-contained (copied, not imported, across skills).
"""
import argparse
import itertools
import json
import os
import random
import sys


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def fmt(v):
    return "n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def expected(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def elo_update(ra, rb, sa, k=24.0):
    """Return new (ra, rb) after a result sa for A (1 win / 0.5 draw / 0 loss)."""
    ea = expected(ra, rb)
    return ra + k * (sa - ea), rb + k * ((1.0 - sa) - (1.0 - ea))


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


def name_of(slot):
    return slot if "/" not in slot and not slot.endswith(".py") else os.path.basename(os.path.dirname(os.path.abspath(slot))) + "/" + os.path.basename(slot)


def main():
    ap = argparse.ArgumentParser(description="Local self-play ELO/TrueSkill ladder for game agents.")
    ap.add_argument("--task-json", default="agent_task.json")
    ap.add_argument("--agents", nargs="+", required=True,
                    help="pool: agent file paths and/or builtin names (e.g. main.py prior_v1.py random)")
    ap.add_argument("--matches", type=int, default=60, help="matches per unordered pair (2p) or total lineups (np)")
    ap.add_argument("--method", choices=["elo", "trueskill"], default="elo")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if len(args.agents) < 2:
        die("need at least 2 agents in the pool.", 3)
    if not os.path.exists(args.task_json):
        die(f"{args.task_json} not found — run frame-agent-task first.", 3)
    with open(args.task_json) as f:
        task = json.load(f)
    env_id = task.get("env_id")
    if not env_id or env_id == "unknown":
        die("env_id unknown in agent_task.json — cannot run episodes.", 3)
    for a in args.agents:
        if ("/" in a or a.endswith(".py")) and not os.path.exists(a):
            die(f"agent file not found: {a}", 3)

    try:
        from kaggle_environments import make
    except Exception:
        die("kaggle_environments not installed — pip install kaggle-environments.", 2)

    use_trueskill = False
    if args.method == "trueskill":
        try:
            import trueskill  # noqa: F401
            use_trueskill = True
        except Exception:
            print("trueskill not installed — falling back to ELO (pip install trueskill for TrueSkill).", file=sys.stderr)

    rng = random.Random(args.seed)
    names = [name_of(a) for a in args.agents]
    idx_of = {a: i for i, a in enumerate(args.agents)}
    ratings = {a: 1500.0 for a in args.agents}
    played = {a: 0 for a in args.agents}
    wins = {a: 0 for a in args.agents}
    invalid = {a: 0 for a in args.agents}
    win_matrix = {}  # "A_vs_B" -> wins of A over B

    probe = make(env_id, debug=False)
    n = agent_count(probe)

    if n == 2:
        lineups = []
        for a, b in itertools.combinations(args.agents, 2):
            lineups += [(a, b)] * args.matches
    else:
        lineups = []
        for _ in range(args.matches * len(args.agents)):
            if len(args.agents) >= n:
                lineups.append(tuple(rng.sample(args.agents, n)))
            else:
                lineups.append(tuple(rng.choices(args.agents, k=n)))
    rng.shuffle(lineups)

    ts_env = None
    ts_ratings = None
    if use_trueskill:
        import trueskill
        ts_env = trueskill.TrueSkill(draw_probability=0.10)
        ts_ratings = {a: ts_env.create_rating() for a in args.agents}

    for lineup in lineups:
        try:
            env = make(env_id, debug=False)
            env.reset(n)
            env.run(list(lineup))
            final = env.steps[-1]
            rewards = [s.get("reward") for s in final]
            for slot_i, a in enumerate(lineup):
                played[a] += 1
                if final[slot_i].get("status") in ("INVALID", "ERROR", "TIMEOUT"):
                    invalid[a] += 1
            ranks = []
            for slot_i, a in enumerate(lineup):
                res = outcome(rewards, slot_i)
                if res == "win":
                    wins[a] += 1
                ranks.append((a, slot_i, res, rewards[slot_i] if rewards[slot_i] is not None else float("-inf")))
            # pairwise ELO among lineup members by reward
            if not use_trueskill:
                for (a, ai, _, ra_), (b, bi, _, rb_) in itertools.combinations(ranks, 2):
                    if ra_ == float("-inf") and rb_ == float("-inf"):
                        continue
                    sa = 1.0 if ra_ > rb_ else (0.0 if ra_ < rb_ else 0.5)
                    na, nb = elo_update(ratings[a], ratings[b], sa)
                    ratings[a], ratings[b] = na, nb
                    if sa == 1.0:
                        win_matrix[f"{a}__vs__{b}"] = win_matrix.get(f"{a}__vs__{b}", 0) + 1
                    elif sa == 0.0:
                        win_matrix[f"{b}__vs__{a}"] = win_matrix.get(f"{b}__vs__{a}", 0) + 1
            else:
                import trueskill
                order = sorted(range(len(lineup)), key=lambda k: -(rewards[k] if rewards[k] is not None else float("-inf")))
                rating_groups = [[ts_ratings[lineup[k]]] for k in order]
                rated = ts_env.rate(rating_groups)
                for pos, k in enumerate(order):
                    ts_ratings[lineup[k]] = rated[pos][0]
        except Exception:
            for a in lineup:
                invalid[a] += 1  # a lineup that crashed counts against participants

    if use_trueskill:
        final_ratings = {name_of(a): round(ts_ratings[a].mu - 3 * ts_ratings[a].sigma, 1) for a in args.agents}
        method = "TrueSkill (conservative mu-3sigma)"
    else:
        final_ratings = {name_of(a): round(ratings[a], 1) for a in args.agents}
        method = "ELO"

    inv_rate = {name_of(a): (invalid[a] / played[a] if played[a] else None) for a in args.agents}
    win_rate = {name_of(a): (wins[a] / played[a] if played[a] else None) for a in args.agents}

    summary = {
        "env_id": env_id,
        "pool": names,
        "matches_total": len(lineups),
        "players_per_match": n,
        "method": method,
        "seed": args.seed,
        "ratings": final_ratings,
        "win_rate": win_rate,
        "win_matrix": win_matrix,
        "invalid_move_rate": inv_rate,
        "offline_disclaimer": "Offline ladder vs this pool only. The Kaggle ladder is far larger and shifts daily; "
                              "this rating is NOT a leaderboard standing.",
        "notes": "",
    }
    with open("ladder_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    ranked = sorted(final_ratings.items(), key=lambda kv: -kv[1])
    rows = "\n".join(f"| {nm} | {fmt(r)} | {fmt(win_rate[nm])} | {fmt(inv_rate[nm])} |" for nm, r in ranked)
    leader = ranked[0][0]
    report = f"""# Self-play ladder — {env_id}

> ⚠️ **Offline ≠ Kaggle.** This rating is from {len(lineups)} matches against **your pool only** ({', '.join(names)}). The Kaggle ladder has a far larger, daily-shifting opponent pool — **this is not a leaderboard standing.** Use it to compare *your* variants, nothing more.

## At a glance
```mermaid
flowchart LR
    POOL["pool: {len(names)} agents"] -->|{len(lineups)} matches| LAD["{method} ladder"]
    LAD --> TOP["top: {leader}"]
    LAD --> INV["track invalid-move rate"]
```

| agent | rating | win rate | invalid rate |
|---|---|---|---|
{rows}

## Read
- Higher rating = beats the rest of **this pool** more often. Compare your variants here before submitting.
- A non-zero **invalid rate** means an agent made illegal/late moves or crashed — fix it; it bleeds rating on Kaggle too.

## Next
→ `profile-agent` (where does the top agent win/lose, and what to try next).
"""
    with open("ladder_report.md", "w") as f:
        f.write(report)

    print(f"{method} ladder over {len(lineups)} matches. Top: {leader} ({fmt(ranked[0][1])}).")
    print("wrote ladder_summary.json + ladder_report.md")


if __name__ == "__main__":
    main()
