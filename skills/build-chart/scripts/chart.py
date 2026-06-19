#!/usr/bin/env python3
"""chart.py — presentation-quality charts for the build-chart skill.

Renders a single, report-ready chart from a tabular file (CSV/TSV/Excel/
Parquet/JSON) using matplotlib's non-interactive Agg backend and saves it to a
PNG. These are FINAL-REPORT charts (clear labels, title, sensible size/dpi) —
distinct from the quick exploratory plots produced during EDA. NEVER modifies
the input file.

Chart kinds:
    bar          one categorical x, aggregated y (or counts) — comparison
    grouped-bar  x grouped by --hue, aggregated y — multi-series comparison
    line         x vs y (sorted by x) — trend, e.g. over time
    hist         distribution of a single numeric --x
    scatter      numeric x vs numeric y — relationship
    box          numeric --y distribution, optionally split by categorical --x

Usage:
    python3 chart.py <file> --kind bar --x Brand --y Price --agg mean \\
        --title "Avg price by brand" --top 10 -o avg_price_by_brand.png
    python3 chart.py <file> --kind hist --x Price
    python3 chart.py <file> --kind scatter --x Horsepower --y Price
    python3 chart.py <file> --kind grouped-bar --x Brand --y Price \\
        --hue Fuel_Type --agg mean --top 8
    python3 chart.py <file> --kind line --x Year --y Price --agg median
    python3 chart.py <file> --kind box --x Fuel_Type --y Mileage_kmpl
"""
import argparse
import os
import sys

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend — no display needed
    import matplotlib.pyplot as plt
    import pandas as pd
except ImportError:
    print(
        "ERROR: missing dependency. Run: pip install pandas matplotlib pyarrow openpyxl",
        file=sys.stderr,
    )
    sys.exit(2)


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def load(path, sheet):
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


def need(df, *cols):
    """Fail clearly if a required column is absent."""
    for c in cols:
        if c is None:
            eprint("ERROR: this chart kind needs a column that was not provided.")
            sys.exit(4)
        if c not in df.columns:
            eprint(f"ERROR: column {c!r} not found. Available: {list(df.columns)}")
            sys.exit(4)


def aggregate(df, x, y, agg):
    """Group df by x and reduce y with agg. agg='count' ignores y and counts rows."""
    g = df.groupby(x, dropna=True)
    if agg == "count" or y is None:
        return g.size()
    return getattr(g[y], agg)()


def top_n(series, n):
    """Keep the n largest values (by magnitude) so a chart stays readable."""
    if n and len(series) > n:
        return series.sort_values(ascending=False).head(n)
    return series


def main():
    ap = argparse.ArgumentParser(description="Render a presentation-quality chart to PNG.")
    ap.add_argument("path", help="Path to the data file.")
    ap.add_argument("--kind", required=True,
                    choices=["bar", "grouped-bar", "line", "hist", "scatter", "box"],
                    help="Chart type.")
    ap.add_argument("--x", default=None, help="Column for the x-axis / category.")
    ap.add_argument("--y", default=None, help="Column for the y-axis / value.")
    ap.add_argument("--hue", default=None, help="Grouping column (grouped-bar).")
    ap.add_argument("--agg", default="mean", choices=["mean", "median", "sum", "count"],
                    help="Aggregation for bar/grouped-bar/line (default: mean).")
    ap.add_argument("--top", type=int, default=None,
                    help="Keep only the top-N categories on a categorical x.")
    ap.add_argument("--bins", type=int, default=30, help="Histogram bins (default: 30).")
    ap.add_argument("--title", default=None, help="Chart title.")
    ap.add_argument("-o", "--out", default=None, help="Output PNG (default: <kind>_chart.png).")
    ap.add_argument("--sheet", default=None, help="Excel sheet name (optional).")
    a = ap.parse_args()

    if not os.path.exists(a.path):
        eprint(f"ERROR: file not found: {a.path}")
        sys.exit(1)
    try:
        df = load(a.path, a.sheet)
    except Exception as e:
        eprint(f"ERROR loading file: {e}")
        sys.exit(3)

    out = a.out or f"{a.kind}_chart.png"
    fig, ax = plt.subplots(figsize=(10, 6))

    if a.kind == "bar":
        need(df, a.x)
        if a.agg != "count":
            need(df, a.y)
        s = top_n(aggregate(df, a.x, a.y, a.agg), a.top).sort_values()
        s.plot.barh(ax=ax, color="#3b6ea5")
        ax.set_xlabel(f"{a.agg} of {a.y}" if a.agg != "count" else "count")
        ax.set_ylabel(a.x)

    elif a.kind == "grouped-bar":
        need(df, a.x, a.hue)
        if a.agg != "count":
            need(df, a.y)
        if a.agg == "count":
            pivot = df.groupby([a.x, a.hue], dropna=True).size().unstack(a.hue)
        else:
            pivot = getattr(df.groupby([a.x, a.hue], dropna=True)[a.y], a.agg)().unstack(a.hue)
        if a.top and len(pivot) > a.top:
            pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).head(a.top).index]
        pivot.plot.bar(ax=ax)
        ax.set_xlabel(a.x)
        ax.set_ylabel(f"{a.agg} of {a.y}" if a.agg != "count" else "count")
        ax.legend(title=a.hue)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    elif a.kind == "line":
        need(df, a.x, a.y)
        s = aggregate(df, a.x, a.y, a.agg).sort_index()
        s.plot.line(ax=ax, marker="o", color="#3b6ea5")
        ax.set_xlabel(a.x)
        ax.set_ylabel(f"{a.agg} of {a.y}" if a.agg != "count" else "count")

    elif a.kind == "hist":
        need(df, a.x)
        col = pd.to_numeric(df[a.x], errors="coerce").dropna()
        if col.empty:
            eprint(f"ERROR: column {a.x!r} has no numeric values to histogram.")
            sys.exit(4)
        ax.hist(col, bins=a.bins, color="#3b6ea5", edgecolor="white")
        ax.set_xlabel(a.x)
        ax.set_ylabel("frequency")

    elif a.kind == "scatter":
        need(df, a.x, a.y)
        xv = pd.to_numeric(df[a.x], errors="coerce")
        yv = pd.to_numeric(df[a.y], errors="coerce")
        m = xv.notna() & yv.notna()
        if not m.any():
            eprint(f"ERROR: no overlapping numeric values in {a.x!r} and {a.y!r}.")
            sys.exit(4)
        ax.scatter(xv[m], yv[m], s=10, alpha=0.4, color="#3b6ea5")
        ax.set_xlabel(a.x)
        ax.set_ylabel(a.y)

    elif a.kind == "box":
        need(df, a.y)
        yv = pd.to_numeric(df[a.y], errors="coerce")
        if a.x:
            need(df, a.x)
            cats = df[a.x].astype("object").where(df[a.x].notna(), "NA")
            order = list(pd.Index(cats.unique()))
            if a.top and len(order) > a.top:
                order = list(cats.value_counts().head(a.top).index)
            data = [yv[(cats == c) & yv.notna()].values for c in order]
            ax.boxplot(data, tick_labels=[str(c) for c in order], showfliers=False)
            ax.set_xlabel(a.x)
            plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        else:
            ax.boxplot(yv.dropna().values, tick_labels=[a.y], showfliers=False)
        ax.set_ylabel(a.y)

    ax.set_title(a.title or f"{a.kind} chart")
    ax.grid(axis="both", alpha=0.2)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"OK: saved {a.kind} chart -> {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
