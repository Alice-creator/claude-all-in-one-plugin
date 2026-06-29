#!/usr/bin/env python3
"""run_sql.py — run a SQL query directly against a data FILE via DuckDB (no server).

Registers the input file (CSV/TSV/Parquet/JSON) as a view named `data`, so you can
write `SELECT ... FROM data ...`. You may also reference the file by its quoted path
inside the query (DuckDB's read_csv_auto / read_parquet work too).

READ-ONLY — and ENFORCED, not assumed. DuckDB runs arbitrary SQL: left unchecked,
`COPY (...) TO 'file'` overwrites disk, `ATTACH`/`INSTALL`/`LOAD` reach the filesystem
and network. So before execution we parse the SQL with DuckDB's own parser and allow
ONLY a single read-only statement (SELECT / WITH-select / EXPLAIN / DESCRIBE / SHOW).
Anything that could write or have a side effect (COPY TO, INSERT/UPDATE/DELETE, ATTACH,
INSTALL/LOAD, CREATE/DROP/ALTER, SET, PRAGMA, CALL, EXPORT) is refused. The source file
and your disk are therefore never modified. (This bounds *writes*; a SELECT can still
read other files you already have access to — it is not a filesystem sandbox.)

Exit 0 = query ran. Exit 1 = file not found. Exit 2 = duckdb missing.
Exit 3 = query/load error. Exit 4 = refused (non-read-only SQL).

Usage:
    python3 run_sql.py <file.csv|.tsv|.parquet|.json> "<SQL>" [--limit N]

Examples:
    python3 run_sql.py data.parquet "SELECT Brand, COUNT(*) c FROM data GROUP BY Brand ORDER BY c DESC"
    python3 run_sql.py data.csv "SELECT * FROM data WHERE Price > 50000" --limit 20
"""
import argparse
import os
import sys

# DuckDB StatementType.name values that cannot write or have side effects. Compared by
# NAME (not enum identity) so it stays robust across DuckDB versions / enum additions.
# (In current DuckDB, DESCRIBE/SHOW/PRAGMA all classify as SELECT; the extra names are
# kept defensively in case a version reports them distinctly — writes never do.)
READ_ONLY_STATEMENTS = {"SELECT", "EXPLAIN", "DESCRIBE", "SHOW"}


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def assert_read_only(con, sql):
    """Refuse anything that isn't a SINGLE read-only statement (exit 4).

    Uses DuckDB's parser (extract_statements) — no execution — to classify the SQL.
    Falls back to a conservative leading-keyword check only if that API is unavailable
    (very old duckdb); the fallback rejects multi-statement input and any statement
    that doesn't begin with a known read-only keyword."""
    try:
        statements = con.extract_statements(sql)
    except AttributeError:
        return _keyword_guard(sql)
    except Exception as e:
        # A parse error here will resurface as a clean query error at execution time.
        eprint(f"ERROR parsing SQL: {e}")
        sys.exit(3)
    if len(statements) != 1:
        eprint(f"REFUSED: expected exactly one statement, got {len(statements)}. "
               "Run one read-only query at a time (no ';'-separated scripts).")
        sys.exit(4)
    st_name = getattr(statements[0].type, "name", str(statements[0].type)).upper()
    if st_name not in READ_ONLY_STATEMENTS:
        eprint(f"REFUSED: non-read-only statement (type={st_name}). query-sql only runs "
               "read-only queries (SELECT/WITH/EXPLAIN/DESCRIBE/SHOW); writes such as COPY TO, "
               "INSERT, ATTACH, INSTALL/LOAD, CREATE/DROP, SET are blocked so nothing is modified.")
        sys.exit(4)


def _keyword_guard(sql):
    """Backstop for duckdb builds without extract_statements: leading-keyword allowlist."""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        eprint("REFUSED: multiple statements not allowed (run one read-only query at a time).")
        sys.exit(4)
    head = stripped.lstrip("( \t\n").split(None, 1)[0].upper() if stripped else ""
    if head not in {"SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW", "TABLE", "FROM", "VALUES"}:
        eprint(f"REFUSED: statement starts with '{head or '(empty)'}' — only read-only queries are allowed.")
        sys.exit(4)


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

    assert_read_only(con, a.sql)  # refuse non-read-only SQL before executing (exit 4)

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
