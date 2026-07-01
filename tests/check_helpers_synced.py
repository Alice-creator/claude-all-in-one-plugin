#!/usr/bin/env python3
"""Guard against drift in the helpers that are deliberately COPIED byte-identical
across skill scripts (the plugin keeps skills self-contained instead of importing a
shared module). This asserts each such helper is identical everywhere it is supposed
to be — turning the "must stay in sync" comment into an enforced check.

Run: python3 tests/check_helpers_synced.py   (exit 0 = in sync, 1 = drift, 2 = setup error)

Intentional divergences are simply NOT grouped together (documented inline):
- split-dataset has its own richer load()/find_split()/infer_task() (handles xlsx/json,
  a y=None 'unknown' task) — excluded.
- profile-dataset/build-chart/verify-analysis have their own loaders — excluded.
- fmt has two intended variants (plain vs None/nan-aware) — checked as two groups.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPTS = {
    "baseline": "skills/baseline/scripts/baseline.py",
    "train-tune": "skills/train-tune/scripts/train_tune.py",
    "select-model": "skills/select-model/scripts/select_model.py",
    "check-drift": "skills/check-drift/scripts/check_drift.py",
    "evaluate-model": "skills/evaluate-model/scripts/evaluate.py",
    # game-agent pipeline
    "scaffold-submission": "skills/scaffold-submission/scripts/scaffold_submission.py",
    "baseline-agent": "skills/baseline-agent/scripts/baseline_agent.py",
    "self-play-eval": "skills/self-play-eval/scripts/self_play_eval.py",
    "profile-agent": "skills/profile-agent/scripts/profile_agent.py",
    # agent-security pipeline
    "run-redteam-eval": "skills/run-redteam-eval/scripts/run_redteam_eval.py",
    "harden-agent": "skills/harden-agent/scripts/harden_agent.py",
}

# (function name, [skills whose definition must be byte-identical])
GROUPS = [
    # modeling pipeline (tabular)
    ("infer_task", ["baseline", "train-tune", "select-model", "evaluate-model"]),
    ("load", ["baseline", "train-tune", "select-model", "check-drift", "evaluate-model"]),
    ("find_split", ["baseline", "train-tune", "select-model", "check-drift"]),
    ("build_preprocessor", ["baseline", "train-tune"]),
    ("clf_metrics", ["baseline", "train-tune"]),
    ("reg_metrics", ["baseline", "train-tune"]),
    ("enforce_test_lock", ["baseline", "train-tune"]),
    ("fmt", ["baseline", "train-tune", "check-drift", "evaluate-model"]),  # None/nan-aware modeling variant
    # game-agent + agent-security pipelines (a simpler {:.3f}/str fmt — its own group, NOT the modeling one)
    ("fmt", ["baseline-agent", "self-play-eval", "profile-agent", "run-redteam-eval", "harden-agent"]),
    ("agent_count", ["scaffold-submission", "baseline-agent", "self-play-eval"]),  # kaggle_environments player-count
    ("outcome", ["baseline-agent", "self-play-eval"]),  # win/draw/loss from episode rewards
]


def func_source(path, name):
    with open(path) as f:
        src = f.read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    return None


def main():
    failures = []
    for fn, skills in GROUPS:
        sources = {}
        for s in skills:
            path = os.path.join(ROOT, SCRIPTS[s])
            seg = func_source(path, fn)
            if seg is None:
                failures.append(f"{fn}: not found in {s} ({SCRIPTS[s]}) — group misconfigured or function renamed")
            else:
                sources[s] = seg
        distinct = set(sources.values())
        if len(distinct) > 1:
            have = {s: hash(seg) & 0xffff for s, seg in sources.items()}
            failures.append(f"{fn}: DRIFTED across {skills} — variant ids {have}")
        else:
            print(f"  ok: {fn} identical across {skills}")

    if failures:
        print("\nDRIFT DETECTED:", file=sys.stderr)
        for f in failures:
            print(f"  ✗ {f}", file=sys.stderr)
        print("\nFix: re-sync the copied helper(s), or update GROUPS if a divergence is intentional.", file=sys.stderr)
        sys.exit(1)
    print("\nAll copied helpers are in sync ✅")


if __name__ == "__main__":
    main()
