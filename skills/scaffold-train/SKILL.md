---
name: scaffold-train
description: Generate a RUNNABLE Ultralytics YOLO object-detection training bundle from images + COCO annotations + a leakage-safe split — a config-driven transfer-learning harness (data.yaml, prepare_data.py, train.py, predict.py, pinned requirements) with a COCO→0-based class map shared downstream, PER-IMAGE 16-bit→8-bit normalization (never silent truncation), and a CPU smoke test that asserts YOLO loaded >0 labels. It SCAFFOLDS, it does NOT train a competitive model — real training is GPU-hours you run. Use after split-images to get an immediately-runnable "does the whole pipeline execute" bundle before you spend GPU time.
allowed-tools: Bash, Read, Write, Glob
---

# scaffold-train

Stage 3 of the **cv-modeler** pipeline, and the CV analog of `scaffold-submission`: it generates the harness and safety-by-construction, not the result. The fastest way to waste GPU-hours on a detection competition is to discover — after training — that your data was mis-converted (wrong class ids, 16-bit truncated, labels YOLO never loaded). This skill catches those by construction and with a smoke test, then hands real training to you.

**It does not train a competitive model in-session.** Both Ultralytics and MMDetection state CPU training is too slow to be competitive; real training defaults to GPU/VRAM. The CPU smoke test only proves the pipeline runs end-to-end.

## When to use
- After `split-images` (it reads `image_splits/` and the split provenance).
- To get a runnable YOLO training bundle whose data conversion is correct (class remap, 16-bit normalization,
  images/labels layout) before you spend GPU time.
- When you want the composition contract (predictions schema, class map) generated correctly so
  `evaluate-detection` and `make-detection-submission` compose unchanged.

## Contract (important)
- **Reads images + COCO + splits; writes a new bundle dir.** Never modifies source images or annotations.
- **Shared class map, built correctly.** COCO `category_id`s are remapped to 0-based contiguous YOLO ids via
  `sorted(set(ids))` (never the naive `id-1`, which breaks on non-contiguous ids). `class_map.json` is the
  single source of truth `evaluate-detection` and `make-detection-submission` consume.
- **16-bit is normalized, never silently truncated.** `prepare_data.py` converts each image to 8-bit RGB with a
  **per-image** percentile stretch (dataset-global stats would leak across the split) and writes a
  `normalization_report.json` stating the loss (65536→256 levels; faint objects may vanish). `data.yaml` points
  only at the **converted** `images/{train,val}` tree, never the raw 16-bit source.
- **Layout is load-bearing.** YOLO finds labels by swapping `/images/`→`/labels/` in the path, so
  `prepare_data.py` writes the parallel `images/`+`labels/` trees with matching basenames.
- **Smoke test asserts >0 labels.** It runs the real `prepare_data.py` on a tiny subset into a quarantined
  `smoke_throwaway/`, then asserts YOLO would load >0 label boxes (a green smoke on 0 labels is meaningless),
  then — if ultralytics is installed — runs 1 CPU epoch. Weight-download/AMP/offline failures are reported
  honestly; the bundle still generates without ultralytics.
- **The manifest carries NEGATIVE assertions.** `produces_trained_model:false`, `weights_are_throwaway:true`,
  and `smoke:{executed, executed_without_error, labels_loaded, trained}` — never a bare `ok` — so no downstream
  report can render a smoke run as a real result.
- **Detection only; no unlearning.** Task is `detect`. It does NOT touch the poisoned_model.pth / machine-unlearning
  sub-task (out of scope, unresearched).

## Steps
1. **Run it** (project venv):
   ```bash
   .venv/bin/python "${CLAUDE_SKILL_DIR}/scripts/scaffold_train.py" \
       --images <dir> --annotations coco.json --splits image_splits/ \
       [--model yolo11n.pt] [--imgsz 640] [--epochs 100] [--out-dir cv_train_scaffold] [--no-smoke]
   ```
   `ultralytics`
   is only needed for the smoke training step — the bundle generates without it (exit note, not exit error).
2. **Read the smoke line, don't just dump it.** ✅ = pipeline runs. ❌ at `prepare_data` (0 labels) means the
   split ids / category ids don't line up — fix that before spending GPU. A YOLO-train failure is usually a
   weights download / AMP check needing network; the bundle is still valid.
3. **Point out what's the user's to run:** `prepare_data.py` → `train.py` (on a GPU) → `predict.py`. Edit
   `train_config.yaml` (epochs/imgsz/batch/device) first.
4. **Hand off** the eventual `preds.csv` to `evaluate-detection` and `make-detection-submission`.

## Output style
- Lead with the Mermaid `## At a glance` and the smoke line. State plainly the split provenance (a per-image
  leaky split makes every future metric suspect) and that this is a scaffold, not a model.
- Always restate: real training is GPU-hours you run; the smoke weights are throwaway.

## Grounding
Transfer-learning-first + config-driven is how [Ultralytics YOLO](https://docs.ultralytics.com/modes/train) and
[MMDetection](https://mmdetection.readthedocs.io/en/latest/user_guides/train.html) are built (pretrained
checkpoint + YAML config + one entrypoint), which is why "generate a runnable script + config, CPU-smoke, hand
real training to the user" is the natural artifact; MMDetection states plainly it does "not recommend CPU for
training because it is too slow." The COCO→YOLO label format (`cls cx cy w h`, normalized, 0-based) is from the
[Ultralytics dataset docs](https://docs.ultralytics.com/datasets/detect/); per-image (not dataset-global)
normalization avoids the preprocessing-leakage mode described in the
[ML-pipelines pitfalls study](https://arxiv.org/pdf/2311.04179). Real astronomical streak detectors fine-tune a
pretrained YOLO (e.g. YOLO11-OBB / YOLOv7) rather than training from scratch, matching the transfer-learning default.
