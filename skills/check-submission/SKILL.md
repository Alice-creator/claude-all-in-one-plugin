---
name: check-submission
description: Validate a tabular submission CSV against the competition's own sample/format file (Kaggle sample_submission.csv, DrivenData submission_format.csv, Zindi SampleSubmission.csv, or any platform's equivalent) before it is uploaded — exact columns and order, row count, missing / extra / duplicated ids, empty or NaN cells, text where the format is numeric, and constant prediction columns. It validates FORMAT only and says so: a perfectly formatted file of bad predictions passes. Writes a submission_check.json sidecar. Use before every tabular submission, after train-tune or any script that writes a submission file. For object detection use make-detection-submission; for agent bundles use scaffold-submission.
allowed-tools: Bash, Read
---

# check-submission

A submission with one missing id, one renamed column or one NaN either gets rejected or scores far below the model's real quality, and it costs one of the day's limited submissions to find out. This skill checks the file against the format the platform itself ships, locally, for free.

## When to use
- Before every upload of a tabular (CSV) submission.
- After changing the inference code, the id handling or the post-processing.

## Contract (important)
- **The format file is the authority.** Columns, order and the id set come from the platform's sample/format file, never from memory.
- **Format only.** `submission_check.json` carries `validates: "format_only"` and `scores_correctness: "not_validated"`. Restate that whenever reporting a `VALID`.
- **Errors block, warnings inform.** Exit 1 on any error (wrong columns, wrong row count, missing/extra/duplicated ids, empty/NaN cells, text in a numeric column). Warnings (column order, id order, a constant column) do not block but must be read.
- **Read-only.** Never edits the submission; the fix belongs in the code that wrote it.
- **The human uploads.** This skill never submits.

## Steps
1. **Run it:**
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_submission.py" \
       --submission submissions/<file>.csv --format-file data/raw/<sample-or-format-file>.csv \
       [--id-column <name>]
   ```
   The id column defaults to the first column of the format file.
2. **On `INVALID`:** fix the code that produced the file, regenerate, re-run. Do not hand-edit the CSV.
3. **On `VALID`:** record the file name in `experiments/log.csv` (`submitted_file`) and hand it to the user to upload. After upload, the user adds the public score to the same row.

## Output style
- One line verdict (`VALID` / `INVALID`, format only), then the errors, then the warnings.
- Never call a `VALID` file "good": the score is unknown until the platform scores it.

## Grounding
Platforms reject or zero-score submissions whose ids or columns do not match their format file, and every platform ships such a file with the data (Kaggle `sample_submission.csv`, DrivenData `submission_format.csv`, Zindi `SampleSubmission.csv`). The format-versus-correctness boundary is the same one `make-detection-submission` holds for detection.
