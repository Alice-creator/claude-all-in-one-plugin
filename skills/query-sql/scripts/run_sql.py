#!/usr/bin/env python3
"""run_sql.py — run a SQL query directly against a data FILE via DuckDB (no server).

Registers the input file (CSV/TSV/Parquet/JSON) as a view named `data`, so you can
write `SELECT ... FROM data ...`. You may also reference the file by its quoted path
inside the query (DuckDB's read_csv_auto / read_parquet work too). READ-ONLY: the
source file is never modified.

Exit 0 = query ran. Exit 1 = file not found. Exit 2 = duckdb missing. Exit 3 = query/load error.

Usage:
    python3 run_sql.py <file.csv|.tsv|.parquet|.json> "<SQL>" [--limit N]

Examples:
    python3 run_sql.py data.parquet "SELECT Brand, COUNT(*) c FROM data GROUP BY Brand ORDER BY c DESC"
    python3 run_sql.py data.csv "SELECT * FROM data WHERE Price > 50000" --limit 20
"""
import argparse
import os
import sys


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def reader_expr(path):
    """Return a DuckDB table-function call that reads `path` as a relation."""
    ext = os.path.splitext(path)[1].lower()
    p = path.replace("'", "''")  # escape single quotes for the SQL literal
    if ext == ".parquet":
        return f"read_parquet('{p}')"
    if ext == ".json":
        return f"read_json_auto('{p}')"
    if ext == ".tsv":
        return f"read_csv_auto('{p}', delim='\t')"
    # .csv, .txt, and anything else: let DuckDB sniff the format
    return f"read_csv_auto('{p}')"


def main():
    ap = argparse.ArgumentParser(description="Run SQL against a data file via DuckDB (read-only).")
    ap.add_argument("file", help="Path to the data file (CSV/TSV/Parquet/JSON).")
    ap.add_argument("sql", help="SQL query; reference the file as the table `data`.")
    ap.add_argument("--limit", type=int, default=50,
                    help="Max rows to print (default 50; the query itself is unchanged). Use 0 for all.")
    a = ap.parse_args()

    if not os.path.exists(a.file):
        eprint(f"ERROR: file not found: {a.file}")
        sys.exit(1)
    try:
        import duckdb
    except ImportError:
        eprint("ERROR: duckdb not installed. Run: pip install duckdb")
        sys.exit(2)

    con = duckdb.connect()  # in-memory, ephemeral — nothing is written to disk
    try:
        # Expose the file as a view named `data` so queries can `... FROM data ...`.
        con.execute(f"CREATE VIEW data AS SELECT * FROM {reader_expr(os.path.abspath(a.file))}")
    except Exception as e:
        eprint(f"ERROR loading file as view 'data': {e}")
        sys.exit(3)

    try:
        rel = con.sql(a.sql)
    except Exception as e:
        eprint(f"ERROR running query: {e}")
        sys.exit(3)

    if rel is None:  # statement returned no result set
        print("OK: statement executed (no rows returned).")
        return

    df = rel.df()
    total = len(df)
    shown = df if a.limit <= 0 else df.head(a.limit)

    import pandas as pd  # bundled with duckdb's .df(); used only for display
    with pd.option_context("display.max_columns", None, "display.width", 200,
                           "display.max_colwidth", 60):
        print(shown.to_string(index=False) if len(shown) else "(no rows)")

    if a.limit > 0 and total > a.limit:
        print(f"\n... {total:,} rows total; showing first {a.limit}. Use --limit 0 for all.")
    else:
        print(f"\n{total:,} row(s).")


if __name__ == "__main__":
    main()
