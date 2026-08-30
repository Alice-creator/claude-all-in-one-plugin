#!/usr/bin/env python3
"""scaffold-trials: generate a RUNNABLE trial harness — then STOP.

It scaffolds the runner; it does NOT run your experiment. Real rollouts are your API spend, the
same boundary cv-modeler draws around GPU-hours (HAL spent ~$40k on 21,730 rollouts). This script:
  - REFUSES unless task_validity.json says gate == PASS. Paying to run a benchmark that a
    do-nothing agent can pass is the failure this pipeline exists to prevent.
  - Generates run_trials.py: K runs per task per config, resumable, hard cost ceiling, per-line
    flush (a crash keeps what it already paid for), an explicit reset_env() hook between runs
    (ABC T.4), and a recorded task ORDER seed — order is not neutral, WebArena's Reddit clone
    rate-limits consecutive posts and silently fails whichever agent went last.
  - Stamps prereg_hash and a config hash into EVERY row, so analyze-trials can detect a hypothesis
    or metric edited after the results existed.
  - Emits the trials.jsonl contract the rest of the pipeline reads: one row per single run.
  - SMOKE TESTS the generated runner against a built-in mock agent (no API key, no cost) and
    asserts the output rows parse and carry every required field. A green smoke proves the harness
    runs; it is NOT a result.

Exit codes: 0 ok · 2 dependency/IO issue · 3 bad/missing input · 4 refused.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical
across scripts); `prereg_hash` MUST stay identical everywhere it appears.
"""
import argparse
import hashlib
import json
import os
import subprocess
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


TRIAL_FIELDS = ["task_id", "config_id", "run_idx", "success", "cost_usd", "latency_s",
                "n_llm_calls", "model_version", "prereg_hash", "config_hash", "error", "trace_path",
                "order_seed"]

RUNNER = '''#!/usr/bin/env python3
"""run_trials.py — execute the experiment. THIS is the step that costs money.

Emits trials.jsonl: ONE ROW PER SINGLE RUN. Downstream skills read only this file.
  {json_schema}

Resumable: re-running skips (task_id, config_id, run_idx) triples already present, so an
interrupted run costs nothing twice. Stops hard at --budget-usd.

WIRE UP load_tasks(), run_agent() and reset_env() below, then:
    python run_trials.py --budget-usd {budget}
"""
import argparse, hashlib, json, os, random, time

PREREG_HASH = "{prereg_hash}"
MODEL_VERSION = "{model_version}"


def load_tasks():
    """TODO: return the eval tasks as a list of dicts, each with at least 'id'.

    Use the HELD-OUT set the design calls for ({holdout}). Developing against the same tasks you
    report on is how agents that took shortcuts came to look general."""
    raise NotImplementedError("load_tasks(): return your held-out eval tasks")


def reset_env(task):
    """TODO: clear residual state BEFORE each run (ABC T.4).

    Not optional and not cosmetic: KernelBench left ground-truth answers in GPU memory where agents
    read them out of bounds. Leftover state also breaks the independence your statistics assume."""
    pass


def run_agent(task, config):
    """TODO: run ONE attempt. Return dict(success: bool, cost_usd: float, n_llm_calls: int,
    trace: list|None, error: str|None).

    `config` is one entry from configs.json — the ONLY thing that may differ between arms. If two
    things differ, the experiment cannot attribute the result to either."""
    raise NotImplementedError("run_agent(): run one attempt and report success + cost")


def mock_agent(task, config):
    """Built-in, free, no API key. Used by the smoke test to prove the harness works."""
    rng = random.Random(f"{{task['id']}}|{{config['id']}}|{{config.get('seed', 0)}}")
    time.sleep(0.001)
    return {{"success": rng.random() < config.get("mock_rate", 0.5), "cost_usd": 0.0,
             "n_llm_calls": 1, "trace": [{{"step": 0, "action": "mock"}}], "error": None}}


def config_hash(config):
    canon = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def already_done(path):
    done = set()
    if not os.path.exists(path):
        return done
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add((r.get("task_id"), r.get("config_id"), r.get("run_idx")))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="configs.json")
    ap.add_argument("--out", default="trials.jsonl")
    ap.add_argument("--k-runs", type=int, default={k_runs})
    ap.add_argument("--budget-usd", type=float, default={budget})
    ap.add_argument("--order-seed", type=int, default=0,
                    help="Task order is recorded because it is NOT neutral (shared rate limits, shared state).")
    ap.add_argument("--traces-dir", default="traces")
    ap.add_argument("--mock", action="store_true", help="Run the free built-in agent. Proves plumbing, not results.")
    a = ap.parse_args()

    with open(a.configs) as f:
        configs = json.load(f)["configs"]
    tasks = [{{"id": f"mock-{{i}}"}} for i in range(4)] if a.mock else load_tasks()
    os.makedirs(a.traces_dir, exist_ok=True)
    done, spent, written = already_done(a.out), 0.0, 0
    order = list(range(len(tasks)))
    random.Random(a.order_seed).shuffle(order)
    agent = mock_agent if a.mock else run_agent

    with open(a.out, "a") as out:
        for run_idx in range(a.k_runs):
            for ti in order:
                task = tasks[ti]
                for config in configs:
                    key = (task["id"], config["id"], run_idx)
                    if key in done:
                        continue
                    if spent >= a.budget_usd:
                        print(f"BUDGET REACHED (${{spent:.2f}}) — stopping. Re-run to resume after raising it.")
                        print(f"INCOMPLETE: {{written}} rows written. Do NOT analyse a truncated grid as if "
                              f"it were the planned design; the missing cells are not random.")
                        return
                    reset_env(task)
                    t0 = time.time()
                    try:
                        r = agent(task, config)
                    except Exception as e:  # a crashed run is DATA, not a gap to silently drop
                        r = {{"success": False, "cost_usd": 0.0, "n_llm_calls": 0,
                              "trace": None, "error": f"{{type(e).__name__}}: {{e}}"}}
                    latency = round(time.time() - t0, 3)
                    trace_path = None
                    if r.get("trace") is not None:
                        trace_path = os.path.join(a.traces_dir, f"{{task['id']}}__{{config['id']}}__{{run_idx}}.json")
                        with open(trace_path, "w") as tf:
                            json.dump(r["trace"], tf)
                    spent += float(r.get("cost_usd") or 0.0)
                    out.write(json.dumps({{
                        "task_id": task["id"], "config_id": config["id"], "run_idx": run_idx,
                        "success": bool(r.get("success")), "cost_usd": float(r.get("cost_usd") or 0.0),
                        "latency_s": latency, "n_llm_calls": int(r.get("n_llm_calls") or 0),
                        "model_version": MODEL_VERSION, "prereg_hash": PREREG_HASH,
                        "config_hash": config_hash(config), "error": r.get("error"),
                        "trace_path": trace_path, "order_seed": a.order_seed,
                    }}) + "\\n")
                    out.flush()
                    written += 1
    print(f"done: {{written}} new rows -> {{a.out}} (spent ${{spent:.2f}})")
    if a.mock:
        print("THIS WAS A MOCK RUN. The numbers are random; they are not a result.")


if __name__ == "__main__":
    main()
'''

README = """# Trial bundle — {hypothesis}

## At a glance
```mermaid
flowchart LR
    C["configs.json<br/>baseline vs treatment"] --> R["run_trials.py<br/>K={k_runs} runs/task/config"]
    Y["YOU wire up:<br/>load_tasks · run_agent · reset_env"] --> R
    R -->|"💸 your API spend<br/>hard cap ${budget}"| T["trials.jsonl<br/>one row per run"]
    R -.->|"--mock: free, random<br/>NOT a result"| SM["smoke rows"]
    T --> A["analyze-trials"]
    T --> D["diagnose-failures"]
```

`prereg_hash` **{prereg_hash}** · gate **PASS** · holdout **{holdout}** · K={k_runs} · budget ${budget}

## Run order
```bash
pip install -r requirements.txt
python run_trials.py --mock                 # free; proves the harness runs (NOT a result)
# wire up load_tasks() / run_agent() / reset_env() in run_trials.py, then:
python run_trials.py --budget-usd {budget}  # 💸 YOUR API spend
```

## The three functions you must write
| Function | Why it is yours |
|---|---|
| `load_tasks()` | Must return the **{holdout}** holdout. Reporting on tasks you developed against is the shortcut the design gate exists to prevent. |
| `run_agent()` | Only `config` may differ between arms. Two changes at once and the result attributes to neither. |
| `reset_env()` | ABC T.4. KernelBench left ground truth in GPU memory and agents read it out of bounds. |

## What this bundle is / isn't
- ✅ Resumable, budget-capped, per-row flushed, order-seeded, prereg-stamped.
- ⛔ **Not results.** `--mock` numbers are random by construction.
- ⛔ Not a validity guarantee. The gate cleared the *known* failure modes only.

## Next
→ `analyze-trials` on `trials.jsonl` (clustered bootstrap CI, paired difference, cost Pareto).
"""


def require_pass_gate(path):
    if not os.path.exists(path):
        die(f"No task_validity.json at {path}. Run validate-eval-task first — this pipeline does not "
            "generate a runner for an unaudited task, because the audit is the cheap step and the "
            "rollouts are the expensive one.", 3)
    with open(path) as f:
        tv = json.load(f)
    gate = tv.get("gate")
    # Do not trust the `gate` string on its own: re-derive it from the evidence in the same file, so
    # flipping "FAIL" to "PASS" by hand while leaving the failures in place does not get through.
    derived = []
    if tv.get("blocking_failures"):
        derived.append(f"{len(tv['blocking_failures'])} blocking failure(s) recorded in the sidecar")
    if tv.get("blocking_gaps"):
        derived.append(f"{len(tv['blocking_gaps'])} blocking gap(s) recorded in the sidecar")
    tol = tv.get("trivial_tolerance") or 0.0
    for agent, v in sorted((tv.get("trivial_agents") or {}).items()).__iter__():
        if isinstance(v, dict) and (v.get("rate") or 0.0) > tol:
            derived.append(f"trivial agent '{agent}' scores {v['rate']:.1%} > tolerance {tol:.1%}")
    if not tv.get("trivial_agents"):
        derived.append("no trivial-agent results recorded")
    osr = tv.get("oracle_solve_rate")
    if osr is None or osr < 1.0:
        derived.append(f"oracle solve rate is {osr}, not 1.0")
    if derived and gate == "PASS":
        die("REFUSED — task_validity.json says gate PASS, but its own contents contradict that:\n  - " +
            "\n  - ".join(derived) +
            "\n\nThe gate value was not produced by the audit that is recorded in this file. Re-run "
            "validate-eval-task rather than editing its output.", 4)
    if gate != "PASS":
        problems = (tv.get("blocking_failures") or []) + (tv.get("blocking_gaps") or [])
        die(f"REFUSED — task_validity gate is {gate}, not PASS. Generating a runner now would spend real "
            "money measuring a task that is known to be broken.\n\n  - " +
            "\n\n  - ".join(problems or ["(no detail recorded)"]) +
            "\n\nFix the task, re-run validate-eval-task, then come back.", 4)
    return tv


def smoke(bundle):
    """Execute the generated runner against the mock and verify the OUTPUT, not just the exit code."""
    out = os.path.join(bundle, "smoke_trials.jsonl")
    if os.path.exists(out):
        os.remove(out)
    try:
        proc = subprocess.run([sys.executable, "run_trials.py", "--mock", "--k-runs", "2",
                               "--out", "smoke_trials.jsonl", "--traces-dir", "smoke_traces"],
                              cwd=bundle, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"executed": False, "reason": f"{type(e).__name__}: {e}", "rows": 0}
    if proc.returncode != 0:
        return {"executed": False, "reason": (proc.stderr or "").strip()[-500:], "rows": 0}
    rows = []
    with open(out) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    missing = sorted({fld for r in rows for fld in TRIAL_FIELDS if fld not in r})
    return {"executed": True, "rows": len(rows), "missing_fields": missing,
            "schema_ok": not missing and len(rows) > 0,
            "reason": "" if rows else "runner produced no rows"}


def main():
    ap = argparse.ArgumentParser(description="Generate a runnable, budget-capped trial harness.")
    ap.add_argument("--prereg", required=True)
    ap.add_argument("--design", required=True, help="experiment_design.json")
    ap.add_argument("--task-validity", required=True, help="task_validity.json — must say gate PASS")
    ap.add_argument("--model-version", required=True,
                    help="Exact model id INCLUDING date. Endpoints drift; 'the latest one' is not reproducible.")
    ap.add_argument("--config", action="append", default=[],
                    help="Repeatable config id. First is the baseline arm. Default: baseline,treatment")
    ap.add_argument("--out-dir", default="trials_bundle")
    args = ap.parse_args()

    for path in (args.prereg, args.design):
        if not os.path.exists(path):
            die(f"Missing {path}.", 3)
    tv = require_pass_gate(args.task_validity)
    with open(args.prereg) as f:
        p = json.load(f)
    with open(args.design) as f:
        d = json.load(f)
    ph = prereg_hash(p)
    if tv.get("prereg_hash") != ph:
        die(f"REFUSED — the validity audit is bound to prereg {tv.get('prereg_hash')} but this prereg is "
            f"{ph}. Either the hypothesis changed after the task was audited, or an audit from a different "
            f"experiment was supplied. Re-audit this task against this prereg before running.", 4)

    ids = args.config or ["baseline", "treatment"]
    configs = {"baseline_config_id": ids[0],
               "configs": [{"id": i, "seed": 42, "mock_rate": 0.5 + 0.08 * n} for n, i in enumerate(ids)]}
    bundle = args.out_dir
    try:
        os.makedirs(bundle, exist_ok=True)
        runner = RUNNER.format(
            json_schema=json.dumps({k: "..." for k in TRIAL_FIELDS}),
            prereg_hash=ph, model_version=args.model_version, k_runs=d["k_runs"],
            budget=d["budget_usd"], holdout=d.get("holdout", "unspecified"))
        with open(os.path.join(bundle, "run_trials.py"), "w") as f:
            f.write(runner)
        os.chmod(os.path.join(bundle, "run_trials.py"), 0o755)
        with open(os.path.join(bundle, "configs.json"), "w") as f:
            json.dump(configs, f, indent=2)
        with open(os.path.join(bundle, "requirements.txt"), "w") as f:
            f.write("# run_trials.py is stdlib-only. Add YOUR agent's deps here, pinned.\n")
        with open(os.path.join(bundle, "README.md"), "w") as f:
            f.write(README.format(hypothesis=p["hypothesis"], prereg_hash=ph, k_runs=d["k_runs"],
                                  budget=d["budget_usd"], holdout=d.get("holdout", "unspecified")))
    except OSError as e:
        die(f"Could not write bundle to {bundle}: {e}", 2)

    s = smoke(bundle)
    manifest = {"bundle_path": os.path.abspath(bundle), "prereg_hash": ph,
                "gate": tv["gate"], "model_version": args.model_version,
                "k_runs": d["k_runs"], "budget_usd": d["budget_usd"],
                "config_ids": ids, "baseline_config_id": ids[0],
                "holdout": d.get("holdout"), "trial_fields": TRIAL_FIELDS,
                "smoke": s, "produces_results": False, "smoke_rows_are_mock": True}
    with open(os.path.join(bundle, "trials_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    if not s["executed"] or not s["schema_ok"]:
        die(f"Bundle written to {bundle}, but the SMOKE TEST FAILED: {s.get('reason') or s}. "
            f"{'Missing fields: ' + ', '.join(s['missing_fields']) if s.get('missing_fields') else ''}\n"
            "Do not run this against a paid API until the mock run produces valid rows.", 2)

    print(f"Bundle ✅  {bundle}  ·  prereg_hash={ph}  ·  gate=PASS")
    print(f"  smoke: ran the real runner on the mock agent, {s['rows']} rows, all "
          f"{len(TRIAL_FIELDS)} required fields present")
    print(f"  configs: {', '.join(ids)} (baseline = {ids[0]})  ·  K={d['k_runs']}  ·  cap ${d['budget_usd']}")
    print("\n⛔ produces_results: false — the smoke rows are MOCK and random by construction.")
    print("Next: wire up load_tasks()/run_agent()/reset_env(), run it (your API spend), then analyze-trials.")


if __name__ == "__main__":
    main()
