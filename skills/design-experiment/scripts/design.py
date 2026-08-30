#!/usr/bin/env python3
"""design-experiment: size and cost the experiment BEFORE spending money on it.

Four things get decided here, each of which is a documented way agent research goes wrong:
  1. HOLDOUT LEVEL. The more general the claim, the more the holdout must differ from what you
     developed on (Kapoor et al. 2024: distribution -> OOD samples -> unseen TASKS -> unseen
     DOMAINS). Their survey found 1/8 domain-general and 0/2 fully-general benchmarks had an
     appropriate holdout. Claiming domain-general with no held-out tasks is REFUSED here.
  2. SAMPLE SIZE, from a power analysis against the preregistered minimum effect — not a guess.
  3. THE CLUSTERING PENALTY. N tasks x K runs are NOT N*K independent observations; runs within a
     task are correlated. The design effect 1+(K-1)*ICC converts them into an effective N.
  4. COST, as a first-class design constraint. Agent evals are expensive enough (HAL: ~$40k for
     21,730 rollouts) that cost is the reason results ship without error bars. Budget it up front
     or the error bars are what gets cut.

Exit codes: 0 ok · 2 IO issue · 3 bad/missing input · 4 refused.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical
across scripts); `prereg_hash` MUST stay identical everywhere it appears.
"""
import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import unicodedata


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def prereg_hash(prereg):
    """SHA-256 over the LOCKED fields. Normalised so a cosmetic edit (NFD vs NFC, trailing space,
    1 vs 1.0) does NOT trigger a spurious HARKing refusal — a false alarm here teaches researchers
    to route around the check, which is worse than no check. `generality_level` is locked because
    escalating the claim's scope after seeing results is HARKing even when the number is untouched."""
    locked = {}
    for k in ("hypothesis", "primary_metric", "baseline", "min_effect", "direction",
              "falsification", "generality_level"):
        v = prereg.get(k)
        if isinstance(v, str):
            v = unicodedata.normalize("NFC", " ".join(v.split()))
        elif isinstance(v, bool):
            pass
        elif isinstance(v, (int, float)):
            v = float(v)
        locked[k] = v
    canon = json.dumps(locked, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def load_prereg(path):
    if not os.path.exists(path):
        die(f"No prereg at {path}. Run frame-research-question first — sizing an experiment for an "
            "unstated hypothesis is how the metric ends up chosen after the fact.", 3)
    with open(path) as f:
        p = json.load(f)
    recomputed = prereg_hash(p)
    if p.get("prereg_hash") != recomputed:
        die(f"REFUSED — prereg.json was edited by hand: stored hash {p.get('prereg_hash')} != "
            f"recomputed {recomputed}. Re-register, or amend it properly with "
            'prereg.py --amend "<reason>" so the change is on the record.', 4)
    return p


# Holdout requirement per level of generality (Kapoor et al. 2024, Table 1).
HOLDOUT_REQUIRED = {
    "distribution-specific": ("in-distribution", "in-distribution samples held out"),
    "task-specific": ("ood", "out-of-distribution samples (the task, but shifted)"),
    "domain-general": ("unseen-tasks", "whole TASKS never seen during development"),
    "fully-general": ("unseen-domains", "whole DOMAINS never seen during development"),
}


def n_per_arm_unpaired(p1, p2, alpha=0.05, power=0.80):
    """Two-proportion sample size per arm. Standard normal-approximation formula."""
    z_a = statistics.NormalDist().inv_cdf(1 - alpha / 2)
    z_b = statistics.NormalDist().inv_cdf(power)
    delta = abs(p2 - p1)
    if delta == 0:
        return float("inf")
    return math.ceil(((z_a + z_b) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2))) / delta ** 2)


def n_pairs_paired(delta, discordance, alpha=0.05, power=0.80):
    """Paired (same tasks, both configs) sample size. Depends on the DISCORDANT rate: the
    fraction of tasks where the two configs disagree. Pairing removes task-difficulty variance,
    which is why it is the cheapest precision available (Miller 2024 calls it 'free')."""
    z_a = statistics.NormalDist().inv_cdf(1 - alpha / 2)
    z_b = statistics.NormalDist().inv_cdf(power)
    if delta <= 0 or discordance <= 0:
        return float("inf")
    return math.ceil(((z_a + z_b) ** 2 * discordance) / delta ** 2)


def design_effect(k, icc):
    """Runs within one task are correlated, so N*K observations are worth fewer than N*K.
    deff = 1 + (K-1)*ICC; effective N = N*K/deff."""
    return 1.0 + (k - 1) * icc


def tasks_required(n_independent, k, icc):
    """Convert a required number of INDEPENDENT observations into a required number of TASKS.

    The sample-size formulas return independent observations. Runs within a task are correlated, so
    K runs are worth K/deff independent ones: tasks = n_independent * deff / K (Kish). Without this
    conversion the design effect is decorative — --icc and --k-runs would not move the verdict at
    all, and a design with 800 genuinely independent observations against a requirement of 236 would
    still be stamped UNDERPOWERED."""
    if n_independent == float("inf"):
        return float("inf")
    return math.ceil(n_independent * design_effect(k, icc) / k)


def evaluate_design(args, p):
    p1 = args.baseline_rate
    delta = p["min_effect"]
    raw_target = p1 + delta if p["direction"] == "increase" else p1 - delta
    p2 = min(0.999, max(0.001, raw_target))
    unpaired_obs = n_per_arm_unpaired(p1, p2)
    paired_obs = n_pairs_paired(delta, args.paired_discordance)
    deff = design_effect(args.k_runs, args.icc)
    eff_n = (args.n_tasks * args.k_runs) / deff
    unpaired = tasks_required(unpaired_obs, args.k_runs, args.icc)
    paired = tasks_required(paired_obs, args.k_runs, args.icc)
    total_runs = args.n_tasks * args.k_runs * args.n_configs
    projected = total_runs * args.cost_per_run
    required = paired if args.paired else unpaired
    return {
        "target_rate_unreachable": raw_target != p2,
        "n_independent_obs_required": None if unpaired_obs == float("inf") else unpaired_obs,
        "baseline_rate": p1, "target_rate": round(p2, 4), "min_effect": delta,
        "alpha": 0.05, "power": 0.80, "paired": bool(args.paired),
        "n_tasks_required_unpaired_per_arm": None if unpaired == float("inf") else unpaired,
        "n_tasks_required_paired": None if paired == float("inf") else paired,
        "n_tasks_required": None if required == float("inf") else required,
        "n_tasks_required_not_estimable": required == float("inf"),
        "n_tasks_planned": args.n_tasks,
        "underpowered": bool(required == float("inf") or args.n_tasks < required),
        "k_runs": args.k_runs, "icc_assumed": args.icc,
        "design_effect": round(deff, 3),
        "effective_sample_size": round(eff_n, 1),
        "naive_sample_size_do_not_use": args.n_tasks * args.k_runs,
        "n_configs": args.n_configs,
        "total_runs": total_runs,
        "cost_per_run_usd": args.cost_per_run,
        "projected_cost_usd": round(projected, 2),
        "budget_usd": args.budget_usd,
        "over_budget": projected > args.budget_usd,
        "paired_discordance_assumed": args.paired_discordance,
    }


def check_refusals(args, p, d):
    """Hard gates. Each corresponds to a failure documented in the literature, not a style preference."""
    refusals = []
    level = p["generality_level"]
    need_key, need_desc = HOLDOUT_REQUIRED[level]
    if args.holdout != need_key:
        refusals.append(
            f"HOLDOUT MISMATCH. The prereg claims generality '{level}', which requires {need_desc} "
            f"(--holdout {need_key}), but --holdout is '{args.holdout}'. Either hold out the right thing, "
            f"or re-register a narrower claim. In the surveyed benchmarks only 1/8 domain-general and 0/2 "
            f"fully-general ones held out the right level, and that is exactly how agents that took "
            f"shortcuts looked general.")
    if args.k_runs < 3 and not args.ack_single_run:
        refusals.append(
            f"K={args.k_runs} runs per task. LLM agents are non-deterministic even at temperature 0 "
            "(hardware, batching and API behaviour all vary), so one run is one sample, not one result. "
            "Use --k-runs 3 at minimum (5-10 is better), or pass --ack-single-run to record that this "
            "experiment CANNOT report variance.")
    if d["target_rate_unreachable"]:
        refusals.append(
            f"IMPOSSIBLE TARGET. A baseline of {args.baseline_rate} with a minimum effect of {p['min_effect']} "
            f"implies a target rate outside [0,1]. Silently clamping it would size the experiment for a "
            f"smaller effect than the one you preregistered, so the power number would be fiction.")
    if d["n_tasks_required_not_estimable"]:
        refusals.append(
            "SAMPLE SIZE NOT ESTIMABLE. The requested effect is not detectable under these assumptions "
            "(zero effective difference). Re-check --baseline-rate and the preregistered min_effect.")
    if args.paired and p["min_effect"] > args.paired_discordance:
        refusals.append(
            f"INFEASIBLE PAIRED DESIGN. min_effect ({p['min_effect']}) exceeds --paired-discordance "
            f"({args.paired_discordance}). The difference between two configs is delta = p01 - p10 and the "
            f"discordance is p01 + p10, so delta <= discordance always. The sizing formula takes the square "
            f"root of (discordance - delta^2) and would be imaginary here — the number it returned before "
            f"this check ({d['n_tasks_required_paired']} pairs) was meaningless. Measure the real "
            f"discordance in a pilot.")
    if d["over_budget"]:
        max_tasks = int(args.budget_usd / (args.k_runs * args.n_configs * args.cost_per_run)) if args.cost_per_run else 0
        refusals.append(
            f"OVER BUDGET. {d['total_runs']} runs x ${args.cost_per_run}/run = ${d['projected_cost_usd']} "
            f"against a ${args.budget_usd} budget. Cut scope deliberately now rather than discovering it "
            f"mid-run and quietly dropping the repeats: at this K and config count the budget affords "
            f"~{max_tasks} tasks. Do NOT solve this by cutting K to 1 — that trades the error bars for "
            f"task count, which is the trade that produced a literature without error bars.")
    return refusals


def write_report(out_dir, p, d, args):
    level = p["generality_level"]
    _, need_desc = HOLDOUT_REQUIRED[level]
    power_badge = "🔴 UNDERPOWERED" if d["underpowered"] else "🟢 powered"
    md = f"""# Experiment design — {p['primary_metric']}

## At a glance
```mermaid
flowchart LR
    PR["prereg {p['prereg_hash']}<br/>effect ≥ {d['min_effect']}"] --> PW["power analysis<br/>need {d['n_tasks_required']} tasks<br/>({'paired' if d['paired'] else 'unpaired'})"]
    PW --> HAVE["planned {d['n_tasks_planned']} tasks<br/>{power_badge}"]
    HAVE --> CL["× K={d['k_runs']} runs<br/>÷ design effect {d['design_effect']}"]
    CL --> EFF["effective N = {d['effective_sample_size']}<br/>(NOT {d['naive_sample_size_do_not_use']})"]
    EFF --> C["{d['total_runs']} runs<br/>≈ ${d['projected_cost_usd']}"]
    HO["holdout: {args.holdout}<br/>({level})"] -.->|"gates the claim"| HAVE
```

| | |
|---|---|
| **Claim level** | `{level}` → must hold out {need_desc} |
| **Holdout provided** | `{args.holdout}` |
| **Tasks needed** ({'paired' if d['paired'] else 'unpaired'}, α=0.05, power=0.80) | **{d['n_tasks_required']}** |
| **Tasks planned** | {d['n_tasks_planned']} — {power_badge} |
| **Runs per task (K)** | {d['k_runs']} |
| **Design effect** (ICC={d['icc_assumed']}) | {d['design_effect']}× |
| **Effective sample size** | **{d['effective_sample_size']}** |
| **Total runs** | {d['total_runs']} across {d['n_configs']} config(s) |
| **Projected cost** | ${d['projected_cost_usd']} of ${d['budget_usd']} budget |

## Why the effective N is smaller than tasks × runs
{d['n_tasks_planned']} tasks × {d['k_runs']} runs is **{d['naive_sample_size_do_not_use']}** rows, but they are not
{d['naive_sample_size_do_not_use']} independent observations: the K runs of one task are correlated (an easy task is
easy every time). With ICC={d['icc_assumed']} the design effect is {d['design_effect']}×, leaving an effective
**{d['effective_sample_size']}**. Treating the rows as independent inflates significance. `analyze-trials`
therefore bootstraps by resampling **tasks**, carrying each task's K runs together.

## Assumptions you are on the hook for
- `baseline_rate = {d['baseline_rate']}` — if the real baseline differs, the required N changes. Measure it in a pilot.
- `ICC = {d['icc_assumed']}` — the run-to-run correlation within a task. Measurable from the pilot; `analyze-trials`
  reports the observed value so this assumption gets checked rather than trusted.
- `paired_discordance = {d['paired_discordance_assumed']}` — the fraction of tasks where the two configs disagree.
  Only used for the paired sizing; a pilot gives the real number.
- `cost_per_run = ${d['cost_per_run_usd']}` — from a pilot, not from a price list; agents make many calls per run.

## What this design cannot buy
- ⛔ Power is not validity. A perfectly powered experiment on a broken task measures nothing —
  `validate-eval-task` is the next gate and it is the one that fails most often.
- ⛔ Statistical significance is not practical significance. That is what `min_effect = {d['min_effect']}` is for.
- ⛔ These numbers assume tasks are independent of each other. Environment-level coupling (shared rate limits,
  shared state) breaks that; `validate-eval-task` item T.4 checks it.

## Next
→ `validate-eval-task` — audit the measuring instrument before spending ${d['projected_cost_usd']}.
"""
    with open(os.path.join(out_dir, "experiment_design.md"), "w") as f:
        f.write(md)


def main():
    ap = argparse.ArgumentParser(description="Size, cost and gate an agent experiment.")
    ap.add_argument("--prereg", required=True, help="Path to prereg.json from frame-research-question.")
    ap.add_argument("--baseline-rate", type=float, required=True,
                    help="Expected success rate of the baseline (0-1), from a pilot.")
    ap.add_argument("--n-tasks", type=int, required=True, help="Tasks available in the eval set.")
    ap.add_argument("--k-runs", type=int, default=5, help="Runs per task per config (default 5).")
    ap.add_argument("--n-configs", type=int, default=2, help="Configs compared, incl. baseline (default 2).")
    ap.add_argument("--cost-per-run", type=float, required=True, help="USD per single task run, from a pilot.")
    ap.add_argument("--budget-usd", type=float, required=True, help="Hard ceiling for the whole experiment.")
    ap.add_argument("--holdout", required=True,
                    choices=["none", "in-distribution", "ood", "unseen-tasks", "unseen-domains"],
                    help="What is actually held out. Must match the prereg's generality level.")
    ap.add_argument("--paired", action="store_true",
                    help="Both configs run on the SAME tasks (recommended: far fewer tasks needed).")
    ap.add_argument("--paired-discordance", type=float, default=0.30,
                    help="Fraction of tasks where the two configs disagree (default 0.30 — measure it).")
    ap.add_argument("--icc", type=float, default=0.5,
                    help="Assumed within-task correlation across runs (default 0.5).")
    ap.add_argument("--ack-single-run", action="store_true",
                    help="Record that K<3 was chosen deliberately and variance CANNOT be reported.")
    ap.add_argument("--out-dir", help="Default: alongside the prereg.")
    args = ap.parse_args()

    if not 0 < args.baseline_rate < 1:
        die(f"--baseline-rate must be strictly between 0 and 1, got {args.baseline_rate}.", 3)
    if not 0 <= args.icc <= 1:
        die(f"--icc must be in [0,1], got {args.icc}.", 3)
    if args.k_runs < 1:
        die(f"--k-runs must be at least 1, got {args.k_runs}.", 3)
    if args.n_tasks < 1:
        die(f"--n-tasks must be at least 1, got {args.n_tasks}.", 3)
    if args.n_configs < 2:
        die(f"--n-configs must be at least 2 (a treatment and a baseline), got {args.n_configs}.", 3)
    if not 0 < args.paired_discordance <= 1:
        die(f"--paired-discordance must be in (0,1], got {args.paired_discordance}.", 3)

    p = load_prereg(args.prereg)
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.prereg))
    d = evaluate_design(args, p)
    refusals = check_refusals(args, p, d)
    if refusals:
        die("REFUSED — fix the design before spending anything:\n\n" +
            "\n\n".join(f"  {i}. {r}" for i, r in enumerate(refusals, 1)), 4)

    d.update({"prereg_hash": p["prereg_hash"], "generality_level": p["generality_level"],
              "holdout": args.holdout, "primary_metric": p["primary_metric"],
              "single_run_acked": bool(args.ack_single_run)})
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "experiment_design.json"), "w") as f:
            json.dump(d, f, indent=2)
        write_report(out_dir, p, d, args)
    except OSError as e:
        die(f"Could not write to {out_dir}: {e}", 2)

    print(f"Design ✅  prereg_hash={p['prereg_hash']}")
    print(f"  tasks needed {d['n_tasks_required']} ({'paired' if d['paired'] else 'unpaired'}) "
          f"· planned {d['n_tasks_planned']} · {'UNDERPOWERED ⚠️' if d['underpowered'] else 'powered'}")
    print(f"  effective N {d['effective_sample_size']} (not {d['naive_sample_size_do_not_use']}; "
          f"design effect {d['design_effect']}x)")
    print(f"  {d['total_runs']} runs ≈ ${d['projected_cost_usd']} of ${d['budget_usd']}")
    if d["underpowered"]:
        eprint(f"\n⚠️  UNDERPOWERED: {d['n_tasks_planned']} tasks vs {d['n_tasks_required']} needed to detect "
               f"an effect of {d['min_effect']} at 80% power. You may run it, but a null result will be "
               "uninformative — record that, do not report it as 'no difference'.")
    print("\nNext: validate-eval-task — audit the task before paying for runs.")


if __name__ == "__main__":
    main()
