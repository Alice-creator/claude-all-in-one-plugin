#!/usr/bin/env python3
"""judge-rag-answers: the generation-side GRADER for RAG research — score answer faithfulness / relevance /
correctness with an LLM judge, and report it HONESTLY, never as raw truth.

This is the key-heavy, non-deterministic half of RAG eval (the retrieval half is bm25-retrieval-metrics, which is
free and deterministic). An LLM judge is a BOUNDED proxy for human judgement: strong judges agree with humans
~80% of the time but carry position, verbosity, and self-preference biases, and raw % agreement overstates
chance-corrected agreement (Cohen's κ) by ~38 points. So this skill:
  - runs each score `--reps` times to expose non-determinism as a per-item variance + a bootstrap CI (over items);
  - computes chance-corrected **Cohen's κ** against a small human-labeled set when given (never a bare % match),
    the RAG analog of the plugin's "offline metric is not the truth";
  - reports a **verbosity diagnostic** (answer-length vs score correlation) and a **self-preference guard** (warns
    if the judge shares the generator's model family — the circularity that inflates a RAG number);
  - never prints a bare judge score as a result, and never hard-codes a pass/fail threshold (it reports diagnostics;
    the human judges). Offline judge score ≠ production quality.

Requires the USER's LLM key (OPENAI_API_KEY / ANTHROPIC_API_KEY) for a real judge. A `--judge mock:...` runs a
deterministic fake judge to verify the harness + the honesty math WITHOUT keys — its numbers are NOT a result
(`produces_results: false`), exactly like scaffold-trials' mock agent.

answers.jsonl: {"id","question","contexts":[...],"answer"[,"reference"]}
human labels (optional): {"id","label": 0|1[,"metric"]}   # 1 = human judged it good on that metric

Exit codes: 0 ok · 2 dependency/key/IO · 3 bad input.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical across scripts).
"""
import argparse
import hashlib
import json
import os
import sys


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def read_jsonl(path):
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
    return rows


METRIC_PROMPTS = {
    "faithfulness": ("You are grading whether an ANSWER is fully supported by the CONTEXTS (no unsupported claims).\n"
                     "CONTEXTS:\n{contexts}\n\nANSWER:\n{answer}\n\n"
                     "Reply with ONLY a number 0.0-1.0 (1.0 = every claim is grounded in the contexts)."),
    "answer_relevance": ("You are grading whether an ANSWER actually addresses the QUESTION.\n"
                         "QUESTION:\n{question}\n\nANSWER:\n{answer}\n\n"
                         "Reply with ONLY a number 0.0-1.0 (1.0 = fully answers the question)."),
    "answer_correctness": ("You are grading an ANSWER against a REFERENCE answer.\n"
                           "QUESTION:\n{question}\n\nREFERENCE:\n{reference}\n\nANSWER:\n{answer}\n\n"
                           "Reply with ONLY a number 0.0-1.0 (1.0 = matches the reference)."),
}


def build_prompt(metric, row):
    return METRIC_PROMPTS[metric].format(
        contexts="\n---\n".join(str(c) for c in row.get("contexts", [])),
        question=row.get("question", ""), answer=row.get("answer", ""), reference=row.get("reference", ""))


def mock_score(provider_seed, item_id, metric, rep):
    """Deterministic pseudo-score in [0,1] with per-rep jitter — exercises the variance/CI/κ math WITHOUT keys.
    NOT a result. Independent of answer content, so on mock the verbosity diagnostic is ~0 (noise), as expected."""
    h = hashlib.sha256(f"{provider_seed}|{item_id}|{metric}|{rep}".encode()).digest()
    return (h[0] / 255.0) * 0.7 + (h[1] / 255.0) * 0.3


def parse_score(text):
    """Pull a 0-1 float out of a judge reply; None if unparseable (recorded as an error, not silently 0)."""
    import re
    m = re.search(r"(?<![\d.])(0(?:\.\d+)?|1(?:\.0+)?)", str(text))
    return max(0.0, min(1.0, float(m.group(1)))) if m else None


def call_judge(provider, model, prompt, item_id, metric, rep):
    """Return a score in [0,1] or None. Real providers need the user's key; mock is deterministic + key-free."""
    if provider == "mock":
        return mock_score(model, item_id, metric, rep)
    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            die("--judge openai:<model> needs OPENAI_API_KEY (your key, your spend). Or use --judge mock:<name> "
                "to verify the harness without keys.", 2)
        try:
            import openai
        except Exception:
            die("openai package not installed — `.venv/bin/pip install openai`, or use --judge mock:<name>.", 2)
        r = openai.OpenAI().chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}], temperature=0.0)
        return parse_score(r.choices[0].message.content)
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            die("--judge anthropic:<model> needs ANTHROPIC_API_KEY (your key, your spend). Or use --judge "
                "mock:<name> to verify the harness without keys.", 2)
        try:
            import anthropic
        except Exception:
            die("anthropic package not installed — `.venv/bin/pip install anthropic`, or use --judge mock:<name>.", 2)
        r = anthropic.Anthropic().messages.create(
            model=model, max_tokens=16, messages=[{"role": "user", "content": prompt}])
        return parse_score(r.content[0].text)
    die(f"unknown judge provider '{provider}' — use mock:<name>, openai:<model>, or anthropic:<model>.", 3)


def cohens_kappa(a, b):
    """Chance-corrected agreement between two 0/1 raters. Report THIS, not raw % match."""
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(a) / n
    pb = sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def main():
    ap = argparse.ArgumentParser(description="Honest LLM-judge grader for RAG answer quality.")
    ap.add_argument("--answers", required=True, help="answers.jsonl (id, question, contexts, answer[, reference])")
    ap.add_argument("--judge", required=True, help="provider:model — mock:<name> | openai:<model> | anthropic:<model>")
    ap.add_argument("--metrics", default="faithfulness,answer_relevance",
                    help="comma list from faithfulness,answer_relevance,answer_correctness")
    ap.add_argument("--reps", type=int, default=3, help="judge calls per (item,metric) — exposes non-determinism")
    ap.add_argument("--human-labels", default=None, help="labels.jsonl (id, label 0/1[, metric]) to compute κ")
    ap.add_argument("--generator-family", default=None, help="the answer generator's model family (self-pref guard)")
    ap.add_argument("--pass-threshold", type=float, default=0.5, help="binarize scores for κ ONLY (not a verdict)")
    ap.add_argument("--out", default="judge_eval.json")
    args = ap.parse_args()

    try:
        import numpy as np
    except Exception:
        die("numpy required — use the project venv: .venv/bin/python", 2)
    if not os.path.exists(args.answers):
        die(f"--answers not found: {args.answers}", 3)
    if ":" not in args.judge:
        die("--judge must be provider:model, e.g. mock:m1 | openai:gpt-4o | anthropic:claude-opus-5-2026-05-01", 3)
    provider, model = args.judge.split(":", 1)
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    for m in metrics:
        if m not in METRIC_PROMPTS:
            die(f"unknown metric '{m}' — choose from {list(METRIC_PROMPTS)}", 3)
    rows = read_jsonl(args.answers)
    if not rows:
        die("answers file is empty", 3)
    for r in rows:
        if "id" not in r or "answer" not in r:
            die(f"answer row missing required 'id' or 'answer': {r}", 3)
    if "answer_correctness" in metrics and not all("reference" in r for r in rows):
        die("answer_correctness needs a 'reference' on every answer row.", 3)

    is_mock = provider == "mock"
    # self-preference guard is only MEANINGFUL when the generator family is known — None (not False) when it isn't,
    # so the sidecar never asserts "not the same family" for a check that was never run.
    same_family = (bool(args.generator_family.lower() in model.lower()) if args.generator_family else None)

    np.random.seed(0)  # deterministic bootstrap CI so the mock harness reproduces its own honesty math
    per_metric = {}
    n_calls = 0
    errors = 0
    for metric in metrics:
        item_means, item_stds, item_lengths, item_ids = [], [], [], []
        for r in rows:
            prompt = build_prompt(metric, r)
            reps = []
            for rep in range(args.reps):
                s = call_judge(provider, model, prompt, str(r["id"]), metric, rep)
                n_calls += 1
                if s is None:
                    errors += 1
                else:
                    reps.append(s)
            if reps:
                item_means.append(float(np.mean(reps)))
                item_stds.append(float(np.std(reps)))  # within-item variance from the SAME calls — no second paid pass
                item_lengths.append(len(str(r.get("answer", "")).split()))
                item_ids.append(str(r["id"]))
        arr = np.array(item_means) if item_means else np.array([0.0])
        # bootstrap CI over ITEMS (not reps) — the unit of generalization is the question
        boot = [float(np.mean(np.random.choice(arr, len(arr), replace=True))) for _ in range(2000)] if len(arr) else [0.0]
        # verbosity diagnostic: answer-length vs score (guarded against a constant-score NaN that would corrupt the JSON)
        vcorr = (float(np.corrcoef(item_lengths, item_means)[0, 1])
                 if len(set(item_lengths)) > 1 and len(item_means) > 1 and np.std(item_means) > 0 else None)
        entry = {
            "mean": round(float(np.mean(arr)), 4),
            "bootstrap_ci95": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
            "mean_within_item_std": round(float(np.mean(item_stds)), 4) if item_stds else None,
            "verbosity_length_score_corr": round(vcorr, 3) if vcorr is not None else None,
            "n_items": len(item_means),
        }
        # κ vs human labels (chance-corrected), if provided
        if args.human_labels and not os.path.exists(args.human_labels):
            eprint(f"  WARNING: --human-labels not found: {args.human_labels} — κ not computed (judge stays uncalibrated).")
        elif args.human_labels:
            hl = {}
            for h in read_jsonl(args.human_labels):
                if h.get("metric", metric) == metric:
                    hl[str(h["id"])] = int(h["label"])
            paired = [(1 if m_ >= args.pass_threshold else 0, hl[i]) for i, m_ in zip(item_ids, item_means) if i in hl]
            if paired:
                entry["n_human_labeled"] = len(paired)
                entry["kappa_binarize_threshold"] = args.pass_threshold
                entry["raw_match_vs_human"] = round(sum(1 for x, y in paired if x == y) / len(paired), 3)
                if len(paired) < 30:
                    entry["kappa_vs_human"] = None
                    entry["kappa_note"] = f"withheld — only {len(paired)} labeled pairs (<30); Cohen's κ on this few is noise"
                else:
                    jb, hb = zip(*paired)
                    entry["kappa_vs_human"] = round(cohens_kappa(list(jb), list(hb)), 3)
        per_metric[metric] = entry

    caveats = [
        "An LLM-judge score is an ESTIMATE WITH ERROR, not ground truth; report the CI, not the mean alone.",
        "Offline judge score ≠ production quality (static answers, no live corpus/query distribution).",
        "No pass/fail threshold is applied as a verdict — diagnostics are reported; the human judges.",
    ]
    if is_mock:
        caveats.insert(0, "MOCK JUDGE — deterministic fake scores to verify the harness + honesty math. NOT A RESULT.")
    if same_family is None:
        caveats.append("SELF-PREFERENCE GUARD INACTIVE — no --generator-family given, so the circularity check did "
                       "NOT run; if the judge shares the generator's model family the score is circular (effect is "
                       "task-dependent — smaller in strict fact-centric scoring).")
    elif same_family:
        caveats.append("SELF-PREFERENCE RISK: the judge shares the generator's model family — a documented "
                       "circularity that inflates the score (effect is task-dependent — smaller in strict "
                       "fact-centric scoring). Use a different-family judge and validate against humans.")
    labeled = any("n_human_labeled" in e for e in per_metric.values())
    kappa_reported = any(e.get("kappa_vs_human") is not None for e in per_metric.values())
    if not labeled:
        caveats.append("No human labels supplied — the judge is UNCALIBRATED; its absolute level is untrustworthy "
                       "(pass --human-labels for chance-corrected κ).")
    elif not kappa_reported:
        caveats.append("Human labels supplied but too few for a stable κ (<30 pairs) — the judge stays effectively "
                       "UNCALIBRATED; κ was withheld rather than reported as noise.")

    result = {
        "judge": args.judge, "provider": provider, "model": model, "reps": args.reps,
        "metrics": per_metric,
        "n_llm_calls": n_calls, "n_parse_errors": errors,
        "cost_note": "cost = n_llm_calls × your provider's per-call price (this skill cannot know pricing). The "
                     "agent-researcher trials.jsonl carries the per-run cost_usd; keep accuracy beside cost.",
        "produces_results": (not is_mock),
        "generator_judge_same_family": same_family,
        "offline_only": True, "matches_production": False, "is_ground_truth": False,
        "caveats": caveats,
    }
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    write_report(result)
    tag = "MOCK (not a result)" if is_mock else f"{n_calls} judge calls"
    print(f"Wrote {args.out} — {tag}: "
          + " · ".join(f"{m} {e['mean']} CI{e['bootstrap_ci95']}" for m, e in per_metric.items()))
    for c in caveats:
        if any(k in c for k in ("MOCK", "SELF-PREFERENCE", "INACTIVE", "UNCALIBRATED")):
            eprint("  ⚠️ " + c)


def write_report(r):
    rows = "\n".join(
        f"- **{m}**: {e['mean']} (95% CI {e['bootstrap_ci95']})"
        + (f" · κ-vs-human **{e['kappa_vs_human']}** (raw match {e.get('raw_match_vs_human')}, overstates κ)"
           if e.get('kappa_vs_human') is not None
           else (f" · κ: {e['kappa_note']}" if e.get('kappa_note') else " · κ: no human labels (uncalibrated)"))
        + (f" · verbosity corr {e['verbosity_length_score_corr']}" if e.get('verbosity_length_score_corr') is not None else "")
        for m, e in r["metrics"].items())
    banner = "🧪 MOCK — NOT A RESULT" if not r["produces_results"] else "🔑 real judge"
    md = f"""# RAG answer judging — {banner}

## At a glance
```mermaid
flowchart LR
    A["answers"] --> J["judge: {r['judge']}<br/>{r['reps']} reps/item"]
    J --> M["scores + 95% CI<br/>κ-vs-human · bias diagnostics"]
    M --> H["estimate-with-error ✓<br/>offline_only · not ground truth"]
```

**{banner}** · {r['n_llm_calls']} judge calls{f" · {r['n_parse_errors']} parse errors" if r['n_parse_errors'] else ""}

## Metrics (never a bare number — CI + calibration)
{rows}

## Honesty — read before trusting the number
{chr(10).join('- ' + c for c in r['caveats'])}

## Next
→ feed per-item scores into a trials.jsonl `success` for clustered-bootstrap analysis (agent-researcher spine);
never present a judge number as production quality.
"""
    with open("judge_eval_report.md", "w") as f:
        f.write(md)


if __name__ == "__main__":
    main()
