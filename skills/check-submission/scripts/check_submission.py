#!/usr/bin/env python3
"""Validate a tabular submission CSV against the competition's sample/format file.

Checks the things that make a submission score zero or get rejected regardless of model
quality: column names and order, row count, the id set (missing / extra / duplicated ids),
empty or NaN cells, and value types that differ from the sample. It validates FORMAT only —
a perfectly formatted file of bad predictions passes.

Platform-agnostic: the format file is whatever the platform ships (Kaggle
`sample_submission.csv`, DrivenData `submission_format.csv`, Zindi `SampleSubmission.csv`, ...).

Writes submission_check.json (machine-readable sidecar) next to the submission.

Exit codes: 0 valid · 1 invalid · 3 unreadable input.

NOTE: helpers here are deliberately self-contained (helpers are copied byte-identical
across scripts rather than importing a shared module).
"""
import argparse
import csv
import json
import math
import os
import sys

MISSING_TOKENS = {"", "nan", "NaN", "NA", "null", "None"}
EXAMPLE_LIMIT = 5


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def read_csv(path):
    if not os.path.exists(path):
        die(f"not found: {path}", 3)
    try:
        with open(path, newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            rows = [row for row in reader]
    except StopIteration:
        die(f"{path} is empty", 3)
    except Exception as error:
        die(f"could not read {path}: {error}", 3)
    return header, rows


def value_kind(text):
    """'number' when the cell parses as a finite float, 'missing' for empty/NaN tokens, else 'text'."""
    if text.strip() in MISSING_TOKENS:
        return "missing"
    try:
        return "number" if math.isfinite(float(text)) else "missing"
    except ValueError:
        return "text"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--submission", required=True)
    parser.add_argument("--format-file", required=True, help="the platform's sample/format submission file")
    parser.add_argument("--id-column", default=None, help="defaults to the first column of the format file")
    arguments = parser.parse_args()

    format_header, format_rows = read_csv(arguments.format_file)
    submission_header, submission_rows = read_csv(arguments.submission)
    id_column = arguments.id_column or format_header[0]
    errors, warnings = [], []

    if submission_header != format_header:
        if sorted(submission_header) == sorted(format_header):
            warnings.append(f"columns match but order differs: {submission_header} vs {format_header}")
        else:
            errors.append(f"columns differ: submission {submission_header} vs format {format_header}")

    if len(submission_rows) != len(format_rows):
        errors.append(f"row count {len(submission_rows)} ≠ format file {len(format_rows)}")

    malformed_rows = [index + 2 for index, row in enumerate(submission_rows) if len(row) != len(submission_header)]
    if malformed_rows:
        errors.append(f"{len(malformed_rows)} rows have the wrong number of cells (lines {malformed_rows[:EXAMPLE_LIMIT]})")

    if id_column in format_header and id_column in submission_header:
        format_id_position = format_header.index(id_column)
        submission_id_position = submission_header.index(id_column)
        format_ids = [row[format_id_position] for row in format_rows if len(row) > format_id_position]
        submission_ids = [row[submission_id_position] for row in submission_rows if len(row) > submission_id_position]
        seen_ids, duplicated_ids = set(), []
        for identifier in submission_ids:
            if identifier in seen_ids:
                duplicated_ids.append(identifier)
            seen_ids.add(identifier)
        missing_ids = sorted(set(format_ids) - seen_ids)
        extra_ids = sorted(seen_ids - set(format_ids))
        if duplicated_ids:
            errors.append(f"{len(duplicated_ids)} duplicated ids, e.g. {duplicated_ids[:EXAMPLE_LIMIT]}")
        if missing_ids:
            errors.append(f"{len(missing_ids)} ids from the format file are missing, e.g. {missing_ids[:EXAMPLE_LIMIT]}")
        if extra_ids:
            errors.append(f"{len(extra_ids)} ids are not in the format file, e.g. {extra_ids[:EXAMPLE_LIMIT]}")
        if not (duplicated_ids or missing_ids or extra_ids) and submission_ids != format_ids:
            warnings.append("same ids but in a different order (most platforms accept this; some do not)")
    else:
        errors.append(f"id column '{id_column}' missing from the submission or the format file")

    for column in submission_header:
        if column == id_column or column not in format_header:
            continue
        submission_position = submission_header.index(column)
        format_position = format_header.index(column)
        submission_kinds = [value_kind(row[submission_position]) for row in submission_rows if len(row) > submission_position]
        format_kinds = {value_kind(row[format_position]) for row in format_rows if len(row) > format_position} - {"missing"}
        missing_count = submission_kinds.count("missing")
        if missing_count:
            errors.append(f"column '{column}': {missing_count} empty/NaN cells")
        if format_kinds == {"number"} and "text" in submission_kinds:
            errors.append(f"column '{column}': the format file is numeric but the submission has text values")
        if submission_kinds and len(set(submission_kinds) - {"missing"}) == 1 and len(set(
                row[submission_position] for row in submission_rows if len(row) > submission_position)) == 1:
            warnings.append(f"column '{column}': every row has the same value — a constant submission scores like a dummy")

    status = "VALID" if not errors else "INVALID"
    summary = {
        "status": status,
        "validates": "format_only",
        "scores_correctness": "not_validated",
        "submission": os.path.abspath(arguments.submission),
        "format_file": os.path.abspath(arguments.format_file),
        "id_column": id_column,
        "rows": len(submission_rows),
        "errors": errors,
        "warnings": warnings,
    }
    sidecar_path = os.path.join(os.path.dirname(os.path.abspath(arguments.submission)), "submission_check.json")
    with open(sidecar_path, "w") as handle:
        json.dump(summary, handle, indent=2)

    print(f"status: {status} (format only — correctness is NOT validated)")
    for error in errors:
        print(f"  ✗ {error}")
    for warning in warnings:
        print(f"  ⚠ {warning}")
    print(f"wrote {sidecar_path}")
    sys.exit(0 if status == "VALID" else 1)


if __name__ == "__main__":
    main()
