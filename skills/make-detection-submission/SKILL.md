---
name: make-detection-submission
description: Format an object-detection predictions file into a competition submission (per-image "confidence x y w h" prediction strings aligned to sample_submission, or a COCO-detection results.json) and VALIDATE the format — every sample image present, columns matching, box tokens well-formed. It validates FORMAT not correctness (a well-formatted file of wrong boxes scores ~0) and refuses to guess the per-box field order/units, which only the competition's sample/rules can confirm. Warns loudly on empty/sparse submissions. Use as the last cv-modeler step, after evaluate-detection, before a human submits.
allowed-tools: Bash, Read, Write
---

# make-detection-submission

Stage 5 (final) of the **cv-modeler** pipeline. A submission fails on format before strategy ever matters: a missing image id, the wrong column names, or the box fields in the wrong order all score zero regardless of how good the detector is. This skill produces the submission in the competition's shape and validates it — while being explicit that a valid format says nothing about whether the boxes are right.

## When to use
- After you have a `preds.csv` (from the bundle's `predict.py`) and the competition's `sample_submission`.
- As the last step before a human submits.

## Contract (important)
- **Reads predictions + the comp's sample_submission; writes the submission + a manifest.** Never trains or
  modifies inputs.
- **Every sample image appears.** Images with no detections get an empty prediction string (not dropped) — most
  detection comps require the full id set. Predicted images not in the sample are dropped (and counted).
- **Validates FORMAT, not correctness.** The manifest carries `validates:"format_only"` and
  `scores_correctness:"not_validated"`. A well-formatted submission of garbage boxes scores ~0; this tool cannot
  and does not tell you the boxes are good.
- **Refuses to guess the box order/units.** Default is `conf,x,y,w,h` (top-left pixels), flagged
  `box_order_confirmed:false` and printed as MUST-CONFIRM against the competition's own sample/rules. Change it
  with `--box-order`.
- **Warns on empty/sparse output.** `0` images with detections (or <5%) prints a loud "this will score ~0".
- **Two formats:** `streak` (per-image prediction strings aligned to sample_submission) and `coco`
  (a COCO-detection `results.json`; use `--class-map` to decode 0-based YOLO ids back to COCO category ids).

## Steps
1. **Run it** (project venv):
   ```bash
   .venv/bin/python "${CLAUDE_SKILL_DIR}/scripts/make_detection_submission.py" \
       --predictions preds.csv --sample-submission sample_submission.csv \
       [--format streak|coco] [--box-order conf,x,y,w,h] [--conf-threshold 0.0] [--max-per-image 0] \
       [--class-map cv_train_scaffold/class_map.json]
   ```
2. **Confirm the box order/units** against the competition's sample row — this is the one thing the tool cannot
   verify for you. Fix `--box-order` if the comp expects e.g. `x,y,w,h,conf` or normalized coords.
3. **Read the warnings.** An empty or sparse submission means the detector (or the confidence threshold) is off —
   go back to `evaluate-detection`, don't submit a zero.
4. **Hand to the human to submit.** The submit action is theirs.

## Output style
- Lead with the Mermaid `## At a glance`: preds → images/detections → "format valid ✓ / correctness NOT validated" → submit.
- Always restate that this validates shape only, and that the box order/units must be confirmed.
- If the competition has a second sub-task (e.g. the ESA poisoned-model / unlearning), remind the user a
  detection submission alone does not complete it.

## Grounding
Detection submissions are per-image box lists scored by an mAP-style metric; the exact serialization
(`confidence x y w h` order, pixel vs normalized, top-left vs center) is competition-defined and is the only
authority — assuming it is a classic silent zero-score. This mirrors the plugin's `scaffold-submission`
discipline for agent comps (get the packaging exactly right, and never present a format-valid artifact as a good
result). The "format ≠ correctness" boundary is the same honesty rule the rest of the plugin holds: offline
validity is necessary, never sufficient.
