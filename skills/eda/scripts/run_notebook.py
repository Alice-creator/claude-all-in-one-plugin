#!/usr/bin/env python3
"""run_notebook.py — execute a notebook IN PLACE and report any cell errors.

This is the execution engine for the iterate-on-error loop: it runs every cell
(does not stop at the first failure), writes the executed notebook back with its
outputs, then reports which cells errored so the caller can fix and re-run.

Exit 0 = all cells ran clean. Exit 3 = one or more cells errored (details on stderr).

Usage:
    python3 run_notebook.py <notebook.ipynb> [--timeout SECONDS]
"""
import argparse
import sys


def errored_cells(nb):
    """Yield (index, ename, evalue) for every code cell that produced an error output."""
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        for out in cell.get("outputs", []):
            if out.get("output_type") == "error":
                yield i, out.get("ename", "Error"), out.get("evalue", "")


def main():
    ap = argparse.ArgumentParser(description="Execute a notebook in place; report cell errors.")
    ap.add_argument("notebook")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()

    try:
        import nbformat
        from nbclient import NotebookClient
    except ImportError:
        print("ERROR: pip install nbformat nbclient ipykernel matplotlib", file=sys.stderr)
        sys.exit(2)

    nb = nbformat.read(a.notebook, as_version=4)
    # allow_errors=True so every cell runs and errors are captured (not aborted at the first).
    NotebookClient(nb, timeout=a.timeout, kernel_name="python3", allow_errors=True).execute()
    nbformat.write(nb, a.notebook)

    errs = list(errored_cells(nb))
    if errs:
        for i, ename, evalue in errs:
            print(f"CELL {i} ERROR: {ename}: {evalue}", file=sys.stderr)
        sys.exit(3)
    print(f"OK: {len(nb.cells)} cells executed, no errors -> {a.notebook}")


if __name__ == "__main__":
    main()
