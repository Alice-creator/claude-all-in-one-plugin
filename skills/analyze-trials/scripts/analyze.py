#!/usr/bin/env python3
"""analyze-trials: turn trials.jsonl into a defensible claim, or refuse to.

Four things, each of which is a documented way agent results mislead:

  1. CLUSTERED BOOTSTRAP CI. Resamples TASKS with replacement, carrying each task's K runs
     together. N tasks x K runs are not N*K independent observations, and treating them as such
     inflates significance. Bootstrap rather than a normal approximation because success rates are
     bounded in [0,1] and often sit near a boundary, where the Gaussian interval misleads.
  2. PAIRED DIFFERENCE on the shared task set. Pairing removes task-difficulty variance and is the
     cheapest precision available (Miller 2024, Anthropic, calls it "free").
  3. COST-ACCURACY PARETO. Accuracy is buyable: calling a stochastic model more times raises it.
     Kapoor et al. 2024 showed trivial baselines (retry / warming / escalation) Pareto-dominate SOTA
     agent architectures on HumanEval. An accuracy gain without its cost is not a result.
  4. THE PREREG CHECK. Recomputes prereg_hash and compares it to the hash stamped in every trial
     row. A mismatch means the hypothesis, metric, effect size or direction changed after the
     results existed, and the confirmatory claim is refused (HARKing).

Verdicts are deliberately four-valued: SUPPORTED, NOT_SUPPORTED, BELOW_THRESHOLD (real but too
small to act on) and INCONCLUSIVE (underpowered — which is NOT evidence of no effect).

Exit codes: 0 ok · 2 dependency/IO issue · 3 bad/missing input · 4 refused.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical
across scripts); `prereg_hash` and `load_trials` MUST stay identical everywhere they appear.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import unicodedata

try:
    import numpy as np
except ImportError:
    print("numpy is required: pip install numpy", file=sys.stderr)
    sys.exit(2)


MIN_SHARED_TASKS = 30  # measured floor: FPR 0.049 at 30 tasks vs 0.077 at 20 and 0.132 at 5
                       # (tests/measure_bootstrap_calibration.py; nominal 0.05)


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


def load_trials(path):
    rows, bad = [], 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if "task_id" in r and "config_id" in r:
                rows.append(r)
            else:
                bad += 1
    return rows, bad


def cell_counts(rows):
    c = {}
    for r in rows:
        key = (r["task_id"], r["config_id"])
        c[key] = c.get(key, 0) + 1
    return c


def validate_rows(rows):
    """`success` must be a real bool. The string "false" is truthy in Python, so a serialisation slip
    would report 100% success for an agent that failed everything."""
    problems = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r.get("success"), bool):
            problems.append(f"row {i} ({r.get('task_id')}/{r.get('config_id')}): 'success' is "
                            f"{type(r.get('success')).__name__}, not a bool")
        cost = r.get("cost_usd")
        if cost is not None and not isinstance(cost, (int, float)):
            problems.append(f"row {i}: 'cost_usd' is {type(cost).__name__}, not numeric")
    return problems


def per_task_rates(rows, config_id):
    """task_id -> (successes, runs) for one config."""
    acc = {}
    for r in rows:
        if r["config_id"] != config_id:
            continue
        s, n = acc.get(r["task_id"], (0, 0))
        acc[r["task_id"]] = (s + (1 if r.get("success") else 0), n + 1)
    return acc


def bootstrap_ci(task_values, n_boot, seed, alpha=0.05):
    """Percentile CI from resampling TASKS (each carrying its own K runs), not individual runs."""
    if not task_values:
        return None, None, None
    arr = np.asarray(task_values, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(arr.mean()), float(np.percentile(means, 100 * alpha / 2)), float(np.percentile(means, 100 * (1 - alpha / 2)))


def observed_icc(rows, config_id):
    """One-way ANOVA ICC(1) over the binary outcomes grouped by task: how much of the variance is
    between tasks rather than between repeated runs of the same task. This CHECKS the assumption
    design-experiment had to guess."""
    groups = {}
    for r in rows:
        if r["config_id"] == config_id:
            groups.setdefault(r["task_id"], []).append(1.0 if r.get("success") else 0.0)
    groups = {t: v for t, v in groups.items() if len(v) >= 2}
    if len(groups) < 2:
        return None
    sizes = [len(v) for v in groups.values()]
    total = float(sum(sizes))
    # k0 (Snedecor & Cochran), not mean(k): with unbalanced groups mean(k) >= k0 always, which
    # understates ICC — the falsely reassuring direction, since the report tells the reader a
    # higher-than-assumed ICC means the design was weaker than it looked.
    k = (total - sum(x * x for x in sizes) / total) / (len(sizes) - 1)
    grand = np.mean([x for v in groups.values() for x in v])
    n_g = len(groups)
    msb = sum(len(v) * (np.mean(v) - grand) ** 2 for v in groups.values()) / (n_g - 1)
    within_df = sum(len(v) for v in groups.values()) - n_g
    if within_df <= 0:
        return None
    msw = sum(sum((x - np.mean(v)) ** 2 for x in v) for v in groups.values()) / within_df
    denom = msb + (k - 1) * msw
    if denom == 0:
        return None
    return float(max(0.0, min(1.0, (msb - msw) / denom)))


def paired_difference(rows, base_id, other_id, n_boot, seed, alpha=0.05):
    """Per-task rate difference on the SHARED task set, with a clustered bootstrap CI.

    `alpha` is Bonferroni-adjusted by the caller when more than one arm is compared: three null arms
    against one baseline give a family-wise error of ~12% at a nominal 5% per comparison."""
    a, b = per_task_rates(rows, other_id), per_task_rates(rows, base_id)
    shared = sorted(set(a) & set(b))
    if not shared:
        return None
    diffs = [(a[t][0] / a[t][1]) - (b[t][0] / b[t][1]) for t in shared]
    mean, lo, hi = bootstrap_ci(diffs, n_boot, seed, alpha)
    degenerate = bool(lo is not None and hi is not None and hi - lo < 1e-12)
    return {"config_id": other_id, "baseline_id": base_id, "n_shared_tasks": len(shared),
            "n_tasks_dropped_unpaired": len(set(a) | set(b)) - len(shared),
            "mean_difference": round(mean, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
            "mean_difference_raw": mean, "ci_low_raw": lo, "ci_high_raw": hi,
            "alpha": alpha, "ci_degenerate": degenerate,
            "ci_excludes_zero": bool((lo > 0 or hi < 0) and not degenerate)}


def config_summary(rows, config_id, n_boot, seed):
    rates = per_task_rates(rows, config_id)
    vals = [s / n for s, n in rates.values()]
    mean, lo, hi = bootstrap_ci(vals, n_boot, seed)
    sub = [r for r in rows if r["config_id"] == config_id]
    costs = [float(r.get("cost_usd") or 0.0) for r in sub]
    return {"config_id": config_id, "n_tasks": len(rates), "n_runs": len(sub),
            "runs_per_task_min": min((n for _, n in rates.values()), default=0),
            "runs_per_task_max": max((n for _, n in rates.values()), default=0),
            "success_rate": round(mean, 4) if mean is not None else None,
            "ci_low": round(lo, 4) if lo is not None else None,
            "ci_high": round(hi, 4) if hi is not None else None,
            "icc_observed": observed_icc(rows, config_id),
            "total_cost_usd": round(sum(costs), 4),
            "cost_per_task_usd": round(sum(costs) / len(rates), 6) if rates else None,
            "n_errors": sum(1 for r in sub if r.get("error"))}


def pareto_front(summaries):
    """A config is on the front if nothing else is at least as accurate AND at least as cheap."""
    front = []
    for s in summaries:
        acc, cost = s["success_rate"] or 0.0, s["cost_per_task_usd"] or 0.0
        dominated = any((o["success_rate"] or 0.0) >= acc and (o["cost_per_task_usd"] or 0.0) <= cost
                        and ((o["success_rate"] or 0.0) > acc or (o["cost_per_task_usd"] or 0.0) < cost)
                        for o in summaries if o["config_id"] != s["config_id"])
        if not dominated:
            front.append(s["config_id"])
    return front


def verdict_for(diff, p, design):
    """Four-valued on purpose: 'not significant' and 'no effect' are different claims."""
    if diff is None:
        return "NO_SHARED_TASKS", "The two configs share no tasks, so no paired comparison exists."
    flip = 1.0 if p["direction"] == "increase" else -1.0
    signed = diff.get("mean_difference_raw", diff["mean_difference"]) * flip
    lo_r, hi_r = diff.get("ci_low_raw", diff["ci_low"]), diff.get("ci_high_raw", diff["ci_high"])
    # carry the interval in the same orientation as the estimate, or a "decrease" hypothesis prints
    # a positive effect beside a negative interval
    s_lo, s_hi = (lo_r * flip, hi_r * flip) if flip > 0 else (hi_r * flip, lo_r * flip)
    diff["ci_low"], diff["ci_high"] = round(s_lo, 4), round(s_hi, 4)
    diff["mean_difference"] = round(signed, 4)
    min_effect = p["min_effect"]
    underpowered = bool(design and design.get("underpowered"))
    if diff.get("ci_degenerate"):
        return ("INCONCLUSIVE",
                f"The bootstrap interval has zero width on {diff['n_shared_tasks']} shared task(s): every "
                "resample produced the same value, so the interval is an artefact of having too little "
                "data to resample, not a precise estimate.")
    floor = MIN_SHARED_TASKS
    if diff["n_shared_tasks"] < floor:
        return ("INCONCLUSIVE",
                f"Only {diff['n_shared_tasks']} shared task(s), below the floor of {floor}. A percentile "
                "bootstrap is unreliable at this size (measured false-positive rate reaches ~14% at 5 "
                "tasks against a nominal 5%), so no confirmatory verdict is available.")
    if not diff["ci_excludes_zero"]:
        if underpowered:
            return ("INCONCLUSIVE",
                    f"The {int((1 - diff.get('alpha', 0.05)) * 100)}% CI [{diff['ci_low']}, {diff['ci_high']}] includes 0, but the design was "
                    f"UNDERPOWERED ({design.get('n_tasks_planned')} tasks vs {design.get('n_tasks_required')} "
                    f"needed). Absence of evidence here is not evidence of absence — do not report 'no difference'.")
        return ("NOT_SUPPORTED",
                f"The {int((1 - diff.get('alpha', 0.05)) * 100)}% CI [{diff['ci_low']}, {diff['ci_high']}] includes 0 in an adequately powered design. "
                f"The preregistered hypothesis is not supported. Report this; a preregistered null is a finding.")
    if signed < 0:
        return ("CONTRADICTED",
                f"The effect is real but runs OPPOSITE to the hypothesis ({signed:+.4f}, CI "
                f"[{diff['ci_low']}, {diff['ci_high']}]).")
    if signed < min_effect:
        return ("BELOW_THRESHOLD",
                f"The effect is real ({signed:+.4f}, CI [{diff['ci_low']}, {diff['ci_high']}]) but smaller than "
                f"the preregistered minimum worth acting on ({min_effect}). Statistically detectable is not "
                f"practically meaningful.")
    return ("SUPPORTED",
            f"The effect is {signed:+.4f} (95% CI [{diff['ci_low']}, {diff['ci_high']}]), excludes 0, and "
            f"clears the preregistered threshold of {min_effect}.")


def integrity_checks(rows, p, ph, design, base_id, task_validity, exploratory):
    """The checks that decide whether a confirmatory claim is allowed at all."""
    refusals, warnings = [], []
    problems = validate_rows(rows)
    if problems:
        refusals.append(f"MALFORMED ROWS ({len(problems)}):\n      " + "\n      ".join(problems[:8]) +
                        ("\n      ..." if len(problems) > 8 else "") +
                        "\n    A non-bool 'success' cannot be counted; coercing it would invent a rate.")
    gate = (task_validity or {}).get("gate")
    if task_validity is None:
        refusals.append("NO VALIDITY AUDIT. --task-validity is required: without it this analysis cannot "
                        "know whether the eval task measures the capability at all. 7/10 audited agent "
                        "benchmarks violate task validity. Pass the audit, or --exploratory to record "
                        "explicitly that this is not a confirmatory result.")
    elif gate != "PASS":
        refusals.append(f"VALIDITY GATE IS {gate}, NOT PASS. The measuring instrument failed its audit, so "
                        "these numbers describe the instrument as much as the agent. Fix the task and "
                        "re-run, or pass --exploratory.")
    n_unstamped = sum(1 for r in rows if not r.get("prereg_hash"))
    if n_unstamped:
        refusals.append(f"{n_unstamped} of {len(rows)} trial row(s) carry NO prereg_hash. Unstamped rows are "
                        "invisible to the HARKing check, so a mix of stamped and unstamped rows would pass "
                        "silently while half the data came from a different hypothesis. Re-run through the "
                        "scaffolded runner, or use --exploratory.")
    stamped = {r.get("prereg_hash") for r in rows if r.get("prereg_hash")}
    if stamped and stamped != {ph}:
        refusals.append(
            f"PREREG MISMATCH. The trials were stamped with {sorted(stamped)} but prereg.json now hashes to "
            f"{ph}. The hypothesis, primary metric, minimum effect or direction changed after these results "
            f"existed. That is HARKing, and the confirmatory claim is refused. Either analyse under the "
            f"ORIGINAL prereg, or report this explicitly as an exploratory (not confirmatory) analysis.")
    configs = sorted({r["config_id"] for r in rows})
    if base_id not in configs:
        refusals.append(f"Baseline config '{base_id}' is absent from the trials (present: {configs}). "
                        "There is nothing to compare against.")
    counts = {}
    for r in rows:
        counts[(r["task_id"], r["config_id"])] = counts.get((r["task_id"], r["config_id"]), 0) + 1
    if counts:
        k_seen = sorted(set(counts.values()))
        if len(k_seen) > 1:
            warnings.append(f"Unequal runs per (task, config) cell: {k_seen}. A truncated grid is not missing "
                            "at random — a budget cut-off drops whatever ran last. Say so, or re-run to fill it.")
        n_thin = sum(1 for v in counts.values() if v < 3)
        if min(k_seen) < 3:
            warnings.append(f"{n_thin} cell(s) have fewer than 3 runs (min K={min(k_seen)}). Below 3, "
                            "run-to-run variance cannot be separated "
                            "from the effect, and LLM agents are non-deterministic even at temperature 0.")
    models = {r.get("model_version") for r in rows if r.get("model_version")}
    if len(models) > 1:
        warnings.append(f"More than one model_version in one dataset: {sorted(models)}. Model version is a "
                        "confound; either split the analysis or state that the arms are not comparable.")
    n_err = sum(1 for r in rows if r.get("error"))
    if n_err:
        warnings.append(f"{n_err} run(s) recorded an error and count as failures. If those were infrastructure "
                        "faults rather than agent failures, they bias the rate DOWN — check before reporting.")
    if exploratory and refusals:
        warnings.extend(f"[downgraded to exploratory] {r}" for r in refusals)
        refusals = []
    return refusals, warnings


def _config_rows(summaries, front):
    out = []
    for s in summaries:
        star = " ⭐" if s["config_id"] in front else ""
        cost = "—" if s["cost_per_task_usd"] is None else f"${s['cost_per_task_usd']:.4f}"
        icc = "—" if s["icc_observed"] is None else f"{s['icc_observed']:.2f}"
        ci = f"[{s['ci_low']:.3f}, {s['ci_high']:.3f}]"
        out.append(f"| `{s['config_id']}`{star} | {s['n_tasks']} | {s['n_runs']} | "
                   f"**{s['success_rate']:.3f}** | {ci} | {cost} | {icc} |")
    return "\n".join(out)


def _diff_lines(diffs, verdicts, badge):
    out = []
    for d, v in zip(diffs, verdicts):
        if not d:
            continue
        dropped = (f", {d['n_tasks_dropped_unpaired']} dropped as unpaired"
                   if d["n_tasks_dropped_unpaired"] else "")
        out.append(f"- `{d['config_id']}` − `{d['baseline_id']}` = **{d['mean_difference']:+.4f}** "
                   f"(95% CI [{d['ci_low']:+.4f}, {d['ci_high']:+.4f}], {d['n_shared_tasks']} shared "
                   f"tasks{dropped}) → {badge.get(v['verdict'], v['verdict'])}")
    return "\n".join(out)


def write_report(out_dir, p, summaries, diffs, front, verdicts, warnings, ph, design):
    badge = {"SUPPORTED": "🟢 SUPPORTED", "NOT_SUPPORTED": "🔴 NOT SUPPORTED",
             "BELOW_THRESHOLD": "🟡 REAL BUT BELOW THRESHOLD", "INCONCLUSIVE": "🟡 INCONCLUSIVE",
             "CONTRADICTED": "🔴 CONTRADICTED", "NO_SHARED_TASKS": "⚠️ NO PAIRED DATA"}
    head = verdicts[0] if verdicts else {"verdict": "NO_SHARED_TASKS", "explanation": "no comparison",
                                         "mean_difference": None}
    head_diff = "—" if head.get("mean_difference") is None else f"{head['mean_difference']:+.4f}"
    caveats = "\n".join(f"- ⚠️ {w}" for w in warnings) or "- none flagged"
    md = f"""# Analysis — {p['primary_metric']}

## At a glance
```mermaid
flowchart LR
    T["trials.jsonl"] --> CB["clustered bootstrap<br/>resample TASKS, carry K runs"]
    CB --> PD["paired difference<br/>{head_diff}"]
    PD --> V["{badge.get(head['verdict'], head['verdict'])}"]
    T --> PA["cost–accuracy Pareto<br/>front: {', '.join(front) or '—'}"]
    PR["prereg {ph}"] -.->|"hash checked<br/>on every row"| V
```

**Verdict: {badge.get(head['verdict'], head['verdict'])}** — {head['explanation']}

## Per-config
| Config | tasks | runs | success rate | 95% CI (clustered) | cost/task | observed ICC |
|---|--:|--:|--:|---|--:|--:|
{_config_rows(summaries, front)}

⭐ = on the cost–accuracy Pareto front. A config that is off the front is beaten on **both** axes:
being more accurate at any price is not a result, because accuracy is purchasable by re-calling a
stochastic model.

**Observed ICC** is the run-to-run correlation within a task, measured. Compare it against the value
`design-experiment` had to assume: if it is higher than assumed, the effective sample size is smaller
than planned and the design was more underpowered than it looked.

## Paired differences vs baseline
{_diff_lines(diffs, verdicts, badge) or "- no paired comparison available"}

Read the interval before the point estimate. Overlapping intervals are not a difference, however
large the gap between the means looks.

## Caveats attached to this analysis
{caveats}

## What these numbers are not
- ⛔ **Not deployment performance.** This is an offline score on a held-out set, in the same sense that
  `evaluate-model` and `evaluate-detection` refuse to call an offline metric a production metric.
- ⛔ **Not a validity certificate.** `validate-eval-task` cleared the *known* failure modes; a shortcut
  nobody has thought of yet would show up here as a clean, confident, wrong number.
- ⛔ **Not generalisable past the holdout level** recorded in the design (`{design.get('holdout') or 'unspecified'}`).
- ⛔ Secondary metrics remain **exploratory** regardless of how they came out. Only the preregistered
  primary metric carries a confirmatory claim.

## Next
→ `diagnose-failures` — a score says the agent fails, not where. That is where the insight is.
"""
    with open(os.path.join(out_dir, "analysis_report.md"), "w") as f:
        f.write(md)


def main():
    ap = argparse.ArgumentParser(description="Clustered-bootstrap analysis of agent trials.")
    ap.add_argument("--trials", required=True, help="trials.jsonl from the scaffolded runner.")
    ap.add_argument("--prereg", required=True)
    ap.add_argument("--design", help="experiment_design.json (enables the powered/underpowered verdict).")
    ap.add_argument("--baseline-config", help="Baseline config id. Default: from the bundle manifest or 'baseline'.")
    ap.add_argument("--manifest", help="trials_manifest.json, to read the baseline config id.")
    ap.add_argument("--task-validity", help="task_validity.json. Required unless --exploratory.")
    ap.add_argument("--exploratory", action="store_true",
                    help="Record that this is NOT a confirmatory analysis; downgrades refusals to "
                         "warnings and stamps confirmatory:false into the sidecar and the report.")
    ap.add_argument("--n-boot", type=int, default=10000, help="Bootstrap resamples (default 10000).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stability-seeds", type=int, default=3,
                    help="Re-run the bootstrap under this many seeds and refuse a verdict that is not "
                         "stable across them (default 3). Kills seed-shopping.")
    ap.add_argument("--out-dir", help="Default: next to trials.jsonl.")
    args = ap.parse_args()

    for path in (args.trials, args.prereg):
        if not os.path.exists(path):
            die(f"Missing {path}.", 3)
    with open(args.prereg) as f:
        p = json.load(f)
    ph = prereg_hash(p)
    design = None
    if args.design and os.path.exists(args.design):
        with open(args.design) as f:
            design = json.load(f)
    base_id = args.baseline_config
    if not base_id and args.manifest and os.path.exists(args.manifest):
        with open(args.manifest) as f:
            base_id = json.load(f).get("baseline_config_id")
    base_id = base_id or "baseline"

    rows, bad = load_trials(args.trials)
    if not rows:
        die(f"No usable rows in {args.trials} ({bad} unparseable).", 3)

    task_validity = None
    if args.task_validity:
        if not os.path.exists(args.task_validity):
            die(f"No task_validity.json at {args.task_validity}.", 3)
        with open(args.task_validity) as f:
            task_validity = json.load(f)
    refusals, warnings = integrity_checks(rows, p, ph, design, base_id, task_validity, args.exploratory)
    if bad:
        warnings.append(f"{bad} line(s) in trials.jsonl could not be parsed and were skipped.")
    if refusals:
        die("REFUSED — this analysis cannot carry a confirmatory claim:\n\n  - " +
            "\n\n  - ".join(refusals), 4)

    configs = sorted({r["config_id"] for r in rows})
    summaries = [config_summary(rows, c, args.n_boot, args.seed + i) for i, c in enumerate(configs)]
    front = pareto_front(summaries)
    others = [c for c in configs if c != base_id]
    alpha = 0.05 / max(1, len(others))  # Bonferroni: family-wise error reaches ~12% at 3 arms otherwise
    if len(others) > 1:
        warnings.append(f"{len(others)} arms compared against the baseline; the interval is Bonferroni-"
                        f"adjusted to alpha={alpha:.4f} per comparison to hold the family-wise error at 5%.")
    diffs = [paired_difference(rows, base_id, c, args.n_boot, args.seed, alpha) for c in others]
    verdicts = []
    for d in diffs:
        v, why = verdict_for(d, p, design)
        stable, seen = True, {v}
        if d and args.stability_seeds > 1:
            for extra in range(1, args.stability_seeds):
                alt = paired_difference(rows, base_id, d["config_id"], args.n_boot,
                                        args.seed + 1000 * extra, alpha)
                seen.add(verdict_for(alt, p, design)[0])
            stable = len(seen) == 1
        if not stable:
            warnings.append(f"[{d['config_id']}] VERDICT NOT STABLE across bootstrap seeds: {sorted(seen)}. "
                            "The result sits on the decision boundary, so which seed you happen to use "
                            "decides the conclusion. Reported as INCONCLUSIVE.")
            v, why = "INCONCLUSIVE", (f"The verdict changed across bootstrap seeds ({sorted(seen)}), so it "
                                      "is an artefact of resampling noise rather than a finding.")
        verdicts.append({"config_id": d["config_id"] if d else None, "verdict": v, "explanation": why,
                         "mean_difference": d["mean_difference"] if d else None,
                         "seed_stable": stable, "verdicts_across_seeds": sorted(seen)})

    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.trials))
    with open(args.trials, "rb") as f:
        trials_digest = hashlib.sha256(f.read()).hexdigest()[:16]
    sidecar = {"confirmatory": not args.exploratory and not refusals,
               "exploratory": bool(args.exploratory),
               "task_validity_gate": (task_validity or {}).get("gate"),
               "trials_sha256": trials_digest, "alpha": alpha,
               "all_rows_prereg_stamped": all(r.get("prereg_hash") for r in rows),
               "order_seed_recorded": all(r.get("order_seed") is not None for r in rows),
               "model_versions": sorted({r.get("model_version") for r in rows if r.get("model_version")}),
               "min_runs_per_cell": min(cell_counts(rows).values()) if rows else None,
               "prereg_hash": ph, "primary_metric": p["primary_metric"], "min_effect": p["min_effect"],
               "direction": p["direction"], "baseline_config_id": base_id, "n_boot": args.n_boot,
               "seed": args.seed, "configs": summaries, "pareto_front": front,
               "paired_differences": [d for d in diffs if d], "verdicts": verdicts,
               "warnings": warnings, "n_rows": len(rows), "n_unparseable": bad,
               "holdout": (design or {}).get("holdout")}
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "analysis.json"), "w") as f:
            json.dump(sidecar, f, indent=2)
        write_report(out_dir, p, summaries, diffs, front, verdicts, warnings, ph, design or {})
    except OSError as e:
        die(f"Could not write to {out_dir}: {e}", 2)

    print(f"Analysis ✅  {os.path.join(out_dir, 'analysis_report.md')}")
    for s in summaries:
        star = " ⭐pareto" if s["config_id"] in front else ""
        print(f"  {s['config_id']:<14} {s['success_rate']:.3f}  CI [{s['ci_low']:.3f}, {s['ci_high']:.3f}]  "
              f"ICC={s['icc_observed'] if s['icc_observed'] is None else round(s['icc_observed'], 2)}{star}")
    for v in verdicts:
        print(f"\n  {v['config_id']}: {v['verdict']} — {v['explanation']}")
    for w in warnings:
        eprint(f"\n  ⚠️ {w}")
    print("\nNext: diagnose-failures — the score says it fails, not where.")


if __name__ == "__main__":
    main()
