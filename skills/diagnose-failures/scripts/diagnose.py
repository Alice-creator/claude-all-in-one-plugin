#!/usr/bin/env python3
"""diagnose-failures: turn failing traces into a defensible failure taxonomy — or refuse to.

A success rate says the agent fails; it does not say where, and where is the insight. This skill
follows the method MAST used (Cemri, Pan, Yang et al. 2025, UC Berkeley): 1,642 annotated traces
across 7 multi-agent frameworks, 14 failure modes in 3 categories, and — the part that makes it a
finding rather than an opinion — INTER-ANNOTATOR AGREEMENT of kappa = 0.88.

So the gate here is agreement, not effort: a taxonomy labelled by one person, or by two who do not
agree, is an opinion formatted as a table. This script computes Cohen's kappa and REFUSES to present
the distribution as a finding below the threshold. It marks it `unvalidated` instead, and says so in
the report rather than quietly rendering percentages.

MAST's headline result is worth carrying into the read: most failures came from SYSTEM DESIGN
(44.2%), not from model capability. A taxonomy that lands every failure on "the model isn't smart
enough" is usually a taxonomy that did not look.

Exit codes: 0 ok · 2 IO issue · 3 bad/missing input · 4 refused.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical
across scripts); `load_trials` MUST stay identical everywhere it appears.
"""
import argparse
import json
import os
import random
import sys


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


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


# MAST: 14 failure modes in 3 categories (Cemri et al. 2025). Category shares from that paper.
MAST = {
    "FM-1.1": ("system-design", "Disobey task specification"),
    "FM-1.2": ("system-design", "Disobey role specification"),
    "FM-1.3": ("system-design", "Step repetition"),
    "FM-1.4": ("system-design", "Loss of conversation history"),
    "FM-1.5": ("system-design", "Unaware of termination conditions"),
    "FM-2.1": ("inter-agent-misalignment", "Conversation reset"),
    "FM-2.2": ("inter-agent-misalignment", "Fail to ask for clarification"),
    "FM-2.3": ("inter-agent-misalignment", "Task derailment"),
    "FM-2.4": ("inter-agent-misalignment", "Information withholding"),
    "FM-2.5": ("inter-agent-misalignment", "Ignored other agent's input"),
    "FM-2.6": ("inter-agent-misalignment", "Reasoning-action mismatch"),
    "FM-3.1": ("task-verification", "Premature termination"),
    "FM-3.2": ("task-verification", "No or incomplete verification"),
    "FM-3.3": ("task-verification", "Incorrect verification"),
    "INFRA": ("not-an-agent-failure", "Infrastructure/harness fault, not the agent"),
    "OTHER": ("unclassified", "Does not fit the taxonomy — extend it, don't force a fit"),
}


def cohens_kappa(labels_a, labels_b):
    """Agreement corrected for chance. Two annotators, shared items only.

    Returns None when kappa is UNDEFINED: with no marginal variability (both annotators used a single
    category) chance agreement is already 1, so kappa is 0/0. Returning 1.0 there would certify the
    laziest possible annotation — two people stamping OTHER on everything — as perfect agreement.
    sklearn returns nan for this case; we return None and refuse to validate."""
    shared = sorted(set(labels_a) & set(labels_b))
    if not shared:
        return None, 0
    n = len(shared)
    agree = sum(1 for i in shared if labels_a[i] == labels_b[i])
    po = agree / n
    cats = set(labels_a[i] for i in shared) | set(labels_b[i] for i in shared)
    pe = sum((sum(1 for i in shared if labels_a[i] == c) / n) *
             (sum(1 for i in shared if labels_b[i] == c) / n) for c in cats)
    if pe >= 1.0 - 1e-12:
        return None, n
    return (po - pe) / (1 - pe), n


def kappa_reading(k):
    if k is None:
        return "not computable"
    if k < 0.20:
        return "slight — effectively no agreement beyond chance"
    if k < 0.40:
        return "fair — not usable as evidence"
    if k < 0.60:
        return "moderate — below the bar for a reported taxonomy"
    if k < 0.80:
        return "substantial"
    return "almost perfect"


def sample_failures(rows, n, seed, per_config=True):
    """Stratified by config so one arm's failures don't dominate the sample."""
    fails = [r for r in rows if not r.get("success")]
    if not fails:
        return []
    rng = random.Random(seed)
    if not per_config:
        return rng.sample(fails, min(n, len(fails)))
    by_cfg = {}
    for r in fails:
        by_cfg.setdefault(r["config_id"], []).append(r)
    per = max(1, n // max(1, len(by_cfg)))
    out = []
    for cfg in sorted(by_cfg):
        pool = by_cfg[cfg]
        out += rng.sample(pool, min(per, len(pool)))
    return out


def item_key(r):
    return f"{r['task_id']}|{r['config_id']}|{r['run_idx']}"


def read_labels(path):
    """jsonl of {"item": "<key>", "label": "FM-1.3"}.

    UNLABELLED rows are dropped, not kept as a category. A blank is something both annotators
    trivially "agree" on, and enough of them drag a genuine kappa of 0.13 up past the 0.6 gate."""
    out, blank, bad = {}, 0, []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                bad.append(f"line {lineno}: not valid JSON ({e.msg})")
                continue
            if not isinstance(r, dict) or "item" not in r:
                bad.append(f"line {lineno}: no 'item' field")
                continue
            label = str(r.get("label") or "").strip()
            if not label:
                blank += 1
                continue
            out[r["item"]] = label
    if bad:
        die(f"REFUSED — {len(bad)} malformed row(s) in {path}:\n  - " + "\n  - ".join(bad[:10]) +
            ("\n  - ..." if len(bad) > 10 else ""), 3)
    return out, blank


def distribution(labels):
    """Shares against TWO denominators: all labelled rows, and agent failures only (INFRA excluded).

    Leaving harness faults in the denominator understates the agent; silently dropping them
    overstates it. Both numbers ship so neither reading can be presented alone."""
    by_mode, by_cat = {}, {}
    for lab in labels.values():
        by_mode[lab] = by_mode.get(lab, 0) + 1
        cat = MAST.get(lab, ("unclassified", ""))[0]
        by_cat[cat] = by_cat.get(cat, 0) + 1
    n = len(labels) or 1
    n_infra = by_mode.get("INFRA", 0)
    n_agent = (len(labels) - n_infra) or 1

    def rows(d, exclude_infra):
        out = {}
        for k, c in sorted(d.items(), key=lambda x: -x[1]):
            is_infra = (k == "INFRA") if not exclude_infra else (k == "not-an-agent-failure")
            out[k] = {"n": c, "share": round(c / n, 4),
                      "share_agent_failures_only": None if is_infra else round(c / n_agent, 4)}
        return out
    return rows(by_mode, False), rows(by_cat, True), {"n_labelled": len(labels), "n_infra": n_infra,
                                                      "n_agent_failures": len(labels) - n_infra}


def write_sheet(path, sampled):
    with open(path, "w") as f:
        for r in sampled:
            f.write(json.dumps({"item": item_key(r), "task_id": r["task_id"],
                                "config_id": r["config_id"], "run_idx": r["run_idx"],
                                "trace_path": r.get("trace_path"), "error": r.get("error"),
                                "label": ""}) + "\n")


def write_report(out_dir, validated, kappa, n_shared, by_mode, by_cat, n_labelled, n_fail, n_total, note):
    badge = "🟢 VALIDATED" if validated else "🔴 UNVALIDATED — single-annotator or low agreement"
    mode_rows = "\n".join(
        f"| `{m}` | {MAST.get(m, ('unclassified', m))[1]} | {MAST.get(m, ('unclassified', ''))[0]} | {v['n']} | {v['share']:.1%} |"
        for m, v in by_mode.items()) or "| — | _(no labels)_ | — | — | — |"
    cat_rows = "\n".join(f"| {c} | {v['n']} | {v['share']:.1%} |" for c, v in by_cat.items()) or "| — | — | — |"
    kappa_txt = ("undefined (no marginal variability)" if kappa is None and n_shared
                 else "—" if kappa is None else f"{kappa:.2f} ({kappa_reading(kappa)})")
    headline = ("The distribution below is reportable." if validated else
                "**The distribution below is NOT reportable as a finding.** It is recorded so the labelling "
                "can be redone, not so it can be cited.")
    md = f"""# Failure diagnosis — {badge}

## At a glance
```mermaid
flowchart LR
    T["{n_total} runs<br/>{n_fail} failures"] --> S["sampled {n_labelled}<br/>stratified by config"]
    S --> A["2 annotators<br/>independently"]
    A --> K["Cohen's κ = {kappa_txt}"]
    K -->|"{'κ ≥ threshold' if validated else 'below threshold'}"| R["{'reportable taxonomy' if validated else 'NOT reportable'}"]
```

{headline}

| | |
|---|---|
| Failures sampled and labelled | {n_labelled} of {n_fail} |
| Inter-annotator agreement (Cohen's κ) | **{kappa_txt}** on {n_shared} shared items |
| Status | {badge} |

{note}

## By failure mode
| Mode | Description | Category | n | share |
|---|---|---|--:|--:|
{mode_rows}

## By category
| Category | n | share |
|---|--:|--:|
{cat_rows}

MAST found **44.2%** of multi-agent failures were **system design**, not model capability. If your
distribution puts almost everything on the model, check whether the labelling looked at the
orchestration at all: termination conditions, lost history, role confusion and repeated steps are
design faults that read like stupidity in a trace.

## Honest limits of this step
- ⛔ A taxonomy is a **description of a sample**, not a measurement of the population. It carries no
  confidence interval and should not be reported as if it did.
- ⛔ Labels are judgements. Without two independent annotators and an agreement statistic, the shares
  above are one person's reading — which is why this skill refuses to bless them.
- ⛔ `INFRA` rows are **not** agent failures. Leaving them in the denominator understates the agent;
  moving them out silently overstates it. Report both counts.
- ⛔ Correlation with a config is not causation. A mode being commoner in one arm suggests the next
  ablation; it does not establish that the arm caused it.

## Next
→ `write-findings` — assemble the preregistered claim, the caveats and what was NOT shown.
"""
    with open(os.path.join(out_dir, "failure_report.md"), "w") as f:
        f.write(md)


def main():
    ap = argparse.ArgumentParser(description="Label and validate an agent failure taxonomy.")
    ap.add_argument("--trials", required=True)
    ap.add_argument("--sample", type=int, default=100, help="Failures to sample for labelling (default 100).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--emit-sheet", action="store_true", help="Write labeling_sheet.jsonl and exit.")
    ap.add_argument("--labels-a", help="jsonl of {item, label} from annotator A.")
    ap.add_argument("--labels-b", help="jsonl from annotator B (independent). Required for a VALIDATED taxonomy.")
    ap.add_argument("--kappa-threshold", type=float, default=0.6,
                    help="Minimum Cohen's kappa to report the distribution (default 0.6).")
    ap.add_argument("--min-shared-items", type=int, default=30,
                    help="Minimum items both annotators labelled (default 30).")
    ap.add_argument("--out-dir", help="Default: next to trials.jsonl.")
    args = ap.parse_args()

    if not os.path.exists(args.trials):
        die(f"Missing {args.trials}.", 3)
    rows, _ = load_trials(args.trials)
    if not rows:
        die(f"No usable rows in {args.trials}.", 3)
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.trials))
    os.makedirs(out_dir, exist_ok=True)

    sampled = sample_failures(rows, args.sample, args.seed)
    n_fail = sum(1 for r in rows if not r.get("success"))
    if not sampled:
        die("No failing runs to diagnose — nothing to label. (If the success rate is 100%, check "
            "validate-eval-task: a benchmark nobody fails is usually a benchmark with a shortcut.)", 3)

    sheet = os.path.join(out_dir, "labeling_sheet.jsonl")
    if args.emit_sheet or not args.labels_a:
        write_sheet(sheet, sampled)
        msg = (f"Wrote {sheet}: {len(sampled)} failures sampled from {n_fail}, stratified by config.\n"
               "Have TWO people label them independently (fill the `label` field with a MAST code), then "
               "pass --labels-a and --labels-b. One annotator cannot produce a reportable taxonomy.")
        if args.emit_sheet:
            print(msg)
            return
        die(msg, 3)

    labels_a, blank_a = read_labels(args.labels_a)
    labels_b, blank_b = (read_labels(args.labels_b) if args.labels_b else ({}, 0))
    labels_b = labels_b or None
    kappa, n_shared = (cohens_kappa(labels_a, labels_b) if labels_b else (None, 0))
    single_category = bool(labels_b) and (len(set(labels_a.values())) < 2 or len(set(labels_b.values())) < 2)
    enough_items = n_shared >= args.min_shared_items
    validated = bool(labels_b and kappa is not None and kappa >= args.kappa_threshold
                     and not single_category and enough_items)

    if single_category:
        note = ("> 🔴 **No marginal variability.** At least one annotator used a single category for every "
                "item, so chance agreement is already 1 and Cohen's κ is undefined (0/0), not perfect. "
                "Two people stamping the same code on everything is not agreement, it is not labelling.")
    elif labels_b and not enough_items:
        note = (f"> 🔴 **Too few shared items** ({n_shared} < {args.min_shared_items}). κ on a handful of "
                "items is dominated by chance; it is not evidence about the distribution.")
    elif not labels_b:
        note = ("> 🔴 **Single annotator.** MAST's taxonomy is citable because two people labelled "
                "independently and agreed at κ=0.88. With one annotator there is no way to tell a real "
                "pattern from one reader's habit of seeing it. Add a second annotator.")
    elif not validated:
        note = (f"> 🔴 **Agreement too low** (κ={kappa:.2f} < {args.kappa_threshold}, {kappa_reading(kappa)}). "
                "The two annotators are not applying the same taxonomy. Reconcile the definitions on a "
                "handful of traces, then re-label — do not average the two readings.")
    else:
        note = (f"> 🟢 Two annotators agreed at κ={kappa:.2f} ({kappa_reading(kappa)}) on {n_shared} shared "
                "items, so the shares below describe the sample rather than one reader.")

    by_mode, by_cat, denoms = distribution(labels_a)
    unknown = sorted({l for l in labels_a.values() if l not in MAST})
    sidecar = {"validated": validated, "cohens_kappa": kappa, "kappa_threshold": args.kappa_threshold,
               "kappa_undefined": bool(labels_b) and kappa is None,
               "single_category_annotation": single_category,
               "n_shared_items": n_shared, "min_shared_items": args.min_shared_items,
               "n_labelled": len(labels_a), "n_failures": n_fail,
               "n_runs": len(rows), "by_mode": by_mode, "by_category": by_cat, "denominators": denoms,
               "n_unlabelled_rows": {"annotator_a": blank_a, "annotator_b": blank_b},
               "labels_outside_taxonomy": unknown, "two_annotators": bool(labels_b),
               "reportable": validated}
    try:
        with open(os.path.join(out_dir, "failure_taxonomy.json"), "w") as f:
            json.dump(sidecar, f, indent=2)
        write_report(out_dir, validated, kappa, n_shared, by_mode, by_cat, len(labels_a), n_fail,
                     len(rows), note)
    except OSError as e:
        die(f"Could not write to {out_dir}: {e}", 2)

    print(f"Diagnosis written: {os.path.join(out_dir, 'failure_report.md')}")
    kappa_str = "undefined" if kappa is None else f"{kappa:.2f}"
    print(f"  {len(labels_a)} labelled of {n_fail} failures  ·  κ = {kappa_str}  ·  "
          f"{'🟢 VALIDATED' if validated else '🔴 UNVALIDATED'}")
    if blank_a or blank_b:
        print(f"    ({blank_a} + {blank_b} unlabelled sheet rows dropped, not counted as agreement)")
    for c, v in by_cat.items():
        agent_only = ("" if v["share_agent_failures_only"] is None
                      else f"   ({v['share_agent_failures_only']:.1%} of agent failures)")
        print(f"    {c:<28} {v['n']:>4}  {v['share']:.1%} of all{agent_only}")
    if unknown:
        eprint(f"\n  ⚠️ labels outside the taxonomy: {', '.join(unknown)} — extend MAST deliberately "
               "rather than forcing traces into a code that doesn't fit.")
    if not validated:
        eprint("\n  🔴 NOT reportable as a finding. write-findings will render it as an unvalidated "
               "observation, not a result.")
    print("\nNext: write-findings.")


if __name__ == "__main__":
    main()
