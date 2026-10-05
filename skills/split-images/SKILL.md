---
name: split-images
description: Leakage-safe train/val split for image data — the sacred leakage rule ported to computer vision. Splits by a SOURCE group (GroupKFold or a grouped holdout) so every image from one source lands in a single fold, CONSUMES inspect-images' near-duplicate clusters so rotated/near-identical copies can't straddle folds, and REFUSES a silent per-image split (no detectable group is not proof of independence). Emits image_splits/ id-lists + split_summary.json that carries the leakage provenance downstream. Use after inspect-images, before scaffold-train, whenever you must split images without inflating your metric.
allowed-tools: Bash, Read, Write, Glob
---

# split-images

Stage 2 of the **cv-modeler** pipeline, and the CV analog of `split-dataset`'s grouped/temporal split. The single most common way a CV project ships an inflated metric is a **per-image random split**: near-identical images (tiles of one frame, frames of one exposure, an image and its augmented copy) end up in both train and val, so the model "memorizes" the validation set. This skill makes that structurally hard.

It works on image **stems** (ids) only — it never loads pixels — and it enforces leakage safety in code, not prose.

## When to use
- After `inspect-images` (pass its `image_inspection.json` so near-dup clusters are folded into the groups).
- Before `scaffold-train` — it reads `image_splits/`.
- Any time you need a train/val split of images and want the grouping to prevent leakage, not just shuffle.

## Contract (important)
- **Group-keyed, never per-image by default.** `--group-by` is a regex on the stem (one capture group), a
  `coco:<field>`, or `none`. All images sharing a group id go to one fold. **`--group-by none` is refused
  (exit 4)** unless you pass `--allow-per-image-split` — absence of a filename group is *not* evidence the
  images are independent (a shared exposure/field/sequence can be invisible in the names or live in FITS headers).
- **Near-dup clusters are folded into the group key.** With `--inspection image_inspection.json`, each near-dup
  cluster is unioned into its group, so a rotated/flipped/near-identical copy cannot land in a different fold.
  If inspect-images flagged its detector `reliable:false`, no clusters are folded (and the report says so) —
  the group key alone must then capture provenance.
- **Sanity gates.** Refuses a per-image COCO field (`id`/`file_name`); refuses a regex that fails to match some
  filenames (an unmatched image would silently become its own group); warns when the key yields ~1 group per image.
- **Be honest about what the checks prove.** The `*_straddling_folds` counts are **regression guards** — 0 by
  construction once GroupKFold runs on the folded key (they catch a code bug, not unseen leakage). The one
  independent signal is **`near_dup_clusters_that_spanned_base_groups`**: >0 means the `--group-by` key *alone*
  would have leaked and folding the near-dups in is what prevented it. A near-dup the detector MISSED is in no
  check — that risk rides on the group key you chose. A guard failure aborts (exit 2).
- **Provenance propagates.** `split_summary.json` records `split_provenance` (`grouped:<key>` or
  `per-image-ACKED-leaky`) and `leakage_ack`, so `evaluate-detection` can stamp a leaky split's mAP as inflated.

## Steps
1. **Run it** (project venv):
   ```bash
   .venv/bin/python "${CLAUDE_SKILL_DIR}/scripts/split_images.py" \
       (--images <dir> | --annotations coco.json) --inspection image_inspection.json \
       --group-by '<regex|coco:field|none>' [--k 5 | --val-frac 0.2] [--seed 42] [--out image_splits]
   ```
   Needs scikit-learn + numpy (already in the venv).
2. **Pick `--group-by` from inspect-images' candidates** (or a COCO source field). Match the group count to the
   data's real sources: tiles of one frame → one group; frames of one exposure → one group. If nothing in the
   filename captures the source, the key is elsewhere (FITS headers) — don't force a per-image split.
3. **Read the integrity block.** Confirm `dup_clusters_straddling_folds==0` (the real leak check). Note the
   `split_provenance` — if it says `per-image-ACKED-leaky`, every downstream number is suspect.
4. **Hand off** to `scaffold-train` with `--splits image_splits/`.

## Output style
- Lead with the Mermaid `## At a glance`: image→groups→(+dup clusters)→grouped/per-image→leak check.
- State the provenance plainly. A per-image acked split is a red badge, not a silent default.
- Never present `groups_straddling_folds==0` as proof of leakage safety on its own.

## Grounding
Group-by-source is the CV port of the plugin's sacred leakage rule, grounded in primary studies: slice-vs-volume
(per-image vs per-source) splitting inflated performance 0.07–0.43 MCC / 5–30% accuracy
([OCT study](https://arxiv.org/pdf/2202.12267)); temporally-adjacent near-duplicate video frames split across
train/test leak because they are "not identical but very similar"
([object-detection leakage](https://arxiv.org/pdf/2410.23312)); and when the IID assumption is violated,
related samples (e.g. 2D slices of one 3D scan) must not straddle folds
([ML-pipelines pitfalls](https://arxiv.org/pdf/2311.04179)). GroupKFold with a source key is the standard
implementation; folding augmentation-aware near-dup clusters in addresses the augmentation-as-leakage mode from
the [AICrowd de-duplication study](https://arxiv.org/pdf/2304.02296).
