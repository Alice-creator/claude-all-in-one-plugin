#!/usr/bin/env python3
"""Attack suite for the agent-researcher pipeline's safety guarantees.

Every case here is a bypass that a review round actually found and that is now fixed. The pipeline's
value is entirely in its refusals, so a silently weakened refusal is the worst possible regression:
it does not crash, it produces a confident wrong answer. This locks each one down.

Run: python3 tests/check_research_gates.py   (exit 0 = all guarantees hold, 1 = a gate regressed)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable
S = os.path.join(ROOT, "skills")

ANSWERS = {f"T.{i}": True for i in range(1, 11)}
ANSWERS.update({"O.d.1": True, "O.d.2": False, "O.f.1": True, "O.f.2": True,
                "R.1": True, "R.2": True, "R.3": True, "R.4": False, "R.5": True, "R.6": True,
                "R.7": True, "R.8": True, "R.9": False, "R.10": True, "R.11": True,
                "R.12": False, "R.13": True})


def run(script, *args):
    proc = subprocess.run([PY, os.path.join(S, script), *[str(a) for a in args]],
                          capture_output=True, text=True, timeout=300)
    return proc.returncode, proc.stdout + proc.stderr


def probe(path, rates, key="success", n=50):
    import random
    rng = random.Random(1)
    with open(path, "w") as f:
        for agent, rate in rates:
            for i in range(n):
                f.write(json.dumps({"agent": agent, "task_id": f"t{i}", key: rng.random() < rate}) + "\n")


def trials(path, prereg_hash, n_tasks=60, k=5, lift=0.10, stamp=True, base=0.40):
    import random
    rng = random.Random(7)
    with open(path, "w") as f:
        for t in range(n_tasks):
            d = rng.betavariate(2, 2)
            for cfg, shift in (("baseline", 0.0), ("treatment", lift)):
                pr = min(0.98, max(0.02, base + (d - 0.5) * 0.8 + shift))
                for ri in range(k):
                    row = {"task_id": f"t{t}", "config_id": cfg, "run_idx": ri,
                           "success": rng.random() < pr, "cost_usd": 0.05, "latency_s": 1.0,
                           "n_llm_calls": 3, "model_version": "m-2026-05-01",
                           "config_hash": "a" * 16, "error": None, "trace_path": None,
                           "order_seed": 0}
                    if stamp:
                        row["prereg_hash"] = prereg_hash
                    f.write(json.dumps(row) + "\n")


CASES = []


def case(name, guarantee):
    def deco(fn):
        CASES.append((name, guarantee, fn))
        return fn
    return deco


def setup(d):
    """A clean, honestly-passing experiment to attack."""
    code, out = run("frame-research-question/scripts/prereg.py",
                    "--hypothesis", "Memory raises success rate", "--primary-metric", "success_rate",
                    "--baseline", "ReAct", "--min-effect", "0.05",
                    "--falsify", "the paired difference CI includes 0 or its upper bound is below 5 points",
                    "--out-dir", d)
    assert code == 0, out
    ph = json.load(open(os.path.join(d, "prereg.json")))["prereg_hash"]
    json.dump(ANSWERS, open(os.path.join(d, "answers.json"), "w"))
    probe(os.path.join(d, "clean.jsonl"), [("do_nothing", 0.0), ("dump_everything", 0.0), ("fixed_reply", 0.0)])
    return ph


def design(d, holdout="ood", n_tasks=60):
    return run("design-experiment/scripts/design.py", "--prereg", os.path.join(d, "prereg.json"),
               "--baseline-rate", "0.4", "--n-tasks", str(n_tasks), "--k-runs", "5",
               "--cost-per-run", "0.01", "--budget-usd", "5000", "--holdout", holdout, "--out-dir", d)


def audit(d, trivial="clean.jsonl", **kw):
    args = ["--answers", os.path.join(d, "answers.json"), "--outcome-method", "unit-test",
            "--uses-tools", "--uses-env", "--oracle-solve-rate", kw.pop("oracle", "1.0"),
            "--prereg", os.path.join(d, "prereg.json"), "--out-dir", d]
    if trivial:
        args += ["--trivial-results", os.path.join(d, trivial)]
    for k, v in kw.items():
        args += [f"--{k.replace('_', '-')}", str(v)]
    return run("validate-eval-task/scripts/validate_task.py", *args)


# ---------------- Guarantee C: a trivial agent above tolerance always FAILS ----------------
@case("empty probe file cannot PASS", "C")
def _(d, ph):
    open(os.path.join(d, "empty.jsonl"), "w").close()
    code, out = audit(d, "empty.jsonl")
    return code == 5, f"exit={code}"


@case("whitespace-only probe cannot PASS", "C")
def _(d, ph):
    open(os.path.join(d, "ws.jsonl"), "w").write("\n \n\t\n")
    code, out = audit(d, "ws.jsonl")
    return code == 5, f"exit={code}"


@case("probe writing 'passed' not 'success' is refused, not read as 0%", "C")
def _(d, ph):
    probe(os.path.join(d, "dirty.jsonl"), [("do_nothing", 0.48), ("dump_everything", 0.6)], key="passed")
    code, out = audit(d, "dirty.jsonl")
    return code == 3 and "malformed" in out, f"exit={code}"


@case("submitting only the trivial agent that scores 0 cannot PASS", "C")
def _(d, ph):
    probe(os.path.join(d, "one.jsonl"), [("fixed_reply", 0.0)])
    code, out = audit(d, "one.jsonl")
    return code == 5, f"exit={code}"


@case("a genuinely dirty probe FAILS", "C")
def _(d, ph):
    probe(os.path.join(d, "bad.jsonl"), [("do_nothing", 0.38), ("dump_everything", 0.0), ("fixed_reply", 0.0)])
    code, out = audit(d, "bad.jsonl")
    return code == 5 and "38" in out, f"exit={code}"


@case("non-zero --trivial-tolerance needs an explicit ack", "C")
def _(d, ph):
    probe(os.path.join(d, "bad2.jsonl"), [("do_nothing", 0.48), ("dump_everything", 0.6), ("fixed_reply", 0.0)])
    code, out = audit(d, "bad2.jsonl", trivial_tolerance="0.65")
    return code == 5, f"exit={code}"


# ---------------- Guarantee B: nothing proceeds past a failed gate ----------------
@case("all-'na' answers cannot PASS", "B")
def _(d, ph):
    json.dump({k: "na" for k in ANSWERS}, open(os.path.join(d, "answers.json"), "w"))
    code, out = audit(d)
    json.dump(ANSWERS, open(os.path.join(d, "answers.json"), "w"))
    return code == 5, f"exit={code}"


@case("--prereg typo does not silently unbind the audit", "B")
def _(d, ph):
    code, out = run("validate-eval-task/scripts/validate_task.py",
                    "--answers", os.path.join(d, "answers.json"), "--outcome-method", "unit-test",
                    "--trivial-results", os.path.join(d, "clean.jsonl"), "--oracle-solve-rate", "1.0",
                    "--prereg", os.path.join(d, "TYPO.json"), "--out-dir", d)
    return code == 3, f"exit={code}"


@case("hand-flipped gate:PASS is caught by re-derivation", "B")
def _(d, ph):
    design(d)
    probe(os.path.join(d, "flip.jsonl"), [("do_nothing", 0.38), ("dump_everything", 0.0),
                                          ("fixed_reply", 0.0)])
    audit(d, "flip.jsonl")
    tv = json.load(open(os.path.join(d, "task_validity.json")))
    tv["gate"] = "PASS"
    tv["blocking_failures"] = ["a real failure that was recorded"]
    json.dump(tv, open(os.path.join(d, "tv_edited.json"), "w"))
    code, out = run("scaffold-trials/scripts/scaffold_trials.py",
                    "--prereg", os.path.join(d, "prereg.json"),
                    "--design", os.path.join(d, "experiment_design.json"),
                    "--task-validity", os.path.join(d, "tv_edited.json"),
                    "--model-version", "m-2026-05-01", "--out-dir", os.path.join(d, "b1"))
    return code == 4 and "contradict" in out, f"exit={code}"


@case("analyze-trials refuses without a validity audit", "B")
def _(d, ph):
    trials(os.path.join(d, "trials.jsonl"), ph)
    code, out = run("analyze-trials/scripts/analyze.py", "--trials", os.path.join(d, "trials.jsonl"),
                    "--prereg", os.path.join(d, "prereg.json"), "--n-boot", "500", "--out-dir", d)
    return code == 4 and "VALIDITY" in out, f"exit={code}"


@case("write-findings refuses when the audit is omitted", "B")
def _(d, ph):
    trials(os.path.join(d, "trials.jsonl"), ph)
    audit(d)
    run("analyze-trials/scripts/analyze.py", "--trials", os.path.join(d, "trials.jsonl"),
        "--prereg", os.path.join(d, "prereg.json"), "--task-validity", os.path.join(d, "task_validity.json"),
        "--n-boot", "500", "--out-dir", d)
    code, out = run("write-findings/scripts/findings.py", "--prereg", os.path.join(d, "prereg.json"),
                    "--analysis", os.path.join(d, "analysis.json"), "--out-dir", d)
    return code == 3, f"exit={code}"


# ---------------- Guarantee A: a post-hoc hypothesis edit is always detected ----------------
@case("--amend cannot relax the prereg into unfalsifiability", "A")
def _(d, ph):
    code, out = run("frame-research-question/scripts/prereg.py", "--amend", "relax", "--out-dir", d,
                    "--min-effect", "0", "--primary-metric", "a,b,c", "--falsify", "no")
    return code == 4, f"exit={code}"


@case("unstamped trial rows are refused, not warned about", "A")
def _(d, ph):
    trials(os.path.join(d, "unstamped.jsonl"), ph, stamp=False)
    audit(d)
    code, out = run("analyze-trials/scripts/analyze.py", "--trials", os.path.join(d, "unstamped.jsonl"),
                    "--prereg", os.path.join(d, "prereg.json"),
                    "--task-validity", os.path.join(d, "task_validity.json"),
                    "--n-boot", "500", "--out-dir", d)
    return code == 4 and "prereg_hash" in out, f"exit={code}"


@case("a MIX of stamped and unstamped rows is refused", "A")
def _(d, ph):
    trials(os.path.join(d, "mix.jsonl"), ph)
    lines = open(os.path.join(d, "mix.jsonl")).read().splitlines()
    half = [json.dumps({k: v for k, v in json.loads(x).items() if k != "prereg_hash"})
            for x in lines[:len(lines) // 2]]
    open(os.path.join(d, "mix.jsonl"), "w").write("\n".join(half + lines[len(lines) // 2:]) + "\n")
    audit(d)
    code, out = run("analyze-trials/scripts/analyze.py", "--trials", os.path.join(d, "mix.jsonl"),
                    "--prereg", os.path.join(d, "prereg.json"),
                    "--task-validity", os.path.join(d, "task_validity.json"),
                    "--n-boot", "500", "--out-dir", d)
    return code == 4, f"exit={code}"


@case("escalating generality_level after results changes the hash", "A")
def _(d, ph):
    pr = json.load(open(os.path.join(d, "prereg.json")))
    pr["generality_level"] = "fully-general"
    json.dump(pr, open(os.path.join(d, "escalated.json"), "w"))
    code, out = run("design-experiment/scripts/design.py", "--prereg", os.path.join(d, "escalated.json"),
                    "--baseline-rate", "0.4", "--n-tasks", "100", "--k-runs", "5",
                    "--cost-per-run", "0.05", "--budget-usd", "500", "--holdout", "unseen-domains")
    return code == 4 and "edited by hand" in out, f"exit={code}"


@case("cosmetic whitespace edit does NOT cause a false HARKing alarm", "A")
def _(d, ph):
    pr = json.load(open(os.path.join(d, "prereg.json")))
    pr["hypothesis"] = "  Memory raises   success rate  "
    return prereg_hash_of(pr) == ph, "hash changed on a whitespace-only edit"


def prereg_hash_of(pr):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pg", os.path.join(S, "frame-research-question/scripts/prereg.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.prereg_hash(pr)


# ---------------- Data-shape attacks on the analysis ----------------
@case("a single shared task cannot yield SUPPORTED", "D")
def _(d, ph):
    trials(os.path.join(d, "tiny.jsonl"), ph, n_tasks=1, k=3, lift=0.9, base=0.05)
    audit(d)
    code, out = run("analyze-trials/scripts/analyze.py", "--trials", os.path.join(d, "tiny.jsonl"),
                    "--prereg", os.path.join(d, "prereg.json"),
                    "--task-validity", os.path.join(d, "task_validity.json"),
                    "--n-boot", "500", "--out-dir", d)
    return "SUPPORTED —" not in out, "a 1-task experiment produced a confirmatory verdict"


@case("string 'false' in success is refused, not read as truthy", "D")
def _(d, ph):
    trials(os.path.join(d, "str.jsonl"), ph, n_tasks=30)
    rows = [json.loads(x) for x in open(os.path.join(d, "str.jsonl")).read().splitlines()]
    for r in rows:
        r["success"] = "false"
    open(os.path.join(d, "str.jsonl"), "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
    audit(d)
    code, out = run("analyze-trials/scripts/analyze.py", "--trials", os.path.join(d, "str.jsonl"),
                    "--prereg", os.path.join(d, "prereg.json"),
                    "--task-validity", os.path.join(d, "task_validity.json"),
                    "--n-boot", "500", "--out-dir", d)
    return code == 4 and "not a bool" in out, f"exit={code}"


# ---------------- Kappa / taxonomy ----------------
@case("two annotators using one category do not score kappa 1.0", "K")
def _(d, ph):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dg", os.path.join(S, "diagnose-failures/scripts/diagnose.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    k, _n = m.cohens_kappa({i: "OTHER" for i in range(40)}, {i: "OTHER" for i in range(40)})
    return k is None, f"kappa={k}"


# ---------------- Design sizing ----------------
@case("--icc and --k-runs actually move the power verdict", "P")
def _(d, ph):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "de", os.path.join(S, "design-experiment/scripts/design.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    got = {m.tasks_required(236, 5, icc) for icc in (0.0, 0.5, 1.0)}
    return len(got) == 3 and m.tasks_required(236, 5, 0.5) == 142, f"tasks_required={sorted(got)}"


@case("an infeasible paired design (effect > discordance) is refused", "P")
def _(d, ph):
    code, out = run("design-experiment/scripts/design.py", "--prereg", os.path.join(d, "prereg.json"),
                    "--baseline-rate", "0.4", "--n-tasks", "100", "--k-runs", "5",
                    "--cost-per-run", "0.01", "--budget-usd", "500", "--holdout", "ood",
                    "--paired", "--paired-discordance", "0.01")
    return code == 4 and "INFEASIBLE" in out, f"exit={code}"


@case("--k-runs 0 is rejected, not a ZeroDivisionError", "P")
def _(d, ph):
    code, out = run("design-experiment/scripts/design.py", "--prereg", os.path.join(d, "prereg.json"),
                    "--baseline-rate", "0.4", "--n-tasks", "100", "--k-runs", "0", "--icc", "1.0",
                    "--cost-per-run", "0.01", "--budget-usd", "500", "--holdout", "ood")
    return code == 3 and "Traceback" not in out, f"exit={code}"


def main():
    failures = []
    for name, guarantee, fn in CASES:
        d = tempfile.mkdtemp(prefix="resgate_")
        try:
            ph = setup(d)
            ok, detail = fn(d, ph)
            if ok:
                print(f"  ok  [{guarantee}] {name}")
            else:
                failures.append(f"[{guarantee}] {name} — {detail}")
                print(f"  ✗   [{guarantee}] {name} — {detail}")
        except Exception as e:  # a crashed case is a failed case
            failures.append(f"[{guarantee}] {name} — raised {type(e).__name__}: {e}")
            print(f"  ✗   [{guarantee}] {name} — raised {type(e).__name__}: {e}")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print()
    if failures:
        print(f"GATE REGRESSION — {len(failures)} of {len(CASES)} guarantees broken:", file=sys.stderr)
        for f in failures:
            print(f"  ✗ {f}", file=sys.stderr)
        sys.exit(1)
    print(f"All {len(CASES)} research-pipeline guarantees hold ✅")


if __name__ == "__main__":
    main()
