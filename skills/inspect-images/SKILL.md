---
name: inspect-images
description: "Become one with the data" for an image dataset BEFORE any split or training — detect 16-bit/astronomical PNGs a naive 8-bit loader would silently truncate, find augmentation-aware near-duplicates (the leakage-risk signal that split-images consumes), summarize COCO annotations (class balance, box sizes, thin/elongated objects), and propose provenance group-key candidates. Emits image_inspection.json + a Mermaid-led report. Use as the first step of the cv-modeler pipeline, or whenever you get an image dataset and need to know its bit-depth, duplication, and how to split it without leaking.
allowed-tools: Bash, Read, Write, Glob
---

# inspect-images

Stage 1 of the **cv-modeler** (computer-vision) pipeline. The fastest way to ship an inflated CV metric is to (a) let a 16-bit astronomical image get 8-bit-truncated so faint signal vanishes, or (b) split near-duplicate images across train/val so the model "memorizes" the val set. This skill surfaces both **before** you split or train.

It does **not** decide the split or train anything. It inspects, measures honestly, and writes a sidecar that `split-images` reads.

## When to use
- First thing in the cv-modeler pipeline, right after `frame-ml-problem` routes an image goal here.
- When you receive an image dataset and need its bit-depth, size mix, duplication, and class/box distribution.
- Before `split-images` — its `image_inspection.json` is the near-dup input that makes the split leakage-safe.

## Contract (important)
- **Never modifies images.** Reads only; writes `image_inspection.json` + `image_inspection_report.md`.
- **16-bit is flagged, not silently handled.** If any image is 16-bit (`I;16`), the report says a naive 8-bit
  loader (Ultralytics reads via `cv2` then divides by 255) will **truncate** it — scaffold-train must normalize
  per-image first. This skill keeps 16-bit data at full depth while inspecting.
- **Near-dup detection is augmentation-aware AND honest about its own limits.** It normalizes each image
  per-image (percentile), then a higher-res dHash canonicalized over the 8 rot/flip orientations, so a
  rotated/flipped copy lands in the same cluster. On sparse-sky imagery a perceptual hash can **collapse**
  (every image hashes alike); the skill measures hash entropy and sets `dup_detector_reliable:false` rather than
  reporting "everything is a duplicate". When unreliable, it says so and tells you to use a provenance key.
- **Group-key candidates are GUESSES from filenames, not the truth.** The real source key (exposure/field/night)
  may live in FITS headers or a manifest. The skill proposes regexes; a human confirms one for `split-images`.
- **Samples honestly.** `--sample 0` (default) hashes every image; if you cap it, the report states near-dups
  outside the sample were not detected.

## Steps
1. **Run it** (project venv):
   ```bash
   .venv/bin/python "${CLAUDE_SKILL_DIR}/scripts/inspect_images.py" \
       --images <image_dir> [--annotations annotations_coco.json] [--sample 0] [--out image_inspection.json]
   ```
   Needs Pillow (`.venv/bin/pip install pillow`) + numpy; `astropy` only if you point it at `.fits` files.
2. **Read the three signals, don't just dump them:**
   - **Bit depth** — if `is_16bit`, remember scaffold-train must normalize before YOLO.
   - **Near-dup detector** — check `dup_detector.reliable`. If `true`, note the clusters (they become split groups).
     If `false`, ignore the clusters and plan to split by a provenance key.
   - **Group-key candidates** — pick the regex whose group count matches your understanding of the data's
     sources (tiles of one frame → one group; frames of one exposure → one group). If none fit, the key isn't
     in the filename — look at FITS headers / a manifest.
3. **Hand off** to `split-images`, passing `--inspection image_inspection.json` and the chosen `--group-by`.

## Output style
- Lead with the Mermaid `## At a glance`: image count + bit-depth, dup-detector verdict, group-key candidate count.
- State plainly whether the dup detector is reliable on this data — a collapsed detector is a finding, not a failure.
- Never present near-dup clusters from an unreliable detector as truth.

## Grounding
The leakage rule this feeds is grounded: splitting image data at the per-image (vs source) level inflates
reported performance 0.07–0.43 MCC / 5–30% accuracy ([OCT study](https://arxiv.org/pdf/2202.12267)), and
augmentation is itself a leakage vector — augmenting before the split lands variants of one image in both
train and val ([same study]; [ML-pipelines pitfalls](https://arxiv.org/pdf/2311.04179)). Augmentation-aware
perceptual hashing (hashing the rotated/flipped copies) is exactly how the [AICrowd Mapping Challenge
de-duplication](https://arxiv.org/pdf/2304.02296) found 38.7% of "training" images were augmented duplicates of
validation images (93% val-in-train). That study worked on high-texture aerial imagery; on sparse astronomical
sky the same hash can fail to discriminate — hence the explicit reliability guard here.
