#!/usr/bin/env python3
"""eda_notebook.py — BUILD (not execute) a baseline EDA Jupyter notebook.

Writes an un-executed .ipynb with a standard EDA battery: load, structure,
missing, numeric distributions, correlation heatmap, categorical breakdown,
and (optionally) relationship to a target column. Run it with run_notebook.py.

Usage:
    python3 eda_notebook.py <data-file> [-o out.ipynb] [--target COL]
"""
import argparse
import os
import sys

LOAD = '''import pandas as pd, numpy as np
import matplotlib.pyplot as plt
%matplotlib inline
plt.rcParams["figure.dpi"] = 90

PATH = {path!r}
ext = PATH.lower().rsplit(".", 1)[-1]
if ext == "parquet":
    df = pd.read_parquet(PATH)
elif ext in ("xlsx", "xls"):
    df = pd.read_excel(PATH)
elif ext == "json":
    df = pd.read_json(PATH)
else:
    df = pd.read_csv(PATH)
print("shape:", df.shape)
df.head()'''

DISTRIB = '''num = df.select_dtypes("number").columns.tolist()
if num:
    ncol = 3
    nrow = (len(num) + ncol - 1) // ncol
    fig, ax = plt.subplots(nrow, ncol, figsize=(5 * ncol, 3.2 * nrow))
    ax = np.array(ax).reshape(-1)
    for i, c in enumerate(num):
        df[c].plot.hist(bins=40, ax=ax[i], title=c)
    for j in range(len(num), len(ax)):
        ax[j].axis("off")
    plt.tight_layout(); plt.show()
else:
    print("No numeric columns")'''

CORR = '''if len(num) > 1:
    corr = df[num].corr(numeric_only=True)
    fig, ax = plt.subplots(figsize=(1 + 0.6 * len(num), 1 + 0.6 * len(num)))
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(num))); ax.set_xticklabels(num, rotation=90)
    ax.set_yticks(range(len(num))); ax.set_yticklabels(num)
    fig.colorbar(im); plt.title("Correlation"); plt.tight_layout(); plt.show()
    corr.round(2)
else:
    print("Need >= 2 numeric columns for a correlation matrix")'''

CATEG = '''cat = [c for c in df.select_dtypes(exclude="number").columns if df[c].nunique() <= 20]
for c in cat:
    print("==", c, "==")
    display(df[c].value_counts(dropna=False).head(10))
if not cat:
    print("No low-cardinality categorical columns")'''

TARGET = '''t = {target!r}
if t in df.columns and pd.api.types.is_numeric_dtype(df[t]):
    cors = df[num].corr(numeric_only=True)[t].drop(t).sort_values(key=abs, ascending=False)
    print("Top numeric correlations with", t)
    display(cors.head(10).round(3))
    cats = [c for c in df.select_dtypes(exclude="number").columns if df[c].nunique() <= 20]
    for c in cats[:3]:
        print("Median", t, "by", c)
        display(df.groupby(c)[t].median().sort_values(ascending=False).head(10))
else:
    print(repr(t), "is not a numeric column / not found - skipping target analysis")'''


def build(path, target):
    import nbformat
    name = os.path.basename(path)
    md = nbformat.v4.new_markdown_cell
    code = nbformat.v4.new_code_cell
    cells = [
        md(f"# Exploratory Data Analysis — `{name}`\n\nAuto-generated baseline EDA. "
           "Extend with dataset-specific questions below."),
        code(LOAD.format(path=path)),
        md("## Structure & types"),
        code("df.dtypes.to_frame('dtype')"),
        code("df.describe(include='all').T"),
        md("## Missing values"),
        code("miss = df.isna().sum()\nmiss = miss[miss > 0].sort_values(ascending=False)\n"
             "miss.to_frame('missing') if len(miss) else 'No missing values'"),
        md("## Numeric distributions"),
        code(DISTRIB),
        md("## Correlation (numeric)"),
        code(CORR),
        md("## Categorical breakdown (low-cardinality)"),
        code(CATEG),
    ]
    if target:
        cells.append(md(f"## Relationship to target: `{target}`"))
        cells.append(code(TARGET.format(target=target)))

    nb = nbformat.v4.new_notebook()
    nb.cells = cells
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3"}
    return nb


def main():
    ap = argparse.ArgumentParser(description="Build a baseline EDA notebook (un-executed).")
    ap.add_argument("path")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--target", default=None, help="Optional target column to relate others to.")
    a = ap.parse_args()

    if not os.path.exists(a.path):
        print(f"ERROR: not found: {a.path}", file=sys.stderr)
        sys.exit(1)
    try:
        import nbformat
    except ImportError:
        print("ERROR: pip install nbformat", file=sys.stderr)
        sys.exit(2)

    out = a.out or os.path.splitext(a.path)[0] + "_eda.ipynb"
    nbformat.write(build(a.path, a.target), out)
    print(f"Built notebook: {out}  (run it with run_notebook.py to execute)")


if __name__ == "__main__":
    main()
