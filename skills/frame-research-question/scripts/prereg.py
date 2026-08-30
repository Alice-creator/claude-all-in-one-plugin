#!/usr/bin/env python3
"""frame-research-question: turn a research topic into a PREREGISTERED, falsifiable hypothesis.

Writes an IMMUTABLE prereg.json. Every downstream skill stamps its `prereg_hash`, so if the
hypothesis, primary metric, baseline, minimum effect size or direction is edited after results
exist, `analyze-trials` sees a hash mismatch and refuses to report a confirmation. That is the
code-enforced guard against HARKing (Hypothesising After the Results are Known), which in ML
shows up as post-hoc metric selection and benchmark gaming.

Refusals (this skill is a gate, not a form):
  - a hypothesis with no falsification criterion is not a hypothesis
  - more than one primary metric is metric shopping
  - an effect size of 0 makes the experiment unfalsifiable
  - an existing prereg is never overwritten; use --amend, which RECORDS the change

Exit codes: 0 ok · 2 IO issue · 3 bad/missing input · 4 refused.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical
across scripts); `prereg_hash` MUST stay identical everywhere it appears.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
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


def slugify(text, maxlen=48):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen].rstrip("-") or "experiment")


def check_falsifiable(args):
    """Reject the three ways a 'hypothesis' fails to be one. Returns a list of refusal reasons."""
    bad = []
    if re.search(r"[,;/]|\s", args.primary_metric.strip()):
        bad.append(f"--primary-metric got {args.primary_metric!r}: exactly ONE primary metric is allowed. "
                   "Several primary metrics means whichever one wins gets reported (metric shopping). "
                   "Put the rest in --secondary-metric; they are recorded as EXPLORATORY.")
    if args.min_effect <= 0:
        bad.append(f"--min-effect is {args.min_effect}: with a minimum effect of 0 every non-zero "
                   "difference 'supports' the hypothesis, so nothing can refute it. State the smallest "
                   "difference you would actually act on.")
    if len(args.falsification.strip()) < 20:
        bad.append("--falsify is too short to be a real criterion. Write the concrete result that would "
                   "make you conclude the hypothesis is WRONG (e.g. 'the paired difference CI includes 0, "
                   "or its upper bound is below +5 points').")
    return bad


def build_prereg(args):
    return {
        "hypothesis": args.hypothesis.strip(),
        "primary_metric": args.primary_metric.strip(),
        "baseline": args.baseline.strip(),
        "min_effect": args.min_effect,
        "direction": args.direction,
        "falsification": args.falsification.strip(),
        "secondary_metrics_exploratory": [m.strip() for m in args.secondary_metric or []],
        "generality_level": args.generality,
        "registered_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "amendments": [],
    }


def write_brief(out_dir, p):
    arrow = "increase" if p["direction"] == "increase" else "decrease"
    sec = ", ".join(p["secondary_metrics_exploratory"]) or "none"
    md = f"""# Research question — preregistered

## At a glance
```mermaid
flowchart LR
    H["HYPOTHESIS<br/>{p['primary_metric']} {arrow}s by ≥ {p['min_effect']}<br/>vs {p['baseline']}"]
    H --> F{{"result"}}
    F -->|"CI excludes 0<br/>AND effect ≥ {p['min_effect']}"| S["SUPPORTED"]
    F -->|"CI includes 0"| N["NOT SUPPORTED<br/>(report it anyway)"]
    F -->|"CI excludes 0<br/>but effect < {p['min_effect']}"| T["real but too small<br/>to act on"]
    H -.->|"locked · hash {p['prereg_hash']}"| L["any later edit is<br/>detected downstream"]
```

| Locked field | Value |
|---|---|
| **Hypothesis** | {p['hypothesis']} |
| **Primary metric** (only one) | `{p['primary_metric']}` |
| **Baseline to beat** | {p['baseline']} |
| **Minimum effect worth acting on** | {p['min_effect']} ({arrow}) |
| **Falsification criterion** | {p['falsification']} |
| **Generality level claimed** | `{p['generality_level']}` |
| **prereg_hash** | `{p['prereg_hash']}` |

Exploratory (NOT confirmatory) secondary metrics: {sec}

## What this locking does and does not do
- ✅ It makes the claim **falsifiable before any data exists**, and makes a later edit *detectable*:
  every downstream sidecar carries `{p['prereg_hash']}`, so swapping the metric after seeing results
  is caught by `analyze-trials` rather than silently absorbed.
- ✅ It commits you to reporting the result **even when the hypothesis fails**. A non-result that was
  preregistered is a finding; a non-result quietly dropped is HARKing.
- ⛔ It does **not** make the question worth asking. Preregistration blocks p-hacking, not bad ideas.
- ⛔ It does **not** license the claim. A supported hypothesis on an *invalid* task measures nothing —
  `validate-eval-task` is what decides whether the measuring instrument works at all.

## Next
→ `design-experiment` (holdout level, sample size via power analysis, cost budget).
"""
    with open(os.path.join(out_dir, "research_question_brief.md"), "w") as f:
        f.write(md)


def apply_amendment(path, reason, args):
    """Amend WITHOUT erasing: the original locked fields and hash stay in the file's history."""
    with open(path) as f:
        p = json.load(f)
    before = {"prereg_hash": p["prereg_hash"], "hypothesis": p["hypothesis"],
              "primary_metric": p["primary_metric"], "min_effect": p["min_effect"],
              "direction": p["direction"], "baseline": p["baseline"],
              "falsification": p["falsification"]}
    for field, value in (("hypothesis", args.hypothesis), ("primary_metric", args.primary_metric),
                         ("baseline", args.baseline), ("min_effect", args.min_effect),
                         ("direction", args.direction), ("falsification", args.falsification)):
        if value is not None:
            p[field] = value.strip() if isinstance(value, str) else value
    p["amendments"].append({
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "reason": reason, "superseded": before,
    })
    p["prereg_hash"] = prereg_hash(p)
    with open(path, "w") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)
    return p


def main():
    ap = argparse.ArgumentParser(description="Preregister a falsifiable research hypothesis.")
    ap.add_argument("--hypothesis", help="One sentence, comparative and measurable.")
    ap.add_argument("--primary-metric", help="Exactly ONE metric name, e.g. success_rate.")
    ap.add_argument("--baseline", help="The baseline this must beat (name it; 'nothing' is not a baseline).")
    ap.add_argument("--min-effect", type=float, help="Smallest difference worth acting on, in metric units.")
    ap.add_argument("--direction", choices=["increase", "decrease"], default=None,
                    help="Default: increase (on create); unchanged (on --amend).")
    ap.add_argument("--falsify", dest="falsification", help="The concrete result that would refute this.")
    ap.add_argument("--secondary-metric", action="append", help="Repeatable. Recorded as EXPLORATORY.")
    ap.add_argument("--generality", default="task-specific",
                    choices=["distribution-specific", "task-specific", "domain-general", "fully-general"],
                    help="How general a claim you intend to make; sets the holdout requirement downstream.")
    ap.add_argument("--out-dir", help="Default: research_experiments/<slug of hypothesis>")
    ap.add_argument("--amend", help="Reason for amending an EXISTING prereg. Records the change, never hides it.")
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join("research_experiments", slugify(args.hypothesis or "experiment"))
    path = os.path.join(out_dir, "prereg.json")

    if args.amend:
        if not args.out_dir:
            die("--amend requires --out-dir pointing at the existing experiment directory. The default "
                "directory is derived from --hypothesis, which an amendment usually changes or omits, so "
                "guessing it would silently look in the wrong place.", 3)
        if not os.path.exists(path):
            die(f"--amend given but no prereg at {path}. Register one first.", 3)
        with open(path) as f:
            merged = json.load(f)
        for field, value in (("hypothesis", args.hypothesis), ("primary_metric", args.primary_metric),
                             ("baseline", args.baseline), ("min_effect", args.min_effect),
                             ("direction", args.direction), ("falsification", args.falsification)):
            if value is not None:
                merged[field] = value
        merged_args = argparse.Namespace(
            primary_metric=merged["primary_metric"], min_effect=merged["min_effect"],
            falsification=merged["falsification"])
        bad = check_falsifiable(merged_args)
        if bad:
            die("REFUSED — the AMENDED prereg would not be falsifiable:\n  - " + "\n  - ".join(bad) +
                "\n\nAn amendment is still a preregistration. Relaxing it into something unfalsifiable is "
                "the failure this gate exists to stop, whichever path you reach it by.", 4)
        p = apply_amendment(path, args.amend, args)
        write_brief(out_dir, p)
        eprint(f"⚠️  AMENDED prereg (change recorded, original retained): {path}")
        eprint(f"    new prereg_hash={p['prereg_hash']}  ·  {len(p['amendments'])} amendment(s) on record")
        eprint("    Any trials already run under the OLD hash will be flagged by analyze-trials.")
        return

    if args.direction is None:
        args.direction = "increase"
    missing = [f for f, v in (("--hypothesis", args.hypothesis), ("--primary-metric", args.primary_metric),
                              ("--baseline", args.baseline), ("--min-effect", args.min_effect),
                              ("--falsify", args.falsification)) if v is None]
    if missing:
        die(f"Missing required field(s): {', '.join(missing)}. Each one is a way a hypothesis can be "
            "unfalsifiable, so none is optional.", 3)

    bad = check_falsifiable(args)
    if bad:
        die("REFUSED — this is not yet a falsifiable hypothesis:\n  - " + "\n  - ".join(bad), 4)

    if os.path.exists(path):
        die(f"REFUSED — a prereg already exists at {path}.\n"
            "A preregistration is immutable by design: silently rewriting it is exactly the thing it "
            "prevents. Either use a new --out-dir for a new experiment, or re-run with "
            '--amend "<why>" to record the change on top of the original.', 4)

    try:
        os.makedirs(out_dir, exist_ok=True)
        p = build_prereg(args)
        p["prereg_hash"] = prereg_hash(p)
        with open(path, "w") as f:
            json.dump(p, f, indent=2, ensure_ascii=False)
        write_brief(out_dir, p)
    except OSError as e:
        die(f"Could not write to {out_dir}: {e}", 2)

    print(f"Preregistered ✅  prereg_hash={p['prereg_hash']}")
    print(f"  {path}")
    print(f"  {os.path.join(out_dir, 'research_question_brief.md')}")
    print(f"\nLocked: {p['primary_metric']} must {p['direction']} by >= {p['min_effect']} vs {p['baseline']}.")
    print("This is now the ONLY confirmatory claim. Everything else you compute is exploratory.")
    print("\nNext: design-experiment (holdout level, sample size, cost budget).")


if __name__ == "__main__":
    main()
