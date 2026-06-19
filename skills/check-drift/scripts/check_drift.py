#!/usr/bin/env python3
"""Population drift between two data snapshots — claude-all-in-one-plugin.

Given a REFERENCE snapshot (what the model was trained on) and a CURRENT snapshot
(a new batch), compute per-feature drift (PSI, primary) and write drift_report.md.
Offline and label-free: it compares two static tables. It does NOT watch live
traffic, measure model quality, or detect concept drift P(y|X) — see the report's
"What this CANNOT tell you" section.

No model is ever loaded.
"""
import argparse
import json
import os

import numpy as np
import pandas as pd


# --- load/find_split copied byte-identical from baseline.py (3-branch: .parquet/.tsv/csv;
# --- deliberately NOT evaluate.py's 2-branch variant — snapshots may be TSV exports) ---
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


def fmt(v):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.4g}"


def md_cell(x):
    return str(x).replace("|", "\\|").replace("\n", " ")  # don't let a column name break the table


def is_categorical(s):
    # numeric with <=5 distinct → categorical (Evidently rule; avoids degenerate quantile bins)
    return (not pd.api.types.is_numeric_dtype(s)) or s.nunique(dropna=True) <= 5


def psi_from_counts(e, a):
    """PSI over discrete bins with Laplace (add-0.5) smoothing — prevents ln(0) blow-ups from
    empty bins. NOTE: smoothing is empty-bin safe, NOT sampling-noise safe — PSI is still
    inflated on small current samples (see the LOW_N guard / report caveat)."""
    e, a = np.asarray(e, float), np.asarray(a, float)
    k = len(e)
    ep = (e + 0.5) / (e.sum() + 0.5 * k)
    ap = (a + 0.5) / (a.sum() + 0.5 * k)
    return float(np.sum((ap - ep) * np.log(ap / ep)))


def numeric_drift(ref, cur, bins, with_ks):
    r = ref.dropna()
    if r.nunique() < 2:
        return None
    edges = np.unique(np.quantile(r, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return None  # too few distinct values for meaningful bins
    # REPLACE outer edges with ±inf so out-of-range current values fold into the first/last
    # REAL reference bin instead of a guaranteed-empty phantom bin that would inflate PSI.
    edges[0], edges[-1] = -np.inf, np.inf
    e = pd.cut(ref.dropna(), edges).value_counts().sort_index()
    a = pd.cut(cur.dropna(), edges).value_counts().reindex(e.index).fillna(0)
    e_counts = np.append(e.values, ref.isna().sum())  # NaN as its own bin → missingness shift
    a_counts = np.append(a.values, cur.isna().sum())
    out = {"psi": psi_from_counts(e_counts, a_counts)}
    if with_ks and cur.dropna().size and r.size:
        from scipy.stats import ks_2samp
        d, p = ks_2samp(r, cur.dropna())
        out["ks_d"], out["ks_p"] = float(d), float(p)
    return out


def _uniq(name, taken):
    while name in taken:
        name += "_"
    return name


def _align_numeric_cat(ref, cur):
    """If both sides are numeric low-card categoricals, align dtypes so 1 and 1.0 (a common
    CSV/NaN round-trip artifact) map to the SAME bucket instead of spurious 'major' drift."""
    if pd.api.types.is_numeric_dtype(ref) and pd.api.types.is_numeric_dtype(cur):
        both = pd.concat([ref.dropna(), cur.dropna()])
        if len(both) and (both == both.round()).all():
            return ref.round().astype("Int64"), cur.round().astype("Int64")
    return ref, cur


def categorical_drift(ref, cur, max_cat):
    ref, cur = _align_numeric_cat(ref, cur)
    taken = set(ref.astype(str)) | set(cur.astype(str))
    OTHER, UNSEEN, NAN = (_uniq(s, taken) for s in ("(other)", "(unseen)", "(nan)"))  # collision-proof
    r = ref.astype(str).where(~ref.isna(), NAN)
    c = cur.astype(str).where(~cur.isna(), NAN)
    ref_cats = set(r.unique())
    top = list(r.value_counts().index[:max_cat])
    unseen_share = float((~c.isin(ref_cats)).mean()) if len(c) else None
    rr = r.where(r.isin(top), OTHER)
    cc = pd.Series(np.where(c.isin(top), c, np.where(c.isin(ref_cats), OTHER, UNSEEN)), index=c.index)
    idx = list(dict.fromkeys(top + [OTHER, UNSEEN]))  # de-dup defensively
    e = rr.value_counts().reindex(idx).fillna(0)
    a = cc.value_counts().reindex(idx).fillna(0)
    psi = psi_from_counts(e.values, a.values)
    te, ta = e.values.sum(), a.values.sum()
    tvd = float(0.5 * np.sum(np.abs(a.values / ta - e.values / te))) if te > 0 and ta > 0 else None
    return {"psi": psi, "tvd": tvd, "unseen_share": unseen_share}


def col_drift(ref_s, cur_s, bins, max_cat, with_ks):
    if is_categorical(ref_s):
        d = categorical_drift(ref_s, cur_s, max_cat)
        d["type"] = "categorical"
    else:
        d = numeric_drift(ref_s, cur_s, bins, with_ks)
        if d is None:
            return None
        d["type"] = "numeric"
    return d


def band(psi, minor, major):
    return "none" if psi < minor else ("moderate" if psi < major else "major")


def main():
    p = argparse.ArgumentParser(description="Detect population drift between two snapshots (offline).")
    p.add_argument("--current", required=True, help="new batch to test for drift")
    p.add_argument("--reference", default=None, help="distribution the model trained on (or use --splits-dir)")
    p.add_argument("--splits-dir", default=None, help="if given and --reference omitted, use its train split")
    p.add_argument("--target", default=None, help="target column → TARGET drift P(y), if in both")
    p.add_argument("--pred-col", default="y_pred", help="predictions column → PREDICTION drift P(y_pred), if in both")
    p.add_argument("--bins", type=int, default=10)
    p.add_argument("--psi-thresholds", default="0.1,0.25", help="minor,major (Siddiqi 0.1/0.25; Fiddler uses 0.1/0.2)")
    p.add_argument("--pvalues", action="store_true", help="also compute secondary KS p-values (over-trigger on large n)")
    p.add_argument("--max-cat", type=int, default=20)
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()

    if not args.reference:
        if not args.splits_dir:
            raise SystemExit("Provide --reference, or --splits-dir to use its train split as reference.")
        args.reference = find_split(args.splits_dir, "train")
    minor, major = (float(x) for x in args.psi_thresholds.split(","))
    ref, cur = load(args.reference), load(args.current)
    args.out_dir = args.out_dir or os.path.join(os.path.dirname(os.path.abspath(args.current)), "check-drift")
    os.makedirs(args.out_dir, exist_ok=True)
    low_n_floor = max(200, 20 * args.bins)  # PSI is unreliable below this current sample size

    shared = [c for c in ref.columns if c in cur.columns]
    ref_only = [c for c in ref.columns if c not in cur.columns]
    cur_only = [c for c in cur.columns if c not in ref.columns]
    special = {c for c in (args.target, args.pred_col) if c and c in shared}
    features = [c for c in shared if c not in special]
    # explicit --target that the current snapshot lacks: warn, don't silently no-op
    missing_target = args.target if (args.target and args.target not in shared) else None

    rows, skipped = [], []
    for col in features:
        d = col_drift(ref[col], cur[col], args.bins, args.max_cat, args.pvalues)
        if d is None:
            skipped.append(col)
            continue
        d["feature"] = col
        d["n_cur"] = int(cur[col].notna().sum())
        d["low_n"] = d["n_cur"] < low_n_floor
        d["band"] = band(d["psi"], minor, major)
        rows.append(d)
    rows.sort(key=lambda r: r["psi"], reverse=True)
    any_low_n = any(r["low_n"] for r in rows)

    def special_drift(col):
        d = col_drift(ref[col], cur[col], args.bins, args.max_cat, False)
        if d:
            d["psi_band"] = band(d["psi"], minor, major)
        return d

    target_d = special_drift(args.target) if args.target in special else None
    pred_d = special_drift(args.pred_col) if args.pred_col in special else None

    n_major = sum(1 for r in rows if r["band"] == "major")
    n_moderate = sum(1 for r in rows if r["band"] == "moderate")
    overall = "major shift" if n_major else ("moderate shift" if n_moderate else "stable")
    top = rows[0] if rows else None

    summary = {
        "reference": args.reference, "current": args.current,
        "n_ref": len(ref), "n_cur": len(cur),
        "n_features": len(rows), "n_major": n_major, "n_moderate": n_moderate,
        "overall": overall, "psi_thresholds": [minor, major],
        "low_n_floor": low_n_floor, "low_n_features": [r["feature"] for r in rows if r["low_n"]],
        "skipped_features": skipped, "missing_target": missing_target,
        "top_feature": top["feature"] if top else None, "top_psi": top["psi"] if top else None,
        "target_psi": target_d["psi"] if target_d else None,
        "prediction_psi": pred_d["psi"] if pred_d else None,
        "schema": {"ref_only": ref_only, "cur_only": cur_only},
    }
    with open(os.path.join(args.out_dir, "drift_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    pd.DataFrame(rows).to_csv(os.path.join(args.out_dir, "drift_metrics.csv"), index=False)

    cols = ["feature", "type", "n_cur", "psi", "band", "tvd", "unseen_share"] + (["ks_d", "ks_p"] if args.pvalues else [])
    head = "| " + " | ".join(cols) + " | flag |\n|" + "---|" * (len(cols) + 1)
    body = "\n".join(
        "| " + " | ".join(fmt(r.get(c)) if isinstance(r.get(c), float) else md_cell(r.get(c, "")) for c in cols)
        + f" | {'⚠ low-n' if r['low_n'] else ''} |" for r in rows)
    top_node = f' --> T["most drifted: {md_cell(top["feature"])}<br/>PSI={fmt(top["psi"])} ({top["band"]})"]' if top else ""
    mermaid = "\n".join([
        "```mermaid", "flowchart LR",
        f'    R["reference<br/>{len(ref):,} rows"] --> C["current<br/>{len(cur):,} rows"]',
        f'    C --> V["{overall}<br/>{n_major} major · {n_moderate} moderate"]{top_node}',
        "```",
    ])
    warnings = []
    if any_low_n:
        warnings.append(f"⚠️ **Small current batch** — features tagged `low-n` have a current sample below {low_n_floor}; PSI is inflated by sampling noise at small n and those flags are unreliable. Use a larger current batch.")
    if missing_target:
        warnings.append(f"⚠️ **Requested `--target {missing_target}` is not in the current snapshot** — target drift was NOT computed.")
    if skipped:
        warnings.append(f"ℹ️ Skipped {len(skipped)} feature(s) with too few distinct reference values to bin: {skipped}")
    warn_md = ("\n".join(warnings) + "\n") if warnings else ""

    def special_md(d, title, interp):
        if not d:
            return ""
        extra = f" · TVD={fmt(d.get('tvd'))}" if d.get("tvd") is not None else ""
        return f"\n## {title}\nPSI = {fmt(d['psi'])} ({d['psi_band']}){extra}\n\n{interp}\n"

    target_interp = ("If this column holds ground-truth outcomes in the current batch, this is label shift P(y). "
                     "The tool does NOT verify the column is true labels rather than predictions/proxies — confirm its provenance.")
    pred_interp = ("Describes how the model's outputs differ between batches. It is NOT a measure of model quality, "
                   "and NOT a reliable predictor of input drift in either direction. A flag to investigate, not proof of anything.")

    report = f"""# Drift report — current vs reference

> Offline comparison of two static snapshots. Reference = `{md_cell(os.path.basename(args.reference))}` ({len(ref):,} rows), current = `{md_cell(os.path.basename(args.current))}` ({len(cur):,} rows). Neither file modified.

## At a glance
{mermaid}

**Verdict: {overall}** — {n_major} major / {n_moderate} moderate of {len(rows)} features (PSI bands {minor}/{major}).

{warn_md}## Per-feature drift (sorted by PSI)
{head}
{body}
{special_md(target_d, "Target drift — P(y), the outcome distribution", target_interp)}{special_md(pred_d, "Prediction drift — P(y_pred), the MODEL-OUTPUT distribution", pred_interp)}
## Schema diff
- only in reference: {ref_only or "—"}
- only in current: {cur_only or "—"}

## How to read PSI
- Bands {minor}/{major} are the Siddiqi credit-scoring **rule of thumb** — no inherent statistical meaning, sensitive to bin count/placement (Fiddler uses {minor}/0.2). Read the **top features by PSI**, not the count of flags: per-feature PSI is **not** multiple-testing corrected.
- **PSI is inflated on small current batches** by ordinary sampling noise (e.g. with no real drift, a current batch of ~50 rows can read "major"). Trust drift verdicts only when `n_cur` is large; `low-n` rows are flagged above.
- A large PSI is **as often an upstream data-pipeline / schema / encoding change (a bug)** as a real population shift (high `unseen_share` or out-of-range mass points that way) — inspect the feeding pipeline before concluding the world changed.

## What this CANNOT tell you
- **Concept drift** P(y|X) — a change in the input→output relationship — is **unmeasurable without ground-truth labels** (true for every offline tool here). Drift is a label-free proxy that the *environment* changed, never proof the *model* degraded. Drift ≠ degradation.
- **Model quality / accuracy** — needs labels on the current batch; if you have them, run `evaluate-model`.
- **Online / business performance, serving health (latency, errors), live monitoring, alerting, retraining** — all need production telemetry. This is a stateless one-shot over two files: no live traffic, no run-over-run history, no control loop. It produces drift **evidence**, not a retrain mandate.
"""
    with open(os.path.join(args.out_dir, "drift_report.md"), "w") as f:
        f.write(report)

    line = f"drift (input population, label-free): {overall.upper()} — {n_major}/{len(rows)} major, {n_moderate} moderate"
    if top:
        line += f"; top: {top['feature']} PSI={fmt(top['psi'])} ({top['band']})"
    if target_d:
        line += f"; target P(y) PSI={fmt(target_d['psi'])}"
    if pred_d:
        line += f"; pred P(y_pred) PSI={fmt(pred_d['psi'])}"
    print(line)
    if any_low_n:
        print(f"  ⚠ small current batch (<{low_n_floor}) on some features — PSI unreliable; see low-n flags")
    if missing_target:
        print(f"  ⚠ --target '{missing_target}' absent from current snapshot — target drift not computed")
    if special:
        print(f"  excluded from per-feature drift (treated as target/prediction): {sorted(special)}")
    print("  note: environment shift, NOT proof the model degraded")
    print(f"  written → {args.out_dir}/ (drift_report.md, drift_metrics.csv, drift_summary.json)")


if __name__ == "__main__":
    main()
