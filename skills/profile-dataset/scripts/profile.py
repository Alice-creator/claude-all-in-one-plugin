#!/usr/bin/env python3
"""profile.py — read-only dataset profiler for the profile-dataset skill.

Loads a tabular file (CSV/TSV/Excel/Parquet/JSON) and prints a structured
structure + data-quality report. NEVER modifies the input file.

Usage:
    python3 profile.py <path> [--sheet NAME] [--top N]
"""
import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def load(path, sheet):
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


def hbytes(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def main():
    ap = argparse.ArgumentParser(description="Read-only dataset profiler.")
    ap.add_argument("path", help="Path to the data file.")
    ap.add_argument("--sheet", default=None, help="Excel sheet name (optional).")
    ap.add_argument("--top", type=int, default=3, help="Top categorical values to show.")
    a = ap.parse_args()

    if not os.path.exists(a.path):
        eprint(f"ERROR: file not found: {a.path}")
        sys.exit(1)
    try:
        import pandas as pd
    except ImportError:
        eprint("ERROR: pandas not installed. Run: pip install pandas numpy openpyxl pyarrow")
        sys.exit(2)
    try:
        df = load(a.path, a.sheet)
    except Exception as e:
        eprint(f"ERROR loading file: {e}")
        sys.exit(3)

    nrows, ncols = df.shape
    bar = "=" * 70
    print(bar)
    print(f"DATASET PROFILE — {os.path.basename(a.path)}")
    print(bar)
    print(f"Path  : {os.path.abspath(a.path)}")
    print(f"Shape : {nrows:,} rows x {ncols} columns")
    try:
        print(f"Memory: {hbytes(df.memory_usage(deep=True).sum())}")
    except Exception:
        pass
    dup = int(df.duplicated().sum())
    print(f"Duplicate rows: {dup:,}" + (f" ({dup / nrows * 100:.1f}%)" if nrows else ""))
    print()

    warns = []
    if dup:
        warns.append(f"{dup:,} duplicate (full-row) rows")
    datetime_cols = []

    print("-" * 70)
    print("PER-COLUMN SUMMARY")
    print("-" * 70)
    for col in df.columns:
        s = df[col]
        miss = int(s.isna().sum())
        pmiss = miss / nrows * 100 if nrows else 0
        nuniq = int(s.nunique(dropna=True))
        print(f"\n• {col}  [{s.dtype}]")
        print(f"    missing={miss:,} ({pmiss:.1f}%)   unique={nuniq:,}")

        if pd.api.types.is_numeric_dtype(s) and s.notna().any():
            d = s.describe()
            std = d.get("std", float("nan"))
            print(f"    min={d['min']:.4g}  mean={d['mean']:.4g}  max={d['max']:.4g}  std={std:.4g}")
            q1, q3 = s.quantile(.25), s.quantile(.75)
            iqr = q3 - q1
            if iqr and iqr > 0:
                nout = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())
                if nout:
                    print(f"    outliers (1.5·IQR) = {nout:,}")
                    warns.append(f"'{col}': {nout:,} potential outliers")
        elif pd.api.types.is_datetime64_any_dtype(s):
            datetime_cols.append(col)
            print(f"    range: {s.min()} -> {s.max()}")
        else:
            vc = s.value_counts(dropna=True).head(a.top)
            if len(vc):
                print("    top: " + ", ".join(f"{repr(str(i))}x{c}" for i, c in vc.items()))
            nn = s.dropna().astype(str)
            if len(nn):
                # strip common numeric noise (thousands separators, currency, %) before testing
                cleaned = nn.str.replace(r"[,$€£%\s]", "", regex=True)
                num_frac = pd.to_numeric(cleaned, errors="coerce").notna().mean()
                if num_frac > 0.95:
                    warns.append(f"'{col}': stored as text but {num_frac * 100:.0f}% parse as numbers — wrong type?")
                else:
                    dt_frac = pd.to_datetime(nn, errors="coerce").notna().mean()
                    if dt_frac > 0.95:
                        warns.append(f"'{col}': stored as text but {dt_frac * 100:.0f}% parse as dates — wrong type?")

        if pmiss > 50:
            warns.append(f"'{col}': {pmiss:.0f}% missing (high)")
        if nuniq <= 1 and nrows > 1:
            warns.append(f"'{col}': constant (only 1 unique value)")

    print()
    print("-" * 70)
    print("DATA-QUALITY WARNINGS")
    print("-" * 70)
    if warns:
        for w in warns:
            print(f"!  {w}")
    else:
        print("OK - no obvious issues detected.")
    if datetime_cols:
        print(f"\nSTRUCTURE HINT: datetime column(s) {datetime_cols} present — may be time-series / panel data.")
    print("\nNOTE: read-only profile — the source file was NOT modified.")


if __name__ == "__main__":
    main()
