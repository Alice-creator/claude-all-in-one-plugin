#!/usr/bin/env python3
"""Recommend a model family from a data fingerprint — claude-all-in-one-plugin.

ADVISORY ONLY: computes a "fingerprint" of the train split (size, features,
categorical cardinality, task, balance, modality flags), runs a research-grounded
decision tree, and writes model_recommendation.md (opening with a Mermaid decision
tree, the fired branch highlighted). It recommends a family; it does NOT train,
tune, or predict — that is train-tune. Reads splits read-only.

Scope: SUPERVISED tabular vs deep-learning recommendation. Reinforcement learning
and unsupervised clustering/dim-reduction are out of scope (the SKILL.md paradigm
gate handles RL conversationally — a static split file cannot reveal a reward loop).
"""
import argparse
import json
import os
import re

import numpy as np
import pandas as pd

# --- helpers kept byte-identical to baseline.py (must not drift) ---------------
def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def find_split(splits_dir, name):
    for f in os.listdir(splits_dir):
        if os.path.splitext(f)[0].lower() == name:
            return os.path.join(splits_dir, f)
    raise SystemExit(f"Could not find '{name}.*' in {splits_dir}")


def infer_task(y):
    # fractional float values are always regression (kept identical across all scripts)
    if pd.api.types.is_float_dtype(y) and not np.all(np.mod(y.dropna(), 1) == 0):
        return "regression"
    nun = y.nunique(dropna=True)
    if pd.api.types.is_float_dtype(y) and nun > 20:
        return "regression"
    return "classification" if nun <= max(20, int(0.05 * len(y))) else "regression"
# -------------------------------------------------------------------------------

LOWER_BETTER = {"mae", "rmse", "mape"}
MEDIA_RE = re.compile(r"\.(?:png|jpe?g|gif|bmp|tiff?|wav|mp3|flac|mp4|mov|avi|webp)$", re.I)


def read_baseline(baseline_dir, override):
    """Read the machine-readable number-to-beat. Never scrape the markdown report."""
    if override:
        name, _, val = override.partition("=")
        name = name.strip()
        return {"primary": name, "value": float(val.replace(",", "")), "lower_is_better": name in LOWER_BETTER}
    p = os.path.join(baseline_dir, "baseline_metric.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def modality_flags(X):
    """Heuristic (labeled as such): flag columns that hint at non-tabular modality."""
    flags = []
    obj_cols = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]
    for c in obj_cols:
        s = X[c].dropna().astype(str)
        if len(s) == 0:
            continue
        media_frac = s.str.contains(MEDIA_RE).mean()
        if media_frac > 0.5:
            flags.append(f"{c}: looks like media file paths ({media_frac:.0%} match)")
            continue
        if s.str.split().str.len().mean() > 5 or s.str.len().mean() > 50:
            flags.append(f"{c}: looks like free text (~{s.str.split().str.len().mean():.0f} tokens/value)")
    num_frac = X.select_dtypes(include=np.number).shape[1] / max(X.shape[1], 1)
    if X.shape[1] > 500 and num_frac > 0.95:
        flags.append(f"all {X.shape[1]} columns numeric — possible flattened signal/embeddings")
    return flags


def fingerprint(df, target, task_arg):
    X = df.drop(columns=[target])
    y = df[target]
    task = task_arg if task_arg != "auto" else infer_task(y)
    cat_cols = [c for c in X.columns if c not in X.select_dtypes(include=np.number).columns]
    cards = {c: int(X[c].nunique()) for c in cat_cols}
    fp = {
        "n_rows": len(df), "n_features": X.shape[1],
        "n_categorical": len(cat_cols),
        "n_high_card": sum(1 for v in cards.values() if v > 50),
        "max_cardinality": max(cards.values()) if cards else 0,
        "task": task, "modality_flags": modality_flags(X),
    }
    if task == "classification":
        vc = y.value_counts(normalize=True)
        fp["n_classes"] = int(y.nunique())
        fp["minority_frac"] = float(vc.min())
        fp["imbalanced"] = fp["minority_frac"] < 0.10
    return fp


def decide(fp, modality, interpretability, latency):
    """Deterministic decision tree. Returns (recommendation dict, fired node ids)."""
    rec = {"primary": None, "alternatives": [], "why": [], "caveats": [], "veto": None}
    fired = ["START", "MOD"]

    if modality in {"image", "audio", "video", "text", "multimodal"}:
        fired.append("DL")
        small = fp.get("n_classes", 2) and fp["n_rows"] < 5000 * max(fp.get("n_classes", 2), 1)
        if small:
            rec["primary"] = "Transfer learning / fine-tune a pretrained model"
            rec["why"].append("Perceptual/text modality but few labels — fine-tune a pretrained backbone rather than train from scratch (Goodfellow: ~5k labeled/category for from-scratch DL; rule of thumb).")
        else:
            rec["primary"] = "Deep learning (modality-appropriate architecture)"
            rec["why"].append("Raw perceptual/text data: DL learns hierarchical features; classic ML needs hand-engineered ones (LeCun et al. 2015).")
        rec["caveats"].append("This plugin's training skill (train-tune) is TABULAR-only — DL is out of its scope; use a dedicated DL track.")
        return _veto(rec, fired, interpretability, latency)

    # tabular
    fired.append("SIZE")
    if fp["n_rows"] < 50:
        fired.append("STOP")
        rec["primary"] = "Do NOT model yet — get more data"
        rec["why"].append("Fewer than ~50 rows is too little to learn or validate (scikit-learn estimator map).")
        return rec, fired

    fired += ["LADDER", "GBDT"]
    rec["primary"] = "Gradient-boosted trees (HistGradientBoosting / XGBoost / LightGBM / CatBoost)"
    rec["why"].append("For medium-sized, feature-meaningful tabular data, GBDTs remain SOTA over deep nets even after huge tuning budgets (Grinsztajn 2022; Shwartz-Ziv 2022).")
    rec["alternatives"] = [
        "Random forest — strong with no tuning, a good robustness check",
        "Regularized linear/logistic — your baseline and the interpretable floor",
        "A single decision tree — for a sanity/interpretability check",
    ]
    if fp["n_high_card"] > 0 or fp["n_categorical"] >= 5:
        rec["why"].append(f"{fp['n_categorical']} categorical features ({fp['n_high_card']} high-cardinality) → prefer CatBoost/LightGBM (native categorical handling, good untuned defaults).")
    if fp["task"] == "classification" and fp["n_rows"] <= 10000 and fp["n_features"] <= 500 and fp.get("n_classes", 99) <= 10:
        rec["alternatives"].insert(0, "TabPFN v2 — can beat tuned GBDTs on small data (≤~10k rows, ≤~500 feats, ≤~10 classes); GBDTs regain parity on larger data (Hollmann, Nature 2025)")
    rec["caveats"].append("The GBDT-vs-DL gap is often negligible vs the effect of light GBDT tuning (McElfresh 2023) — tuning the family usually matters more than switching it.")
    rec["caveats"].append("GBDT-as-default holds for medium, feature-meaningful tabular; for very large / dominant-high-cardinality / sparse data, a neural net (or GBDT+NN ensemble) becomes a co-candidate.")
    return _veto(rec, fired, interpretability, latency)


def _veto(rec, fired, interpretability, latency):
    fired.append("VETO")
    if interpretability == "required" or latency == "cpu-tight":
        fired.append("GLASS")
        reason = "audit/regulatory interpretability" if interpretability == "required" else "tight CPU latency"
        rec["veto"] = (f"OVERRIDE → glass-box model (regularized linear/logistic or a shallow decision tree). "
                       f"Reason: {reason}. Any accuracy edge a black-box shows does not clear this hard constraint.")
    else:
        fired.append("FINAL")
    return rec, fired


def mermaid(fp, fired):
    active = ",".join(dict.fromkeys(fired))  # de-dup, keep order
    return "\n".join([
        "```mermaid",
        "flowchart TD",
        f'    START["fingerprint<br/>n={fp["n_rows"]:,}, feats={fp["n_features"]}, cats={fp["n_categorical"]}({fp["n_high_card"]} high-card)<br/>task={fp["task"]}"] --> MOD{{"modality?"}}',
        '    MOD -->|"image/audio/text"| DL["deep / transfer learning"]',
        '    MOD -->|tabular| SIZE{"n_rows ≥ 50?"}',
        '    SIZE -->|no| STOP["get more data"]',
        '    SIZE -->|yes| LADDER["ladder:<br/>linear→tree→RF→GBDT"]',
        '    LADDER --> GBDT["primary: GBDT"]',
        '    GBDT --> VETO{"interpretability=required<br/>or latency=cpu-tight?"}',
        '    VETO -->|yes| GLASS["override → glass-box"]',
        '    VETO -->|no| FINAL["recommend GBDT"]',
        "    classDef active fill:#bfb,stroke:#2a2,stroke-width:3px;",
        f"    class {active} active;",
        "```",
    ])


def main():
    p = argparse.ArgumentParser(description="Recommend a model family from a data fingerprint (advisory).")
    p.add_argument("--splits-dir", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--task", choices=["auto", "classification", "regression"], default="auto")
    p.add_argument("--baseline-dir", default=None, help="dir with baseline_metric.json (default <splits-dir>/baseline)")
    p.add_argument("--baseline-metric", default=None, help="override, e.g. f1_macro=0.78")
    p.add_argument("--modality", choices=["tabular", "image", "audio", "video", "text", "multimodal"], default="tabular")
    p.add_argument("--interpretability", choices=["none", "preferred", "required"], default="none")
    p.add_argument("--latency", choices=["none", "cpu-tight"], default="none")
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()

    train = load(find_split(args.splits_dir, "train"))
    if args.target not in train.columns:
        raise SystemExit(f"--target '{args.target}' not in train columns: {list(train.columns)}")
    args.out_dir = args.out_dir or os.path.join(args.splits_dir, "select-model")
    args.baseline_dir = args.baseline_dir or os.path.join(args.splits_dir, "baseline")
    os.makedirs(args.out_dir, exist_ok=True)

    fp = fingerprint(train, args.target, args.task)
    baseline = read_baseline(args.baseline_dir, args.baseline_metric)
    rec, fired = decide(fp, args.modality, args.interpretability, args.latency)

    # report
    if baseline:
        dirn = "lower is better" if baseline["lower_is_better"] else "higher is better"
        bar = f"`{baseline['primary']} = {baseline['value']:.4g}` ({dirn})"
        bar_line = f"**Number to beat (from baseline):** {bar} — train-tune must clear this to justify complexity."
    else:
        bar_line = "**No baseline number found.** Run `baseline` first to get the bar your model must beat."

    fp_tbl = "| field | value |\n|---|---|\n" + "\n".join(
        f"| {k} | {v} |" for k, v in fp.items() if k != "modality_flags")
    flags = fp["modality_flags"]
    flags_md = ("⚠️ **Modality flags** (confirm before trusting the tabular assumption):\n"
                + "\n".join(f"- {x}" for x in flags)) if flags else "_No non-tabular column patterns detected (treated as tabular)._"
    alts = "\n".join(f"- {a}" for a in rec["alternatives"]) or "_—_"
    whys = "\n".join(f"- {w}" for w in rec["why"])
    caveats = "\n".join(f"- {c}" for c in rec["caveats"]) or "_—_"
    veto_md = f"\n## Veto applied\n{rec['veto']}\n" if rec["veto"] else ""
    final = rec["veto"].split(".")[0] if rec["veto"] else rec["primary"]

    report = f"""# Model recommendation — `{args.target}` ({fp['task']}, {args.modality})

> **Advisory only.** This recommends a family; it does not train. `train-tune` does the work.

## At a glance
{mermaid(fp, fired)}

## Fingerprint
{fp_tbl}

{flags_md}

## Recommendation
**Primary: {rec['primary']}**

Why:
{whys}

Alternatives to try:
{alts}
{veto_md}
## Caveats & scope limits
{caveats}
- Advisory: actual performance is decided by `train-tune` + `evaluate-model`, not by this recommendation.
- Modality, deployment constraints, and whether the problem is really sequential (RL) cannot be read from a split file — confirm them yourself.

## Next step
{bar_line}

→ Run `train-tune --model <chosen family>` on these splits, then `evaluate-model` on its predictions.
"""
    with open(os.path.join(args.out_dir, "model_recommendation.md"), "w") as f:
        f.write(report)

    verdict = f"{args.modality}, n={fp['n_rows']:,}, {fp['n_categorical']} cats ({fp['n_high_card']} high-card) → {final}"
    if baseline:
        verdict += f"; must beat {baseline['primary']}={baseline['value']:.4g}"
    print(verdict)
    if flags:
        print("  modality flags: " + " | ".join(flags))
    print(f"  written → {args.out_dir}/model_recommendation.md")


if __name__ == "__main__":
    main()
