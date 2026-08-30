#!/usr/bin/env python3
"""validate-eval-task: audit the MEASURING INSTRUMENT before paying to run anything.

This is a GATE, not a report. It implements the Agentic Benchmark Checklist (ABC; Zhu et al.,
NeurIPS 2025 D&B), which found 7/10 popular agent benchmarks violating task validity, 7/10
violating outcome validity, and 10/10 with reporting gaps — errors up to 100% in relative terms:

  tau-bench   38% of airline tasks are unsolvable and success == 'environment unchanged',
              so a DO-NOTHING agent passes them (+38%); dumping the whole database passes
              substring-matched tasks (+40%).
  SWE-Lancer  agents can overwrite the benchmark's own tests with `assert 1 == 1` -> 100%.
  KernelBench the fuzzer varied tensor values but not shapes/layouts -> +31%.
  CVE-Bench   a SLEEP clause merely APPEARING in the log counted as a time-based injection -> +32.5%.
  OSWorld     13/46 Chrome tasks broke when real websites changed -> agent UNDERrated by 28%.

Two checks are empirical, not questionnaire answers, and both are mandatory:
  * TRIVIAL-AGENT PROBE (ABC R.13): a do-nothing / fixed-reply agent must score ~0. If it scores,
    the task is measuring something other than the capability. This script writes trivial_probe.py
    for you to run; without its results the gate is BLOCKED, never PASS.
  * ORACLE SOLVE RATE (ABC T.8-T.9): a reference solver must solve 100%. Anything less means some
    tasks are impossible and every agent is being charged for them as failures.

Exit codes: 0 GATE PASS · 2 IO issue · 3 bad/missing input · 4 refused · 5 GATE FAILED/BLOCKED.

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


# (id, section, group, applies_when, mandatory, text)
# applies_when: "always" | a tool/env flag | an outcome-method name. Verbatim intent from ABC Figs 2-4.
ABC = [
    ("T.1", "task", "Tool", "tools", True, "Versions of all tools (e.g. Python) are clearly specified."),
    ("T.2", "task", "Tool", "tools", True, "Required API tools are consistently accessible during evaluation."),
    ("T.3", "task", "Tool", "tools", True, "Evaluation terminates or handles errors if an API becomes inaccessible."),
    ("T.4", "task", "Env", "env", True, "Residual data or state are fully cleared between runs."),
    ("T.5", "task", "Env", "always", True, "Agent is completely isolated from any ground truth information."),
    ("T.6", "task", "Env", "env", True, "Setup does not change over time (e.g. no live website)."),
    ("T.7", "task", "Impl", "always", True, "Annotated ground truth is verified for correctness."),
    ("T.8", "task", "Impl", "always", True, "Each task is verified to be solvable."),
    ("T.9", "task", "Impl", "always", True, "An oracle solver can automatically solve all challenges."),
    ("T.10", "task", "Impl", "always", True, "Implementation is free of vulnerabilities that pass eval without solving."),
    ("O.a.1", "outcome", "InfoAcq", "string-match", True, "Considers expressions semantically equivalent to ground truth."),
    ("O.a.2", "outcome", "InfoAcq", "string-match", True, "Handles redundant words used by agents."),
    ("O.b.1", "outcome", "InfoAcq", "substring-match", True, "Handles negation modifiers used by agents."),
    ("O.b.2", "outcome", "InfoAcq", "substring-match", True, "Is robust against systematically listing all possible answers."),
    ("O.b.3", "outcome", "InfoAcq", "substring-match", True, "Ground truth is sufficiently complex to prevent guessing."),
    ("O.c.1", "outcome", "Judge", "llm-judge", True, "Documented evidence of the judge's accuracy, self-consistency and human agreement."),
    ("O.c.2", "outcome", "Judge", "llm-judge", True, "Judge is designed to resist adversarial inputs and reward hacking."),
    ("O.d.1", "outcome", "Code", "unit-test", True, "Test cases verified for correctness and quality (e.g. by human)."),
    ("O.d.2", "outcome", "Code", "unit-test", False, "Test-case quality measured objectively (e.g. code coverage)."),
    ("O.e.1", "outcome", "Code", "fuzz-test", True, "Addresses potential edge cases."),
    ("O.e.2", "outcome", "Code", "fuzz-test", True, "Covers all relevant input variations (data types, memory layouts, ranges)."),
    ("O.e.3", "outcome", "Code", "fuzz-test", True, "Generates inputs the code under test is sensitive to."),
    ("O.f.1", "outcome", "Code", "e2e-test", True, "Exercises all relevant parts of the code being tested."),
    ("O.f.2", "outcome", "Code", "e2e-test", True, "Prevents non-deterministic ('flaky') test results."),
    ("O.g.1", "outcome", "State", "state-match", True, "Ground truth includes all states achievable after success."),
    ("O.g.2", "outcome", "State", "state-match", True, "Checks relevant AND irrelevant states for the challenge."),
    ("O.g.3", "outcome", "State", "state-match", True, "Ground truth is complex enough to prevent trivial state modifications."),
    ("O.h.1", "outcome", "MultiStep", "answer-match", True, "Required answer formats are specified in the task description."),
    ("O.h.2", "outcome", "MultiStep", "answer-match", True, "Minimises the possibility of success by random guessing."),
    ("O.i.1", "outcome", "MultiStep", "quality-measure", True, "Quality metrics are designed to prevent exploitation (reward hacking)."),
    ("R.1", "reporting", "Transparency", "always", False, "Is fully or at least partially open-sourced."),
    ("R.2", "reporting", "Transparency", "always", False, "Offers an open-source evaluation harness for users."),
    ("R.3", "reporting", "Transparency", "always", True, "Measures to prevent data contamination (e.g. a private held-out test set)."),
    ("R.4", "reporting", "Transparency", "always", False, "Measures or plans to update challenges over time to avoid overfitting."),
    ("R.5", "reporting", "Transparency", "always", True, "States the relationship between target capability and what is measured."),
    ("R.6", "reporting", "Transparency", "always", True, "States the evaluation subject (a model, or an agent framework)."),
    ("R.7", "reporting", "Mitigation", "always", False, "Describes steps taken to prevent, identify and correct flaws."),
    ("R.8", "reporting", "Mitigation", "always", False, "Qualitative discussion of the impact of unavoidable flaws."),
    ("R.9", "reporting", "Mitigation", "always", False, "Quantitative analysis of the impact of unavoidable flaws."),
    ("R.10", "reporting", "Interpretation", "always", True, "Reports statistical significance measures such as confidence intervals."),
    ("R.11", "reporting", "Interpretation", "always", False, "Provides guidance on interpreting results given known eval flaws."),
    ("R.12", "reporting", "Interpretation", "always", False, "Reports non-AI baselines (e.g. human experts)."),
    ("R.13", "reporting", "Interpretation", "always", True, "Reports results of trivial agents (e.g. one that does nothing)."),
]

TRIVIAL_PROBE = '''#!/usr/bin/env python3
"""Trivial-agent probe (ABC R.13) — the cheapest way to discover a broken benchmark.

Runs agents that possess NONE of the target capability. Each must score ~0. If any of them
scores, the task is rewarding something other than the capability, and every number you were
about to spend money on is measuring that instead.

Real findings this exact probe would have caught:
  - tau-bench: `do_nothing` passes 38% of the airline subset (success == environment unchanged).
  - tau-bench / WebArena: `dump_everything` passes substring-matched tasks by listing all answers.
  - WebArena: `empty_reply` is accepted as correct by the judge on 'N/A' tasks.

WIRE UP `run_task` BELOW, then: python trivial_probe.py --out trivial_results.jsonl
"""
import argparse, json

def do_nothing(task):          return ""
def empty_reply(task):         return ""
def fixed_reply(task):         return "I cannot complete this task."
def dump_everything(task):     return " ".join(str(v) for v in task.get("context", {}).values())
def guess_first_option(task):  return (task.get("options") or [""])[0]

TRIVIAL_AGENTS = {"do_nothing": do_nothing, "empty_reply": empty_reply, "fixed_reply": fixed_reply,
                  "dump_everything": dump_everything, "guess_first_option": guess_first_option}

def load_tasks():
    """TODO: return your eval tasks as a list of dicts, each with at least an 'id'."""
    raise NotImplementedError("load_tasks(): return your eval task list")

def score(task, answer):
    """TODO: call YOUR grader — the exact one the real experiment will use. Return 1.0 or 0.0.
    Do not write a simplified grader here; the point is to test the real one."""
    raise NotImplementedError("score(): call the same grader the real run uses")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="trivial_results.jsonl")
    a = ap.parse_args()
    tasks = load_tasks()
    with open(a.out, "w") as f:
        for name, agent in TRIVIAL_AGENTS.items():
            for t in tasks:
                s = score(t, agent(t))
                f.write(json.dumps({"agent": name, "task_id": t["id"], "success": bool(s)}) + "\\n")
    print(f"wrote {a.out} — feed it to validate_task.py --trivial-results")

if __name__ == "__main__":
    main()
'''


def applicable(item, methods, uses_tools, uses_env):
    _, _, _, when, _, _ = item
    if when == "always":
        return True
    if when == "tools":
        return uses_tools
    if when == "env":
        return uses_env
    return when in methods


def read_answer(answers, key):
    """Accepts `true`, `false`, `"na"`, or {"answer": ..., "evidence": "..."}."""
    v = answers.get(key)
    if isinstance(v, dict):
        return v.get("answer"), v.get("evidence", "")
    return v, ""


def score_sections(items, answers, methods, uses_tools, uses_env):
    rows, per_section = [], {}
    for it in items:
        iid, section, group, _, mandatory, text = it
        if not applicable(it, methods, uses_tools, uses_env):
            continue
        ans, evidence = read_answer(answers, iid)
        state = "na" if ans == "na" else ("yes" if ans is True else "no" if ans is False else "unanswered")
        rows.append({"id": iid, "section": section, "group": group, "mandatory": mandatory,
                     "text": text, "state": state, "evidence": evidence})
        if state != "na":
            b = per_section.setdefault(section, {"yes": 0, "no": 0, "unanswered": 0})
            b[state] += 1
    scores = {}
    for s, b in per_section.items():
        total = b["yes"] + b["no"] + b["unanswered"]
        scores[s] = {"yes": b["yes"], "no": b["no"], "unanswered": b["unanswered"],
                     "score": round(b["yes"] / total, 3) if total else None}
    return rows, scores


def read_trivial(path):
    """Per-agent pass rate from the probe's jsonl, parsed STRICTLY.

    A probe that writes {"passed": true} instead of {"success": true} is a plausible accident, and
    coercing the missing key to False reports a fabricated 0% for an agent that actually passed 48%
    of tasks — the gate then certifies rigour it never measured. So a row missing `agent` or
    `success`, or whose `success` is not a real bool, is an ERROR, never a silent failure."""
    tally, bad = {}, []
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
            if not isinstance(r, dict) or "agent" not in r:
                bad.append(f"line {lineno}: no 'agent' field")
                continue
            if "success" not in r:
                bad.append(f"line {lineno}: no 'success' field (did the probe write 'passed' or 'score'?)")
                continue
            if not isinstance(r["success"], bool):
                bad.append(f"line {lineno}: 'success' is {type(r['success']).__name__}, not a bool")
                continue
            t = tally.setdefault(str(r["agent"]), {"n": 0, "passed": 0})
            t["n"] += 1
            t["passed"] += 1 if r["success"] else 0
    if bad:
        die(f"REFUSED — {len(bad)} malformed row(s) in {path}:\n  - " + "\n  - ".join(bad[:10]) +
            ("\n  - ..." if len(bad) > 10 else "") +
            "\n\nThe probe's output is the evidence this gate rests on. Rows it cannot read are not "
            "counted as failures — that would fabricate a clean result. Fix the probe and re-run it.", 3)
    return {a: {"n": v["n"], "passed": v["passed"],
                "rate": round(v["passed"] / v["n"], 4) if v["n"] else 0.0} for a, v in tally.items()}


def evaluate_gate(rows, trivial, args):
    """Hard predicates. Each maps to a specific documented benchmark failure, not a preference."""
    fails, blocks = [], []
    by_id = {r["id"]: r for r in rows}

    def state(i):
        return by_id[i]["state"] if i in by_id else "na"

    if not trivial:
        blocks.append("R.13 — no usable trivial-agent results (--trivial-results absent, empty, or all rows "
                      "unreadable). A do-nothing agent passing 38% of tau-bench's airline tasks was found "
                      "this way. Run the generated trivial_probe.py against YOUR grader; the gate cannot "
                      "PASS without it. An empty file is not evidence of a clean result.")
    else:
        if len(trivial) < args.min_trivial_agents:
            blocks.append(f"R.13 — only {len(trivial)} trivial agent(s) reported "
                          f"({', '.join(sorted(trivial))}), below --min-trivial-agents "
                          f"{args.min_trivial_agents}. Running just the one that scores 0 proves nothing; "
                          "the probe ships several because they fail differently (do-nothing passes "
                          "'leave the environment unchanged' tasks, dump-everything passes substring "
                          "matching).")
        thin = [f"{a} (n={v['n']})" for a, v in sorted(trivial.items()) if v["n"] < args.min_trivial_tasks]
        if thin:
            blocks.append(f"R.13 — too few tasks probed for: {', '.join(thin)} (need "
                          f"{args.min_trivial_tasks}). A trivial agent measured on a handful of tasks "
                          "cannot demonstrate it scores ~0.")
        for agent, v in sorted(trivial.items()):
            if v["rate"] > args.trivial_tolerance:
                fails.append(f"R.13 — the trivial agent '{agent}' scores {v['rate']:.1%} ({v['passed']}/{v['n']}), "
                             f"above the {args.trivial_tolerance:.1%} tolerance. It possesses none of the target "
                             f"capability, so that score is the benchmark rewarding something else. Fix the task "
                             f"or the grader; do not subtract it as a 'floor'.")
    if args.trivial_tolerance > 0 and not args.ack_trivial_tolerance:
        blocks.append(f"--trivial-tolerance is {args.trivial_tolerance}, not 0. Any non-zero tolerance means "
                      "accepting that an agent with none of the target capability scores points, which is "
                      "the benchmark rewarding something else. Pass --ack-trivial-tolerance \"<why>\" to "
                      "record the justification; it is stamped into the sidecar and the report.")
    if args.oracle_solve_rate is None:
        blocks.append("T.8/T.9 — no --oracle-solve-rate given. A reference solver must demonstrably solve every "
                      "task; otherwise unsolvable tasks are silently charged to the agent as failures.")
    elif not 0.0 <= args.oracle_solve_rate <= 1.0:
        fails.append(f"T.8/T.9 — --oracle-solve-rate is {args.oracle_solve_rate}, which is not a fraction "
                     "in [0,1]. A solve rate above 1 is not a stronger result, it is a bug in how it was "
                     "measured.")
    elif args.oracle_solve_rate < 1.0:
        fails.append(f"T.8/T.9 — the oracle solves only {args.oracle_solve_rate:.1%} of tasks. The remainder are "
                     f"impossible, not hard. Remove them or fix them; leaving them in caps every agent's ceiling "
                     f"and makes cross-paper comparison meaningless.")
    if state("T.5") == "no":
        fails.append("T.5 — the agent is NOT isolated from ground truth. This is the SWE-Lancer failure: agents "
                     "reached the benchmark's own test files and overwrote them with a trivial assertion, "
                     "scoring 100% without solving anything.")
    if state("T.6") == "no":
        fails.append("T.6 — the environment is not frozen. This is the OSWorld failure: live websites changed, "
                     "13/46 Chrome tasks broke, and the SOTA agent was UNDER-rated by 28% absolute. An unfrozen "
                     "environment makes results non-comparable across time, in both directions.")
    if state("T.4") == "no":
        fails.append("T.4 — state is not cleared between runs. This is the KernelBench failure: ground-truth "
                     "answers left in GPU memory were readable via out-of-bounds access. It also breaks the "
                     "independence assumption your statistics rely on.")
    if "llm-judge" in args.outcome_method and state("O.c.1") != "yes":
        fails.append("O.c.1 — an LLM judge is the grader but its accuracy, self-consistency and human agreement "
                     "are not evidenced. Reliability is not validity: a judge that always picks option A is "
                     "perfectly self-consistent AND maximally position-biased. Same-verdict rates fall from >95% "
                     "at temperature 0 to ~70% at temperature 1. Validate it against human labels first, or use "
                     "a deterministic grader as the primary metric and keep the judge exploratory.")
    na_no_reason = [r["id"] for r in rows
                    if r["mandatory"] and r["state"] == "na" and not (r.get("evidence") or "").strip()]
    if na_no_reason:
        blocks.append(f"{len(na_no_reason)} MANDATORY item(s) marked 'na' with no justification: "
                      f"{', '.join(na_no_reason)}. Marking a mandatory check not-applicable removes it from "
                      "the audit entirely, so it needs a reason: use "
                      '{"answer": "na", "evidence": "<why this cannot apply>"}.')
    unanswered = [r["id"] for r in rows if r["mandatory"] and r["state"] == "unanswered"]
    if unanswered:
        blocks.append(f"{len(unanswered)} mandatory item(s) unanswered: {', '.join(unanswered)}. "
                      "'Not looked at' is not 'fine' — 80% of surveyed benchmarks failed to acknowledge "
                      "weaknesses they had.")
    no_items = [r["id"] for r in rows if r["mandatory"] and r["state"] == "no" and r["id"] not in
                ("T.4", "T.5", "T.6", "O.c.1")]
    gate = "FAIL" if fails else ("BLOCKED" if blocks else "PASS")
    return gate, fails, blocks, no_items


def write_report(out_dir, rows, scores, trivial, gate, fails, blocks, no_items, args, ph):
    badge = {"PASS": "🟢 PASS", "FAIL": "🔴 FAIL", "BLOCKED": "🟡 BLOCKED"}[gate]
    tri_rows = []
    for agent, v in sorted((trivial or {}).items()):
        verdict = "🔴 scores above tolerance" if v["rate"] > args.trivial_tolerance else "🟢 ~0"
        tri_rows.append(f"| `{agent}` | {v['passed']}/{v['n']} | **{v['rate']:.1%}** | {verdict} |")
    tri = "\n".join(tri_rows) or "| _(not run)_ | — | — | 🟡 gate blocked |"

    sec_rows = []
    for name, v in sorted(scores.items()):
        pct = "—" if v["score"] is None else f"{v['score']:.0%}"
        sec_rows.append(f"| {name} | {v['yes']} | {v['no']} | {v['unanswered']} | {pct} |")
    sec = "\n".join(sec_rows)

    worst_trivial = ("must score ~0" if not trivial
                     else f"max {max(v['rate'] for v in trivial.values()):.1%}")
    oracle_txt = "not supplied" if args.oracle_solve_rate is None else f"{args.oracle_solve_rate:.1%}"
    problems = "\n".join(f"- 🔴 {f}" for f in fails) + "\n" + "\n".join(f"- 🟡 {b}" for b in blocks)
    unmet = ", ".join(f"`{i}`" for i in no_items) or "none"
    md = f"""# Eval-task validity audit — gate {badge}

## At a glance
```mermaid
flowchart LR
    TV["task validity<br/>{scores.get('task', {}).get('yes', 0)}✓ / {scores.get('task', {}).get('no', 0)}✗"] --> G{{"GATE"}}
    OV["outcome validity<br/>{scores.get('outcome', {}).get('yes', 0)}✓ / {scores.get('outcome', {}).get('no', 0)}✗"] --> G
    RP["reporting<br/>{scores.get('reporting', {}).get('yes', 0)}✓ / {scores.get('reporting', {}).get('no', 0)}✗"] --> G
    TR["trivial agents<br/>{worst_trivial}"] --> G
    OR["oracle solve rate<br/>{oracle_txt}"] --> G
    G -->|"{gate}"| N["{'run the experiment' if gate == 'PASS' else 'FIX THE TASK — do not run'}"]
```

**Gate: {badge}** · prereg `{ph}` · outcome method(s): {', '.join(args.outcome_method)}

| Section | ✓ | ✗ | unanswered | score |
|---|--:|--:|--:|--:|
{sec}

### Trivial-agent probe (ABC R.13)
| Agent | passed | rate | verdict |
|---|--:|--:|---|
{tri}

An agent with none of the target capability must score ~0. If it does not, the gap is the benchmark
rewarding something other than the capability, and it is present in every later number.

### Blocking problems
{problems if (fails or blocks) else "- none"}

### Non-blocking items answered NO
{unmet} — these do not stop the experiment but each one must appear in `write-findings` as a stated
limitation with its likely direction and size (ABC R.7-R.9).

## What this audit does and does not do
- ✅ It refuses to let a broken instrument be paid for. 7/10 surveyed benchmarks violate task validity
  and 7/10 violate outcome validity; the resulting errors reach 100% in relative terms.
- ⛔ It does **not** make an invalid task valid. Fixing a task is human work; this only detects and blocks.
- ⛔ A PASS is not a guarantee of validity, only the absence of the *known* failure modes. Unknown
  shortcuts remain possible — the outlier check in T.10 (agents failing every easy task, or succeeding
  only on hard ones) is the cheapest way to find them during the pilot.

## Next
{'→ `scaffold-trials` — generate the runner.' if gate == 'PASS' else '→ fix the task, then re-run this audit. Nothing downstream will accept a non-PASS gate.'}
"""
    with open(os.path.join(out_dir, "task_validity_report.md"), "w") as f:
        f.write(md)


def main():
    ap = argparse.ArgumentParser(description="ABC validity audit of an agent eval task. This is a gate.")
    ap.add_argument("--answers", help="JSON of ABC answers: {\"T.1\": true, \"T.4\": \"na\", ...}")
    ap.add_argument("--outcome-method", action="append", default=[],
                    choices=["string-match", "substring-match", "llm-judge", "unit-test", "fuzz-test",
                             "e2e-test", "state-match", "answer-match", "quality-measure"],
                    help="Repeatable. How task outcomes are graded — selects the applicable O.* items.")
    ap.add_argument("--uses-tools", action="store_true", help="Agent is given tools/APIs (enables T.1-T.3).")
    ap.add_argument("--uses-env", action="store_true", help="Tasks run in a sandbox/environment (enables T.4, T.6).")
    ap.add_argument("--trivial-results", help="jsonl from trivial_probe.py. Required for a PASS.")
    ap.add_argument("--oracle-solve-rate", type=float, help="Fraction of tasks a reference solver solves. Must be 1.0.")
    ap.add_argument("--trivial-tolerance", type=float, default=0.0,
                    help="Max acceptable trivial-agent pass rate (default 0.0).")
    ap.add_argument("--ack-trivial-tolerance",
                    help="Justification required whenever --trivial-tolerance > 0. Stamped into the sidecar.")
    ap.add_argument("--min-trivial-agents", type=int, default=3,
                    help="Minimum distinct trivial agents that must be probed (default 3).")
    ap.add_argument("--min-trivial-tasks", type=int, default=20,
                    help="Minimum tasks each trivial agent must be probed on (default 20).")
    ap.add_argument("--prereg", help="prereg.json. Required unless --emit-probe; binds this audit to one "
                                     "hypothesis so a foreign audit cannot be reused downstream.")
    ap.add_argument("--out-dir", default=".", help="Where to write the sidecar, report and trivial_probe.py.")
    ap.add_argument("--emit-probe", action="store_true", help="Write trivial_probe.py and exit.")
    args = ap.parse_args()

    try:
        os.makedirs(args.out_dir, exist_ok=True)
        probe_path = os.path.join(args.out_dir, "trivial_probe.py")
        if not os.path.exists(probe_path):
            with open(probe_path, "w") as f:
                f.write(TRIVIAL_PROBE)
            os.chmod(probe_path, 0o755)
    except OSError as e:
        die(f"Could not write to {args.out_dir}: {e}", 2)
    if args.emit_probe:
        print(f"Wrote {probe_path}. Wire up load_tasks()/score() against YOUR real grader, run it, "
              "then pass --trivial-results.")
        return

    if not args.outcome_method:
        die("--outcome-method is required (repeatable). How a task is graded decides which outcome-validity "
            "checks apply, and grading is where most agent benchmarks break.", 3)
    answers = {}
    if args.answers:
        if not os.path.exists(args.answers):
            die(f"No answers file at {args.answers}.", 3)
        try:
            with open(args.answers) as f:
                answers = json.load(f)
        except json.JSONDecodeError as e:
            die(f"{args.answers} is not valid JSON: {e}", 3)
        if not isinstance(answers, dict):
            die(f"{args.answers} must be a JSON object mapping item ids to answers.", 3)

    if not args.prereg:
        die("--prereg is required. Without it the audit is not bound to any hypothesis, and a PASSing "
            "audit from a different experiment could be handed to scaffold-trials unchallenged.", 3)
    if not os.path.exists(args.prereg):
        die(f"No prereg at {args.prereg}. (A typo here used to degrade silently to an unbound audit.)", 3)
    with open(args.prereg) as f:
        ph = prereg_hash(json.load(f))

    trivial = None
    if args.trivial_results:
        if not os.path.exists(args.trivial_results):
            die(f"No trivial results at {args.trivial_results}.", 3)
        trivial = read_trivial(args.trivial_results)

    rows, scores = score_sections(ABC, answers, set(args.outcome_method), args.uses_tools, args.uses_env)
    gate, fails, blocks, no_items = evaluate_gate(rows, trivial, args)

    probe_digest = None
    if args.trivial_results:
        with open(args.trivial_results, "rb") as f:
            probe_digest = hashlib.sha256(f.read()).hexdigest()[:16]
    sidecar = {"gate": gate, "prereg_hash": ph, "outcome_methods": args.outcome_method,
               "trivial_results_path": args.trivial_results, "trivial_results_sha256": probe_digest,
               "trivial_tolerance_acked": args.ack_trivial_tolerance,
               "declared_by_user": {"uses_tools": args.uses_tools, "uses_env": args.uses_env,
                                    "outcome_method": args.outcome_method,
                                    "oracle_solve_rate": args.oracle_solve_rate},
               "section_scores": scores, "trivial_agents": trivial,
               "oracle_solve_rate": args.oracle_solve_rate, "trivial_tolerance": args.trivial_tolerance,
               "blocking_failures": fails, "blocking_gaps": blocks,
               "non_blocking_no_items": no_items, "items": rows}
    tv_path = os.path.join(args.out_dir, "task_validity.json")
    history = []
    if os.path.exists(tv_path):
        try:
            with open(tv_path) as f:
                prev = json.load(f)
            history = prev.get("audit_history", [])
            history.append({"gate": prev.get("gate"), "prereg_hash": prev.get("prereg_hash"),
                            "trivial_results_sha256": prev.get("trivial_results_sha256"),
                            "blocking_failures": prev.get("blocking_failures"),
                            "blocking_gaps": prev.get("blocking_gaps")})
        except (json.JSONDecodeError, OSError):
            history = [{"gate": "UNREADABLE_PRIOR_AUDIT"}]
    sidecar["audit_history"] = history
    sidecar["n_prior_audits"] = len(history)
    try:
        with open(tv_path, "w") as f:
            json.dump(sidecar, f, indent=2)
        write_report(args.out_dir, rows, scores, trivial, gate, fails, blocks, no_items, args, ph)
    except OSError as e:
        die(f"Could not write to {args.out_dir}: {e}", 2)

    print(f"ABC audit written: {os.path.join(args.out_dir, 'task_validity_report.md')}")
    if gate == "PASS":
        print("\nGATE: 🟢 PASS — the known failure modes are absent. Proceed to scaffold-trials.")
        if history:
            eprint(f"  ⚠️  This is audit #{len(history) + 1} of the same task; the {len(history)} earlier "
                   f"verdict(s) {[h.get('gate') for h in history]} are kept in audit_history. Re-auditing "
                   "until it passes is the audit equivalent of seed shopping — make sure the TASK changed, "
                   "not just the answers.")
        if no_items:
            eprint(f"  ({len(no_items)} non-blocking item(s) answered NO: {', '.join(no_items)} — these must "
                   "be reported as limitations, with direction and size.)")
        return
    eprint(f"\nGATE: {'🔴 FAIL' if gate == 'FAIL' else '🟡 BLOCKED'} — do NOT run the experiment yet.\n")
    for f_ in fails:
        eprint(f"  🔴 {f_}\n")
    for b in blocks:
        eprint(f"  🟡 {b}\n")
    eprint("Every downstream skill refuses a non-PASS gate. Fix the task, then re-audit.")
    sys.exit(5)


if __name__ == "__main__":
    main()
