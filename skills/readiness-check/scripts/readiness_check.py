#!/usr/bin/env python3
"""Pre-deployment readiness audit of a pipeline directory — claude-all-in-one-plugin.

Inspects the artifacts the modeling pipeline wrote (split_summary.json,
baseline_metric.json, tuned_metric.json, experiments.jsonl, evaluation_report.md)
and scores them against an ML Test Score-style checklist (Breck et al. 2017),
writing readiness_report.md. READ-ONLY: it audits evidence-of-process on disk;
it re-runs and re-judges nothing, and it cannot verify serving infra or live
monitoring (those are marked NOT-AUTO-CHECKABLE). Pure stdlib — no pandas/sklearn.
"""
import argparse
import glob
import json
import math
import os


def find_one(root, name):
    """Shallowest match for `name` anywhere under root (handles non-default/nested out-dirs).
    Ties broken by most-recent mtime so the choice is deterministic, not filesystem-order."""
    hits = glob.glob(os.path.join(root, "**", name), recursive=True)
    return min(hits, key=lambda p: (p.count(os.sep), -os.path.getmtime(p))) if hits else None


def read_json(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_jsonl(path):
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def file_has(path, needle):
    if not path or not os.path.exists(path):
        return False
    with open(path, errors="ignore") as f:
        return needle.lower() in f.read().lower()


def finite(x):
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


# Each check has a FIXED weight (auto-checkable=1.0, manual-evidence=0.5) independent of its
# outcome, so the denominator is constant. Earned = full weight on PASS, half on PARTIAL, 0 on FAIL.
def weight(level):
    return 1.0 if level == "auto" else 0.5


def pts(status, level):
    w = weight(level)
    return w if status == "PASS" else (0.5 * w if status == "PARTIAL" else 0.0)


def main():
    p = argparse.ArgumentParser(description="Pre-deployment readiness audit (offline, read-only).")
    p.add_argument("--pipeline-dir", required=True, help="the <name>_splits/ tree to audit")
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()
    root = args.pipeline_dir
    if not os.path.isdir(root):
        raise SystemExit(f"--pipeline-dir not found: {root}")
    args.out_dir = args.out_dir or os.path.join(root, "readiness-check")
    os.makedirs(args.out_dir, exist_ok=True)

    split = read_json(find_one(root, "split_summary.json"))
    base = read_json(find_one(root, "baseline_metric.json"))
    tuned = read_json(find_one(root, "tuned_metric.json"))
    exps = read_jsonl(find_one(root, "experiments.jsonl"))
    eval_report = find_one(root, "evaluation_report.md")
    last_run = exps[-1] if exps else None

    checks = []  # (section, name, status, level, evidence)

    # Every check is emitted in EVERY run (FAIL/PARTIAL when its artifact is absent) so the
    # auto-checkable denominator is constant and offline-readiness fractions are comparable across runs.

    # ---- Section 1 — Features & Data ----
    if split:
        clean = split.get("no_row_overlap") and split.get("group_overlap") in (None, 0)
        checks.append(("Features & Data", "Leakage-safe split (no row/entity overlap)",
                       "PASS" if clean else "FAIL", "auto",
                       f"split_summary.json: no_row_overlap={split.get('no_row_overlap')}, group_overlap={split.get('group_overlap')}"))
        if "duplicates_in_source" not in split:
            checks.append(("Features & Data", "Duplicate rows handled", "PARTIAL", "manual",
                           "duplicate count not recorded in split_summary.json — cannot confirm"))
        else:
            dup_ok = split["duplicates_in_source"] == 0 or split.get("dropped_duplicates")
            checks.append(("Features & Data", "Duplicate rows handled", "PASS" if dup_ok else "PARTIAL", "manual",
                           f"{split['duplicates_in_source']} dups, dropped={split.get('dropped_duplicates')}"))
    else:
        checks.append(("Features & Data", "Leakage-safe split (no row/entity overlap)", "FAIL", "auto",
                       "split_summary.json not found — run split-dataset"))
        checks.append(("Features & Data", "Duplicate rows handled", "FAIL", "manual",
                       "split_summary.json not found — cannot audit duplicates"))

    # ---- Section 2 — Model Development ----
    checks.append(("Model Development", "Baseline ('number to beat') established",
                   "PASS" if base else "FAIL", "auto",
                   f"baseline_metric.json: {base.get('primary')}={base.get('value')}" if base
                   else "baseline_metric.json not found — run baseline"))
    # 'Tuned beats baseline' is ALWAYS emitted (was previously skipped when baseline was missing)
    if base and tuned:
        same = base.get("primary") == tuned.get("primary") and base.get("eval_on") == tuned.get("eval_on")
        bv, tv = base.get("value"), tuned.get("value")
        if not same:
            st, ev = "PARTIAL", "baseline vs tuned not comparable (primary/eval_on differ — e.g. measured on different splits)"
        elif not (finite(bv) and finite(tv)):
            st, ev = "PARTIAL", "a primary metric is undefined (e.g. MAPE on zero targets) — not comparable"
        else:
            beats = (tv < bv) if base.get("lower_is_better") else (tv > bv)
            st = "PASS" if beats else "PARTIAL"
            ev = f"tuned {tuned.get('primary')}={tv} vs baseline {bv} ({'lower' if base.get('lower_is_better') else 'higher'} better) → {'beats' if beats else 'does NOT beat'}"
    elif base and not tuned:
        st, ev = "PARTIAL", "baseline established but no tuned_metric.json — nothing tuned to compare"
    elif tuned and not base:
        st, ev = "PARTIAL", "tuned model present but no baseline to compare against — run baseline"
    else:
        st, ev = "FAIL", "neither baseline nor tuned model present — run baseline + train-tune"
    checks.append(("Model Development", "Tuned model beats the baseline", st, "auto", ev))

    if last_run and last_run.get("best_params") and last_run.get("n_iter"):
        checks.append(("Model Development", "Hyperparameters tuned (recorded search)", "PASS", "auto",
                       f"experiments.jsonl: n_iter={last_run.get('n_iter')}, cv={last_run.get('cv')}, scoring={last_run.get('scoring')}"))
    else:
        checks.append(("Model Development", "Hyperparameters tuned (recorded search)", "FAIL", "auto",
                       "no experiments.jsonl run with best_params — run train-tune"))

    # the slice header is template boilerplate; require the marker evaluate-model writes ONLY
    # when a real worst-slice table was produced, not the bare "## Slice-based error analysis" header
    if eval_report and file_has(eval_report, "worst-performing slices"):
        checks.append(("Model Development", "Evaluated with slice/error analysis", "PASS", "manual",
                       f"evaluation_report.md has a worst-slice table ({os.path.relpath(eval_report, root)})"))
    elif eval_report:
        checks.append(("Model Development", "Evaluated with slice/error analysis", "PARTIAL", "manual",
                       "evaluation_report.md present but produced no slices (small eval set / no feature columns)"))
    else:
        checks.append(("Model Development", "Evaluated with slice/error analysis", "FAIL", "manual",
                       "no evaluation_report.md — run evaluate-model"))

    # ---- Section 3 — ML Infrastructure ----
    if last_run:
        has = last_run.get("seed") is not None and last_run.get("dataset_sha256") and last_run.get("versions")
        ev = (f"latest run {last_run.get('run_id')}: seed={last_run.get('seed')}, "
              f"dataset_sha256={last_run.get('dataset_sha256')}, versions logged — "
              f"metadata PRESENT, not a re-verification that training is deterministic")
        checks.append(("ML Infrastructure", "Reproducibility metadata (seed + data hash + versions)",
                       "PASS" if has else "PARTIAL", "auto", ev))
    else:
        checks.append(("ML Infrastructure", "Reproducibility metadata (seed + data hash + versions)", "FAIL", "auto",
                       "no experiments.jsonl — run train-tune"))

    # Test-holdout: PASS only on POSITIVE evidence (recorded eval_on, all val). A recorded
    # eval_on=test is reported PARTIAL — the tool cannot tell a one-time terminal estimate
    # (legitimate) from selecting on test (contamination), so it asks for manual review
    # rather than either a false PASS or an unfair FAIL of the correct terminal workflow.
    recorded = [a.get("eval_on") for a in ([base, tuned] + exps) if a and a.get("eval_on") is not None]
    if any(e == "test" for e in recorded):
        checks.append(("ML Infrastructure", "Test set held out from tuning/selection", "PARTIAL", "auto",
                       "a selection artifact recorded eval_on=test — OK only if it's the one-time TERMINAL estimate, NOT model selection; verify manually"))
    elif not recorded:
        checks.append(("ML Infrastructure", "Test set held out from tuning/selection", "PARTIAL", "auto",
                       "no eval_on recorded in any artifact — cannot confirm test was untouched"))
    else:
        checks.append(("ML Infrastructure", "Test set held out from tuning/selection", "PASS", "auto",
                       "baseline/tuned/experiments all selected on val — test untouched by selection"))

    # ---- Section 4 — Monitoring: unobservable offline ----
    monitoring_na = [
        "Live input invariants / data validation on serving traffic",
        "Training-serving skew", "Model staleness in production",
        "Numerical stability in serving", "Compute-performance regression",
        "Prediction-quality regression on live labels", "Dependency-change alerts",
    ]

    SECTIONS = ["Features & Data", "Model Development", "ML Infrastructure"]
    sec_pts = {s: sum(pts(st, lv) for (sec, _, st, lv, _) in checks if sec == s) for s in SECTIONS}
    sec_max = {s: sum(weight(lv) for (sec, _, st, lv, _) in checks if sec == s) for s in SECTIONS}
    offline_pts = sum(sec_pts.values())
    offline_max = sum(sec_max.values())
    frac = offline_pts / offline_max if offline_max else 0.0
    # NON-CANONICAL indicative label on the fraction (the paper's absolute bands don't apply to a subset)
    label = "strong (offline)" if frac >= 0.8 else "partial (offline)" if frac >= 0.5 else "weak (offline)"
    n_fail = sum(1 for c in checks if c[2] == "FAIL")
    n_partial = sum(1 for c in checks if c[2] == "PARTIAL")

    def sec_node(s, i):
        return f'    S{i}["{s}<br/>{sec_pts[s]:.1f} / {sec_max[s]:.1f} auto"] --> SCORE'

    mermaid = "\n".join([
        "```mermaid", "flowchart LR",
        *[sec_node(s, i) for i, s in enumerate(SECTIONS)],
        f'    SCORE["offline-readiness<br/>{offline_pts:.1f} / {offline_max:.1f}<br/>{label}"]',
        '    MON["Monitoring<br/>deferred to production<br/>(unobservable offline)"]',
        "```",
    ])

    def table(section):
        rows = [c for c in checks if c[0] == section]
        out = "| check | status | evidence | pts |\n|---|---|---|---|\n"
        for (_, name, st, lv, ev) in rows:
            out += f"| {name} | {st} | {ev} | {pts(st, lv):.1f} |\n"
        return out

    gaps = [f"- **{name}** — {ev}" for (_, name, st, lv, ev) in checks if st in ("FAIL", "PARTIAL")]
    na_list = "\n".join(f"- {m} — needs live serving telemetry / production labels" for m in monitoring_na)

    report = f"""# Readiness audit — `{os.path.basename(os.path.abspath(root))}`

> Read-only audit of pipeline artifacts against an ML Test Score-style checklist (Breck et al. 2017). It checks **evidence that a step was done**, not whether the model is *good*. It re-runs nothing.

## At a glance
{mermaid}

**Offline-readiness: {offline_pts:.1f} / {offline_max:.1f} auto-checkable points — {label}.** {n_fail} FAIL, {n_partial} PARTIAL.

> The strict ML Test Score (min over all 4 sections) is **0.0** offline, because Monitoring is unobservable without production telemetry — that is expected for an offline tool, not a pipeline failure. The load-bearing number above is the fraction of the *offline-auto-checkable* checks passed; its label is **indicative, non-canonical** (the paper's interpretation bands were calibrated on the full rubric, not this subset).

## Features & Data
{table("Features & Data")}
## Model Development
{table("Model Development")}
## ML Infrastructure
{table("ML Infrastructure")}
## Gaps to close
{chr(10).join(gaps) if gaps else "- none — all auto-checkable items passed"}

## Not auto-checkable (manual sign-off required)
Monitoring (Section 4) is entirely deferred — every check needs live serving telemetry and/or production labels:
{na_list}

Also not offline-checkable: serving infra (canary, rollback, integration tests, latency), fairness/inclusion, and spec code-review.

## What this audit CANNOT tell you
- It does **not** prove the model is accurate or production-ready — a high offline score is **not** a deploy approval.
- It **trusts the recorded artifacts** (seed/hash/eval_on) as-is; it cannot re-verify that training was actually deterministic, nor that the on-disk splits still match the recorded hash.
- It cannot measure online/business performance, serving health, or drift — for the offline drift proxy, run `check-drift`. Concept drift P(y|X) needs production labels and is unverifiable by any offline tool here.
"""
    with open(os.path.join(args.out_dir, "readiness_report.md"), "w") as f:
        f.write(report)

    print(f"offline-readiness: {offline_pts:.1f}/{offline_max:.1f} ({label}) | {n_fail} FAIL, {n_partial} PARTIAL")
    for (sec, name, st, lv, _) in checks:
        if st in ("FAIL", "PARTIAL"):
            print(f"  {st:7s} {name}")
    print(f"  written → {args.out_dir}/readiness_report.md")


if __name__ == "__main__":
    main()
