#!/usr/bin/env python3
"""Measure — not assert — the calibration of analyze-trials' clustered bootstrap.

The pipeline documents a false-positive rate and a clustering penalty. Those numbers must come from
a recorded, re-runnable measurement with stated parameters, not from one lucky simulation. This
script IS the source of both numbers; the SKILL.md quotes what it prints.

Run: python3 tests/measure_bootstrap_calibration.py [--sims 2000]
"""
import argparse
import importlib.util
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "an", os.path.join(ROOT, "skills/analyze-trials/scripts/analyze.py"))
an = importlib.util.module_from_spec(spec)
spec.loader.exec_module(an)


def synth(n_tasks, k, base_p, lift, seed, spread=0.8):
    """Beta-distributed per-task difficulty induces realistic within-task correlation."""
    rng = random.Random(seed)
    rows = []
    for t in range(n_tasks):
        d = rng.betavariate(2, 2)
        for cfg, shift in (("baseline", 0.0), ("treatment", lift)):
            p = min(0.98, max(0.02, base_p + (d - 0.5) * spread + shift))
            for ri in range(k):
                rows.append({"task_id": f"t{t}", "config_id": cfg, "run_idx": ri,
                             "success": rng.random() < p})
    return rows


def rate(n_tasks, k, lift, sims, n_boot, seed0):
    hits = 0
    for s in range(sims):
        rows = synth(n_tasks, k, 0.40, lift, seed0 + s)
        d = an.paired_difference(rows, "baseline", "treatment", n_boot, s)
        hits += bool(d and d["ci_excludes_zero"])
    return hits / sims


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--n-boot", type=int, default=1000)
    a = ap.parse_args()

    print(f"Parameters: sims={a.sims}, n_boot={a.n_boot}, base_rate=0.40, beta(2,2) task difficulty, "
          f"spread=0.8, nominal alpha=0.05\n")

    print("FALSE-POSITIVE RATE under a true null (lift=0). Nominal 0.05.")
    print(f"  {'n_tasks':>8} {'K':>3} {'FPR':>7}   note")
    for n, k in ((5, 3), (10, 3), (20, 5), (50, 5), (100, 5)):
        fpr = rate(n, k, 0.0, a.sims, a.n_boot, 10_000)
        note = "BELOW the MIN_SHARED_TASKS floor — refused" if n < an.MIN_SHARED_TASKS else ""
        print(f"  {n:>8} {k:>3} {fpr:>7.3f}   {note}")

    print("\nPOWER at a true lift of 0.10.")
    for n, k in ((20, 5), (50, 5), (100, 5)):
        print(f"  {n:>8} {k:>3} {rate(n, k, 0.10, max(200, a.sims // 4), a.n_boot, 50_000):>7.3f}")

    print("\nCLUSTERING PENALTY: clustered CI width / naive per-run CI width.")
    print("  Theory: sqrt(1 + (K-1)*ICC). Depends on BOTH K and the ICC, so a single number is not a "
          "property of the method.")
    for k in (3, 5, 10):
        rows = synth(200, k, 0.40, 0.0, 99)
        aa, bb = an.per_task_rates(rows, "treatment"), an.per_task_rates(rows, "baseline")
        shared = sorted(set(aa) & set(bb))
        clustered = [(aa[t][0] / aa[t][1]) - (bb[t][0] / bb[t][1]) for t in shared]
        _, lo, hi = an.bootstrap_ci(clustered, 4000, 1)
        flat = []
        for t in shared:
            flat += [1.0] * aa[t][0] + [0.0] * (aa[t][1] - aa[t][0])
        _, lof, hif = an.bootstrap_ci(flat, 4000, 1)
        icc = an.observed_icc(rows, "treatment")
        print(f"  K={k:>2}  observed ICC={icc:.2f}  clustered/naive = {(hi - lo) / (hif - lof):.2f}x")

    print("\nRead this as: the percentile bootstrap is approximately calibrated at and above the "
          f"MIN_SHARED_TASKS={an.MIN_SHARED_TASKS} floor, and materially anti-conservative below it, "
          "which is why the floor is enforced rather than documented.")


if __name__ == "__main__":
    main()
