#!/usr/bin/env python3
"""write-findings: assemble the report, with the headline claim taken from the ANALYSIS, not the author.

Pineau's survey of 50 RL papers found significance testing in 5% of them, and plots with shaded
regions that never said whether the shading was a confidence interval or a standard deviation. The
NeurIPS reproducibility checklist exists because of that. This script fills that checklist from the
actual sidecars rather than from memory, and refuses three specific dishonesties:

  1. It will not write a positive headline when analysis.json says NOT_SUPPORTED, INCONCLUSIVE,
     BELOW_THRESHOLD or CONTRADICTED. A preregistered null is a finding and gets reported as one.
  2. It will not present an unvalidated failure taxonomy (single annotator, or kappa below the
     threshold) as a result — it renders it as an observation and labels it.
  3. It refuses entirely if the prereg hash disagrees across the sidecars, because that means the
     hypothesis moved after the results existed.

Every report carries a "What this does NOT show" section, auto-populated from the holdout level, the
validity items answered NO, the analysis warnings and the exploratory metrics. That section is not
decoration: a benchmark score is not deployment performance, and this pipeline says so in the same
place its tabular and vision siblings do.

Exit codes: 0 ok · 2 IO issue · 3 bad/missing input · 4 refused.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical
across scripts); `prereg_hash` MUST stay identical everywhere it appears.
"""
import argparse
import hashlib
import json
import os
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


def load(path, required=True, what=""):
    if not path or not os.path.exists(path):
        if required:
            die(f"Missing {what or path}. write-findings assembles from the sidecars; it does not "
                "reconstruct them from prose.", 3)
        return None
    with open(path) as f:
        return json.load(f)


VERDICT_HEADLINE = {
    "SUPPORTED": ("🟢", "The preregistered hypothesis is SUPPORTED."),
    "NOT_SUPPORTED": ("🔴", "The preregistered hypothesis is NOT supported."),
    "BELOW_THRESHOLD": ("🟡", "A real effect was detected, but it is BELOW the threshold worth acting on."),
    "INCONCLUSIVE": ("🟡", "The result is INCONCLUSIVE — the design was underpowered."),
    "CONTRADICTED": ("🔴", "The effect runs OPPOSITE to the preregistered hypothesis."),
    "NO_SHARED_TASKS": ("⚠️", "No paired comparison was possible."),
}


def repro_rows(p, d, tv, an, man, fx):
    """The reproducibility checklist, filled from sidecars. A blank is reported as a blank."""
    def mark(ok, value):
        return ("✅" if ok else "❌", value if value not in (None, "", []) else "_not recorded_")
    k_runs = (d or {}).get("k_runs")
    models = (man or {}).get("model_version")
    items = [
        ("Preregistered hypothesis + falsification criterion", *mark(True, p["hypothesis"])),
        ("Primary metric fixed before results", *mark(True, f"`{p['primary_metric']}`")),
        ("Minimum effect size stated in advance", *mark(True, p["min_effect"])),
        ("prereg_hash present on every trial row", *mark(an.get("all_rows_prereg_stamped") is True,
                                                          f"`{an.get('prereg_hash')}` on all rows"
                                                          if an.get("all_rows_prereg_stamped") else None)),
        ("Eval-task validity audited (ABC)", *mark((tv or {}).get("gate") == "PASS", f"gate = {(tv or {}).get('gate')}")),
        ("Trivial-agent baseline reported (R.13)", *mark(bool((tv or {}).get("trivial_agents")),
                                                        ", ".join(f"{a} {v['rate']:.1%}" for a, v in
                                                                  sorted(((tv or {}).get("trivial_agents") or {}).items())))),
        ("Oracle solve rate reported", *mark((tv or {}).get("oracle_solve_rate") is not None,
                                             (tv or {}).get("oracle_solve_rate"))),
        ("Exact model version incl. date", *mark(len(an.get("model_versions") or []) == 1,
                                                 ", ".join(f"`{m}`" for m in (an.get("model_versions") or [])) or None)),
        ("Runs per cell ≥ 3 (observed, not planned)", *mark(bool(an.get("min_runs_per_cell")) and an.get("min_runs_per_cell") >= 3,
                                                            f"min {an.get('min_runs_per_cell')} observed (planned {k_runs})")),
        ("Confidence intervals reported", *mark(bool(an.get("configs")), "clustered bootstrap, "
                                                f"{an.get('n_boot')} resamples, seed {an.get('seed')}")),
        ("Clustering respected (resampled tasks, not runs)", *mark(True, "yes — tasks resampled with their K runs")),
        ("Cost reported alongside accuracy", *mark(any(c.get("cost_per_task_usd") for c in an.get("configs", [])),
                                                   f"Pareto front: {', '.join(an.get('pareto_front') or []) or '—'}")),
        ("Holdout level matches the claim", *mark(bool(an.get("holdout") or (d or {}).get("holdout")),
                                                  an.get("holdout") or (d or {}).get("holdout"))),
        ("Failure analysis with inter-annotator agreement", *mark(bool(fx and fx.get("validated")),
                                                                  "κ = " + (f"{fx['cohens_kappa']:.2f}" if fx and fx.get("cohens_kappa") is not None else "not computed"))),
        ("Analysis seed + bootstrap resamples recorded", *mark(an.get("seed") is not None,
                                                               f"seed {an.get('seed')}, {an.get('n_boot')} resamples")),
        ("Task order seed recorded on every row", *mark(an.get("order_seed_recorded") is True,
                                                        "yes" if an.get("order_seed_recorded") else None)),
        ("Verdict stable across bootstrap seeds", *mark(all(v.get("seed_stable", False) for v in an.get("verdicts", [])) and an.get("verdicts"),
                                                        "yes" if all(v.get("seed_stable", False) for v in an.get("verdicts", [])) else None)),
        ("Confirmatory (not exploratory)", *mark(an.get("confirmatory") is True,
                                                 "confirmatory" if an.get("confirmatory") else "EXPLORATORY")),
    ]
    return "\n".join(f"| {label} | {ok} | {val} |" for label, ok, val in items)


def not_shown(p, d, tv, an, fx):
    out = []
    holdout = an.get("holdout") or (d or {}).get("holdout") or "unspecified"
    level = p.get("generality_level", "unspecified")
    out.append(f"**Generality.** The claim holds at the `{level}` level against a `{holdout}` holdout, and no "
               "further. Performance on other tasks, domains or distributions is not evidence here.")
    out.append("**Deployment.** These are offline scores on a held-out set. They are not production "
               "performance, not a service-level guarantee, and not a deployable operating point. Nothing in "
               "this pipeline measured the agent under real load, real users or real adversaries.")
    if (tv or {}).get("non_blocking_no_items"):
        out.append("**Known validity gaps.** The audit answered NO to " +
                   ", ".join(f"`{i}`" for i in tv["non_blocking_no_items"]) +
                   ". These did not block the run, but each is a way the number could be off, and the "
                   "direction is not always known.")
    for w in an.get("warnings", []):
        out.append(f"**Caveat from the analysis.** {w}")
    if p.get("secondary_metrics_exploratory"):
        out.append("**Exploratory metrics.** " + ", ".join(f"`{m}`" for m in p["secondary_metrics_exploratory"]) +
                   " were not preregistered as confirmatory. However they came out, they generate hypotheses; "
                   "they do not test one.")
    if fx and not fx.get("validated"):
        out.append("**Failure taxonomy.** Labelled by " +
                   ("two annotators who did not agree sufficiently" if fx.get("two_annotators") else "a single annotator") +
                   f" (κ = {fx.get('cohens_kappa') if fx.get('cohens_kappa') is not None else 'not computed'}). "
                   "Reported as an observation, not a measured distribution.")
    if (d or {}).get("underpowered"):
        out.append(f"**Power.** The design ran {d.get('n_tasks_planned')} tasks where {d.get('n_tasks_required')} "
                   "were needed for 80% power. A null result from this design is uninformative rather than negative.")
    out.append("**Contamination.** Nothing here proves the eval tasks were absent from model training. Models "
               "have scored well on SWE-bench-style tasks without the context needed to solve them, and dropped "
               "sharply on matched tasks from outside the benchmark. Treat an unexplained-high score as suspect.")
    return "\n".join(f"- {s}" for s in out)


def main():
    ap = argparse.ArgumentParser(description="Assemble the findings report from the pipeline's sidecars.")
    ap.add_argument("--prereg", required=True)
    ap.add_argument("--analysis", required=True, help="analysis.json")
    ap.add_argument("--design", help="experiment_design.json")
    ap.add_argument("--task-validity", help="task_validity.json")
    ap.add_argument("--manifest", help="trials_manifest.json")
    ap.add_argument("--failures", help="failure_taxonomy.json")
    ap.add_argument("--title", help="Report title. Default: the hypothesis. May not assert a positive "
                                    "result over a non-SUPPORTED verdict.")
    ap.add_argument("--primary-config", help="Which arm carries the preregistered claim (required when "
                                             "more than one arm was compared).")
    ap.add_argument("--exploratory", action="store_true",
                    help="Mark the whole report non-confirmatory; required to write up a failed or "
                         "missing validity audit.")
    ap.add_argument("--out-dir", help="Default: next to analysis.json.")
    args = ap.parse_args()

    p = load(args.prereg, True, "prereg.json")
    an = load(args.analysis, True, "analysis.json")
    d = load(args.design, False)
    if not args.task_validity and not args.exploratory:
        die("--task-validity is required. Omitting the audit used to produce a green report that simply "
            "said 'gate: not audited' in small print — the report would assert a finding the pipeline had "
            "no grounds for. Pass the audit, or --exploratory to mark the whole report non-confirmatory.", 3)
    tv = load(args.task_validity, False)
    gate = (tv or {}).get("gate")
    if tv and gate != "PASS" and not args.exploratory:
        die(f"REFUSED — the validity gate is {gate}, not PASS. A findings report over a failed audit "
            "presents a measurement of a broken instrument as a result. Fix the task and re-run, or pass "
            "--exploratory, which forces a non-confirmatory headline.", 4)
    if an.get("exploratory") and not args.exploratory:
        die("REFUSED — analysis.json is marked exploratory but --exploratory was not passed here. An "
            "exploratory analysis cannot become a confirmatory report by being written up.", 4)
    man = load(args.manifest, False)
    fx = load(args.failures, False)

    ph = prereg_hash(p)
    seen = {("prereg.json", ph), ("analysis.json", an.get("prereg_hash"))}
    if tv and tv.get("prereg_hash") not in (None, "none"):
        seen.add(("task_validity.json", tv["prereg_hash"]))
    if man and man.get("prereg_hash"):
        seen.add(("trials_manifest.json", man["prereg_hash"]))
    hashes = {h for _, h in seen if h}
    if len(hashes) > 1:
        die("REFUSED — the sidecars disagree about which hypothesis this is:\n  " +
            "\n  ".join(f"{src}: {h}" for src, h in sorted(seen) if h) +
            "\nThat means the hypothesis, metric, effect size or direction changed partway through. "
            "Re-run the affected stages, or report this explicitly as exploratory work.", 4)

    verdicts = an.get("verdicts") or []
    if not verdicts:
        head = {"verdict": "NO_SHARED_TASKS", "explanation": "no comparison available"}
    elif len(verdicts) == 1:
        head = verdicts[0]
    elif args.primary_config:
        match = [v for v in verdicts if v.get("config_id") == args.primary_config]
        if not match:
            die(f"--primary-config '{args.primary_config}' is not among the analysed arms "
                f"({', '.join(str(v.get('config_id')) for v in verdicts)}).", 3)
        head = match[0]
    else:
        die("REFUSED — this analysis compares " + str(len(verdicts)) + " arms against the baseline "
            f"({', '.join(str(v.get('config_id')) for v in verdicts)}), so there is no single headline "
            "claim. Naming the arm is a preregistration decision, not a formatting one: picking whichever "
            "arm came out best is HARKing, and taking the first one alphabetically means renaming a config "
            "flips the conclusion. Pass --primary-config <the preregistered treatment>.", 4)
    # Re-derive the verdict from the interval rather than trusting the stored string.
    diff = next((x for x in an.get("paired_differences", []) if x.get("config_id") == head.get("config_id")), None)
    if diff and head.get("verdict") in ("SUPPORTED", "BELOW_THRESHOLD", "NOT_SUPPORTED"):
        excludes = bool(diff.get("ci_excludes_zero"))
        signed = head.get("mean_difference") or 0.0
        expect = ("SUPPORTED" if excludes and signed >= p["min_effect"]
                  else "BELOW_THRESHOLD" if excludes and signed > 0 else None)
        if expect and expect != head["verdict"]:
            die(f"REFUSED — analysis.json states verdict {head['verdict']}, but its own interval "
                f"[{diff.get('ci_low')}, {diff.get('ci_high')}] with effect {signed} and min_effect "
                f"{p['min_effect']} implies {expect}. The sidecar has been edited. Re-run analyze-trials.", 4)
    icon, sentence = VERDICT_HEADLINE.get(head["verdict"], ("⚠️", head["verdict"]))
    cfgs = an.get("configs", [])
    front = an.get("pareto_front") or []
    cfg_lines = []
    for c in cfgs:
        star = " ⭐" if c["config_id"] in front else ""
        cost = "—" if c["cost_per_task_usd"] is None else f"${c['cost_per_task_usd']:.4f}"
        ci = f"[{c['ci_low']:.3f}, {c['ci_high']:.3f}]"
        cfg_lines.append(f"| `{c['config_id']}`{star} | {c['success_rate']:.3f} | {ci} | "
                         f"{c['n_tasks']} | {c['n_runs']} | {cost} |")
    cfg_rows = "\n".join(cfg_lines)

    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.analysis))
    title = args.title or p["hypothesis"]
    if args.title and head["verdict"] != "SUPPORTED":
        banned = ("gain", "improve", "better", "wins", "beats", "outperform", "decisive", "boost",
                  "success", "effective", "works", "confirms", "proves", "delivers")
        hit = [w for w in banned if w in args.title.lower()]
        if hit:
            die(f"REFUSED — --title claims a positive result ({', '.join(hit)}) over a "
                f"{head['verdict']} verdict. The headline is the one piece of author-controlled text in "
                "this report; letting it assert what the data did not show defeats the whole document. "
                "Retitle it neutrally, or state the non-result.", 4)
    md = f"""# Findings — {title}

## At a glance
```mermaid
flowchart LR
    H["hypothesis<br/>{p['primary_metric']} {p['direction']}s ≥ {p['min_effect']}"] --> G["ABC gate<br/>{(tv or {}).get('gate', 'not audited')}"]
    G --> R["{an.get('n_rows', '?')} runs<br/>K={(d or {}).get('k_runs', '?')}"]
    R --> A["paired difference<br/>{head.get('mean_difference') if head.get('mean_difference') is not None else '—'}"]
    A --> V["{icon} {head['verdict']}"]
```

## {icon} Result

**{sentence}**

{head['explanation']}

Preregistered claim: *{p['hypothesis']}* — `{p['primary_metric']}` must {p['direction']} by at least
**{p['min_effect']}** versus **{p['baseline']}**, registered as hash `{ph}` before any run.

| Config | success rate | 95% CI | tasks | runs | cost/task |
|---|--:|---|--:|--:|--:|
{cfg_rows}

## Reproducibility checklist
| Item | | Value |
|---|:-:|---|
{repro_rows(p, d, tv, an, man, fx)}

## What this does NOT show
{not_shown(p, d, tv, an, fx)}

## Falsification criterion, as registered
> {p['falsification']}

Recording this before the run is what makes the result above a test rather than a description. If the
verdict is not SUPPORTED, that is the criterion doing its job, and the result stands as a finding.
"""
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "findings.md"), "w") as f:
            f.write(md)
        with open(os.path.join(out_dir, "reproducibility.json"), "w") as f:
            json.dump({"prereg_hash": ph, "verdict": head["verdict"], "gate": gate,
                       "confirmatory": bool(an.get("confirmatory")) and not args.exploratory,
                       "primary_config": head.get("config_id"),
                       "model_version": (man or {}).get("model_version"), "k_runs": (d or {}).get("k_runs"),
                       "n_rows": an.get("n_rows"), "holdout": an.get("holdout") or (d or {}).get("holdout"),
                       "pareto_front": an.get("pareto_front"),
                       "failure_taxonomy_validated": bool(fx and fx.get("validated")),
                       "warnings": an.get("warnings", [])}, f, indent=2)
    except OSError as e:
        die(f"Could not write to {out_dir}: {e}", 2)

    print(f"Findings ✅  {os.path.join(out_dir, 'findings.md')}")
    print(f"  {icon} {head['verdict']} — {sentence}")
    if head["verdict"] != "SUPPORTED":
        eprint("\n  This is written up as a non-confirmation, not a failure. Report it: a preregistered "
               "null that goes unpublished is the mechanism that makes a literature look more positive "
               "than the evidence is.")


if __name__ == "__main__":
    main()
