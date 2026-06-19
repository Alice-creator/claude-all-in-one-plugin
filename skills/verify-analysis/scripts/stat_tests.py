#!/usr/bin/env python3
"""stat_tests.py — vetted statistical tests for the verify-analysis stage.

Validates candidate EDA findings with the RIGHT test plus an effect size, and
checks whether a relationship is STABLE across random splits. The default stance
is skepticism: small or unstable effects are weak/refuted, not "significant".
NEVER modifies the input file.

Tests:
    corr   Pearson correlation of two numeric columns (r, p, n).
    group  Two-group difference on a numeric --y split by a 2-level --x:
           Welch t-test, falling back to Mann-Whitney U for tiny groups (n<20).
           Effect size = Cohen's d.
    anova  One-way ANOVA of numeric --y across a categorical --x (F, p, eta^2).
    chi2   Chi-square independence of two categoricals --x, --y (chi2, p, Cramer's V).

Programmatic use (returns dicts): pearson, two_group, anova, chi2, stability.

Usage:
    python3 stat_tests.py <file> --test corr|group|anova|chi2 --x COL --y COL [--by COL]
    # --by re-runs the chosen test inside the strongest split of --by, a cheap
    #   confounder probe (does the effect survive holding --by roughly fixed?).

Prints a JSON result to stdout.
"""
import argparse
import json
import math
import os
import sys
import warnings

warnings.filterwarnings("ignore")


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def load(path, sheet=None):
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".txt"):
        try:
            return pd.read_csv(path, sep=None, engine="python")
        except UnicodeDecodeError:
            return pd.read_csv(path, sep=None, engine="python", encoding="latin-1")
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t", engine="python")
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, sheet_name=sheet if sheet else 0)
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".json":
        try:
            return pd.read_json(path)
        except ValueError:
            return pd.read_json(path, lines=True)
    return pd.read_csv(path, sep=None, engine="python")


# ---------------------------------------------------------------------------
# verdict helper — encodes the skeptical default
# ---------------------------------------------------------------------------
def verdict(p, effect, *, small, medium, n, min_n=30):
    """Map (significance, effect magnitude, sample size) -> confirmed/weak/refuted.

    - refuted : not significant, OR effect below the 'small' floor.
    - weak    : significant but effect only between small and medium, or n is thin.
    - confirmed: significant AND effect >= medium AND enough data.
    Effect is compared on its absolute value.
    """
    a = abs(effect) if effect is not None and not _isnan(effect) else 0.0
    if p is None or _isnan(p) or p >= 0.05 or a < small:
        return "refuted"
    if a >= medium and n >= min_n:
        return "confirmed"
    return "weak"


def _isnan(x):
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True


def _clean_pair(df, x, y):
    """Drop rows where x or y is NA; return the two aligned Series."""
    sub = df[[x, y]].dropna()
    return sub[x], sub[y]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def pearson(df, x, y):
    from scipy import stats
    a, b = _clean_pair(df, x, y)
    n = int(len(a))
    if n < 3:
        return {"test": "pearson", "x": x, "y": y, "n": n,
                "verdict": "inconclusive", "error": "fewer than 3 paired observations"}
    r, p = stats.pearsonr(a, b)
    # Cohen: |r| 0.1 small, 0.3 medium, 0.5 large. Skeptic floor at 0.1.
    return {"test": "pearson", "x": x, "y": y, "n": n,
            "r": round(float(r), 4), "p_value": float(p),
            "effect_size": {"name": "pearson_r", "value": round(float(r), 4)},
            "verdict": verdict(p, r, small=0.1, medium=0.3, n=n)}


def _cohens_d(a, b):
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    va, vb = a.var(ddof=1), b.var(ddof=1)
    sp = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if sp == 0:
        return float("nan")
    return float((a.mean() - b.mean()) / sp)


def two_group(df, x, y):
    """Numeric y compared across the two levels of a 2-level grouping column x."""
    from scipy import stats
    gx, gy = _clean_pair(df, x, y)
    levels = list(gx.unique())
    if len(levels) != 2:
        return {"test": "two_group", "x": x, "y": y, "n": int(len(gy)),
                "verdict": "inconclusive",
                "error": f"need exactly 2 groups in '{x}', found {len(levels)}"}
    a = gy[gx == levels[0]]
    b = gy[gx == levels[1]]
    na, nb = int(len(a)), int(len(b))
    n = na + nb
    tiny = na < 20 or nb < 20
    if tiny:
        try:
            stat, p = stats.mannwhitneyu(a, b, alternative="two-sided")
            method = "mann_whitney_u"
        except ValueError as e:
            return {"test": "two_group", "x": x, "y": y, "n": n,
                    "verdict": "inconclusive", "error": str(e)}
    else:
        stat, p = stats.ttest_ind(a, b, equal_var=False)  # Welch
        method = "welch_t"
    d = _cohens_d(a, b)
    return {"test": "two_group", "method": method, "x": x, "y": y,
            "groups": {str(levels[0]): na, str(levels[1]): nb}, "n": n,
            "statistic": round(float(stat), 4), "p_value": float(p),
            "group_means": {str(levels[0]): round(float(a.mean()), 4),
                            str(levels[1]): round(float(b.mean()), 4)},
            "effect_size": {"name": "cohens_d",
                            "value": (None if _isnan(d) else round(d, 4))},
            # Cohen's d: 0.2 small, 0.5 medium, 0.8 large. Skeptic floor 0.2.
            "verdict": verdict(p, d, small=0.2, medium=0.5, n=n)}


def anova(df, x, y):
    """One-way ANOVA of numeric y across the categories of x. Effect = eta^2."""
    from scipy import stats
    gx, gy = _clean_pair(df, x, y)
    groups = [gy[gx == lv] for lv in gx.unique()]
    groups = [g for g in groups if len(g) >= 2]
    n = int(len(gy))
    if len(groups) < 2:
        return {"test": "anova", "x": x, "y": y, "n": n, "verdict": "inconclusive",
                "error": "need >= 2 groups with >= 2 observations each"}
    F, p = stats.f_oneway(*groups)
    grand = gy.mean()
    ss_between = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)
    ss_total = float(((gy - grand) ** 2).sum())
    eta2 = (ss_between / ss_total) if ss_total > 0 else float("nan")
    return {"test": "anova", "x": x, "y": y, "k_groups": len(groups), "n": n,
            "F": round(float(F), 4), "p_value": float(p),
            "effect_size": {"name": "eta_squared",
                            "value": (None if _isnan(eta2) else round(eta2, 4))},
            # eta^2: 0.01 small, 0.06 medium, 0.14 large. Skeptic floor 0.01.
            "verdict": verdict(p, eta2, small=0.01, medium=0.06, n=n)}


def chi2(df, x, y):
    """Chi-square test of independence for two categorical columns. Effect = Cramer's V."""
    import pandas as pd
    from scipy import stats
    sub = df[[x, y]].dropna()
    n = int(len(sub))
    table = pd.crosstab(sub[x], sub[y])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return {"test": "chi2", "x": x, "y": y, "n": n, "verdict": "inconclusive",
                "error": "need >= 2 levels in each column"}
    chi, p, dof, _ = stats.chi2_contingency(table)
    r, c = table.shape
    denom = n * (min(r, c) - 1)
    v = math.sqrt(chi / denom) if denom > 0 else float("nan")
    return {"test": "chi2", "x": x, "y": y, "n": n,
            "chi2": round(float(chi), 4), "p_value": float(p), "dof": int(dof),
            "table_shape": [int(r), int(c)],
            "effect_size": {"name": "cramers_v",
                            "value": (None if _isnan(v) else round(v, 4))},
            # Cramer's V: 0.1 small, 0.3 medium, 0.5 large. Skeptic floor 0.1.
            "verdict": verdict(p, v, small=0.1, medium=0.3, n=n)}


# ---------------------------------------------------------------------------
# stability — does the statistic hold across random splits?
# ---------------------------------------------------------------------------
def stability(df, x, y, n=5, seed=0, stat="auto"):
    """Recompute a statistic on n random equal splits; report mean & variance.

    Picks the statistic automatically: Pearson r if both columns are numeric,
    else Cohen's d (2-group) / eta^2 (multi-group) for numeric y vs categorical x.
    An unstable effect (sign flips, or variance large vs the mean) is a red flag
    even when the full-sample p-value looks significant.
    """
    import numpy as np
    import pandas as pd

    sub = df[[x, y]].dropna().reset_index(drop=True)
    N = len(sub)
    if N < 2 * n:
        return {"metric": None, "n_splits": n, "values": [],
                "error": f"not enough rows ({N}) for {n} splits"}

    x_num = pd.api.types.is_numeric_dtype(sub[x])
    y_num = pd.api.types.is_numeric_dtype(sub[y])
    if stat == "auto":
        if x_num and y_num:
            stat = "pearson_r"
        elif y_num and not x_num:
            stat = "cohens_d" if sub[x].nunique() == 2 else "eta_squared"
        else:
            stat = "cramers_v"

    rng = np.random.default_rng(seed)
    idx = rng.permutation(N)
    parts = np.array_split(idx, n)
    vals = []
    for part in parts:
        s = sub.iloc[part]
        try:
            if stat == "pearson_r":
                v = pearson(s, x, y).get("r")
            elif stat == "cohens_d":
                r = two_group(s, x, y)
                v = (r.get("effect_size") or {}).get("value")
            elif stat == "eta_squared":
                r = anova(s, x, y)
                v = (r.get("effect_size") or {}).get("value")
            else:
                r = chi2(s, x, y)
                v = (r.get("effect_size") or {}).get("value")
        except Exception:
            v = None
        if v is not None and not _isnan(v):
            vals.append(float(v))

    if not vals:
        return {"metric": stat, "n_splits": n, "values": [],
                "error": "no split produced a value"}

    arr = np.array(vals, dtype=float)
    mean = float(arr.mean())
    var = float(arr.var(ddof=1)) if len(arr) > 1 else 0.0
    signs = {math.copysign(1, v) for v in arr if v != 0}
    sign_flips = len(signs) > 1
    # stable if effects share a sign and spread is small relative to the level.
    cv = (math.sqrt(var) / abs(mean)) if mean != 0 else float("inf")
    stable = (not sign_flips) and cv < 0.5
    return {"metric": stat, "n_splits": n, "n_used": len(vals),
            "values": [round(v, 4) for v in vals],
            "mean": round(mean, 4), "variance": round(var, 6),
            "sign_flips": sign_flips, "stable": bool(stable)}


# ---------------------------------------------------------------------------
# optional confounder probe: re-run the test inside the largest --by stratum
# ---------------------------------------------------------------------------
def _within_by(df, by, test, x, y):
    biggest = df[by].value_counts(dropna=True)
    if biggest.empty:
        return {"by": by, "error": "no non-null values in confounder column"}
    level = biggest.index[0]
    sub = df[df[by] == level]
    res = TESTS[test](sub, x, y)
    return {"by": by, "held_at": str(level), "n_in_stratum": int(len(sub)),
            "result": res,
            "note": "re-ran the test holding the confounder roughly fixed; "
                    "if the verdict weakens here, the headline effect may be confounded"}


TESTS = {"corr": pearson, "group": two_group, "anova": anova, "chi2": chi2}


def main():
    ap = argparse.ArgumentParser(description="Vetted statistical tests for verify-analysis.")
    ap.add_argument("path", help="Path to the (clean) data file.")
    ap.add_argument("--test", required=True, choices=list(TESTS.keys()),
                    help="corr | group | anova | chi2")
    ap.add_argument("--x", required=True, help="First column (predictor / grouping).")
    ap.add_argument("--y", required=True, help="Second column (outcome / numeric for corr/group/anova).")
    ap.add_argument("--by", default=None, help="Optional confounder column to stratify on.")
    ap.add_argument("--splits", type=int, default=5, help="Random splits for the stability check.")
    ap.add_argument("--sheet", default=None, help="Excel sheet name (optional).")
    a = ap.parse_args()

    if not os.path.exists(a.path):
        eprint(f"ERROR: file not found: {a.path}")
        sys.exit(1)
    try:
        import pandas as pd  # noqa: F401
        import scipy  # noqa: F401
    except ImportError:
        eprint("ERROR: missing deps. Run: pip install pandas scipy numpy")
        sys.exit(2)
    try:
        df = load(a.path, a.sheet)
    except Exception as e:
        eprint(f"ERROR loading file: {e}")
        sys.exit(3)

    for col in (a.x, a.y) + ((a.by,) if a.by else ()):
        if col not in df.columns:
            eprint(f"ERROR: column not found: {col!r}. Available: {list(df.columns)}")
            sys.exit(4)

    try:
        result = TESTS[a.test](df, a.x, a.y)
        result["stability"] = stability(df, a.x, a.y, n=a.splits)
        if a.by:
            result["confounder_check"] = _within_by(df, a.by, a.test, a.x, a.y)
    except Exception as e:
        eprint(f"ERROR running {a.test}: {type(e).__name__}: {e}")
        sys.exit(5)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
