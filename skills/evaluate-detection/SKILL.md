---
name: evaluate-detection
description: Compute HONEST offline object-detection metrics (mAP, per-class AP, IoU matching) from a predictions file + COCO ground truth — preferring pycocotools (the metric real COCO competitions use) with a clearly-labeled approximate numpy fallback that accumulates detections globally per class. Reads split provenance and STAMPS a leaky/unknown split's mAP as inflated/untrustworthy, reports boxes-per-image and confidence so the COCO top-100 and low-threshold caveats are data-driven, and states plainly that offline mAP is neither the leaderboard nor a deployable operating point. Use after training to measure a detector on a held-out fold without fooling yourself.
allowed-tools: Bash, Read, Write
---

# evaluate-detection

Stage 4 of the **cv-modeler** pipeline, and the CV analog of `evaluate-model`. It answers "how good is this detector, offline?" — and it works hard to stop you over-reading the answer. Detection mAP is easy to inflate (leaky split, top-100 truncation, near-zero confidence thresholds) and easy to confuse with a leaderboard or a deployment metric. This skill computes it correctly and reports its limits in the same breath.

## When to use
- After real training (yours, on a GPU) produces a `preds.csv` via the bundle's `predict.py`.
- To measure mAP / per-class AP on the **held-out** fold from `split-images`, with the split provenance attached.
- Before `make-detection-submission`, to sanity-check the detector — knowing a good offline number is necessary, not sufficient.

## Contract (important)
- **Reads a predictions file + COCO GT; writes metrics + report.** Never trains, never modifies inputs.
- **Predictions schema is the pipeline contract:** `image_id, class_id, score, x, y, w, h` where `image_id` is
  the file **stem**, `class_id` is **0-based YOLO**, and `x,y,w,h` are **top-left pixels** (as scaffold-train's
  `predict.py` emits). GT classes are aligned to the same 0-based space via `class_map.json`.
- **Prefers pycocotools; numpy is an APPROXIMATE fallback.** With pycocotools installed it reports the metric
  real COCO comps use (maxDets=100). The numpy fallback accumulates detections **globally per class** (not
  per-image-then-average) and states its AP-integration method — but it has no iscrowd/area-range/maxDets
  handling and is labeled approximate.
- **Split provenance stamps the result.** With `--split image_splits/`, eval is restricted to the val set and the
  report headlines the provenance: a per-image/leaky split → "mAP likely inflated"; no `--split` → "provenance
  UNKNOWN, may be on training data". The sidecar carries `offline_only:true, matches_leaderboard:false,
  is_deployable_operating_point:false, threshold_free:true`.
- **Caveats are data-driven.** It reports boxes-per-image (flagging the COCO top-100 truncation when exceeded)
  and min confidence (flagging near-zero thresholds).
- **Must match the comp's metric.** VOC@0.5 and COCO 0.50:0.95 are different numbers; the report says which it
  computed and reminds you to match the competition's exact definition.

## Steps
1. **Run it** (project venv):
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/evaluate-detection/scripts/evaluate_detection.py" \
       --predictions preds.csv --annotations coco.json --class-map cv_train_scaffold/class_map.json \
       --split image_splits/ [--iou 0.5] [--coco] [--no-pycocotools]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/evaluate-detection/scripts/evaluate_detection.py`.)
   `pycocotools` is optional but preferred (`.venv/bin/pip install pycocotools`).
2. **Read the provenance badge first.** If it's red (per-image) or ❓ (unknown), the mAP is untrustworthy — fix
   the split before believing the number.
3. **Read the caveats.** Boxes/image over 100 and near-zero confidences both mean the headline mAP hides behavior
   that matters. Confirm the metric definition matches the competition's.
4. **Hand off** to `make-detection-submission`.

## Output style
- Lead with the Mermaid `## At a glance`: preds → mAP (+which tool) → split badge → the three negative assertions.
- Never present offline mAP as a leaderboard position or a deployment-ready number.

## Grounding
COCO mAP scores only the 100 highest-confidence boxes per image, so extra low-confidence boxes are "not
penalized by the evaluation function" ([mAP misconceptions](https://pmc.ncbi.nlm.nih.gov/articles/PMC8271464/)),
and reported benchmark confidence thresholds are usually undocumented and "ridiculously low (<5%)", so a
leaderboard mAP integrates over an effectively-zero operating point. Data leakage "artificially inflates"
detection metrics that then fail on deployment ([object-detection leakage](https://arxiv.org/pdf/2410.23312)) —
hence the split-provenance stamp. VOC (single IoU 0.5) vs COCO (0.50:0.95) are materially different numbers, so
the pipeline must match the competition's exact metric rather than assume one mAP.
