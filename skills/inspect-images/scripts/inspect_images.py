#!/usr/bin/env python3
"""inspect-images: "become one with the data" for an image dataset BEFORE splitting or training.

Three honest jobs:
  1. Bit-depth / size / channel inspection — detect 16-bit (I;16) astronomical PNGs that a naive
     8-bit loader (Ultralytics reads via cv2 and divides by 255) would silently truncate.
  2. Augmentation-aware near-duplicate detection — normalize each image (per-image percentile), then a
     higher-res dHash canonicalized over the 8 rot/flip orientations, so a rotated/flipped copy hashes to
     the SAME cluster. This is the leakage-risk signal split-images CONSUMES (near-dups must not straddle
     folds). On sparse sky imagery a perceptual hash can collapse — we measure hash entropy and REFUSE to
     claim reliability when it does (dup_detector_reliable:false) rather than reporting "everything is a dup".
  3. Provenance group-key candidates — from filename tokens (and, for FITS, header hints) — proposals a
     human confirms; NOT asserted as the true source grouping.

Emits image_inspection.json (a sidecar split-images reads) + image_inspection_report.md (Mermaid-led).
Never modifies images. Samples honestly (reports coverage).

Exit codes: 0 ok · 2 dependency/IO issue · 3 bad/missing input.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical across
scripts rather than importing a shared module).
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


IMG_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
FITS_EXTS = (".fits", ".fit", ".fts")


def list_images(images_dir):
    out = []
    for root, _dirs, files in os.walk(images_dir):
        # skip generated trees so re-runs don't inspect their own converted output / labels
        base = os.path.basename(root)
        if base in ("labels", "smoke_throwaway") or root.endswith(os.sep + "labels"):
            continue
        for fn in files:
            if fn.lower().endswith(IMG_EXTS + FITS_EXTS):
                out.append(os.path.join(root, fn))
    return sorted(out)


def stem_of(path):
    """Canonical image_id used across the whole CV pipeline: the file basename WITHOUT extension."""
    return os.path.splitext(os.path.basename(str(path)))[0]


def load_gray_array(path):
    """Return (gray float32 2D array, meta dict). meta has mode/bit_depth/is_16bit/width/height/channels/pmin/pmax.
    16-bit stays 16-bit here (no truncation) — the caller normalizes per-image for hashing/display."""
    ext = os.path.splitext(path)[1].lower()
    if ext in FITS_EXTS:
        try:
            from astropy.io import fits
        except Exception:
            die("FITS image found but astropy is not installed — `.venv/bin/pip install astropy` (optional dep) "
                "to inspect FITS, or point --images at the PNG/TIFF export.", 2)
        import numpy as np
        with fits.open(path) as hdul:
            data = None
            for hdu in hdul:
                if getattr(hdu, "data", None) is not None:
                    data = hdu.data
                    break
            if data is None:
                raise ValueError("no image data in any FITS HDU")
            arr = np.asarray(data).astype("float32")
            if arr.ndim > 2:  # a cube (C,H,W) or higher: take the first plane (matches prepare_data)
                arr = arr[tuple([0] * (arr.ndim - 2))]
            meta = {"mode": "FITS", "bit_depth": int(data.dtype.itemsize) * 8,
                    "is_16bit": data.dtype.itemsize >= 2, "channels": 1}
    else:
        try:
            from PIL import Image
        except Exception:
            die("Pillow is required for image inspection — `.venv/bin/pip install pillow`.", 2)
        import numpy as np
        with Image.open(path) as im:
            mode = im.mode
            arr = np.asarray(im).astype("float32")
            channels = 1 if arr.ndim == 2 else arr.shape[2]
            if arr.ndim == 3:  # collapse to luminance for hashing/stats; original channels recorded in meta
                arr = arr.mean(axis=2)
            # 16-bit modes in PIL: "I;16", "I;16B", "I", "I;16L"; also uint16 arrays.
            is16 = mode in ("I;16", "I;16B", "I;16L", "I") or arr.max() > 255
            bit = 16 if is16 else 8
            meta = {"mode": mode, "bit_depth": bit, "is_16bit": bool(is16), "channels": int(channels)}
    import numpy as np
    h, w = arr.shape[:2]
    meta.update({"width": int(w), "height": int(h),
                 "pmin": float(np.min(arr)), "pmax": float(np.max(arr))})
    return arr, meta


def to_uint8(arr):
    """Per-image percentile normalization to 0-255 (NOT dataset-global — global stats would leak across a
    split). Used ONLY for the perceptual hash / display; keeps faint streaks visible before downscaling."""
    import numpy as np
    a = arr.astype("float64")
    lo, hi = np.percentile(a, [1.0, 99.0])
    if hi <= lo:
        lo, hi = float(a.min()), float(a.max())
    if hi <= lo:
        return np.zeros(a.shape, dtype="uint8")
    return (np.clip((a - lo) / (hi - lo), 0.0, 1.0) * 255.0).astype("uint8")


def _dhash_bits(u8, hash_size):
    """Row-gradient dHash on a normalized uint8 image. Returns a hash_size*hash_size-bit int."""
    import numpy as np
    from PIL import Image
    small = np.asarray(Image.fromarray(u8).resize((hash_size + 1, hash_size), Image.BILINEAR), dtype="int16")
    diff = small[:, 1:] > small[:, :-1]
    val = 0
    for b in diff.flatten():
        val = (val << 1) | int(b)
    return val


def canonical_hash(arr, hash_size=16):
    """Augmentation-aware: hash all 8 dihedral orientations (rot90*4 x flip) of the normalized image and
    return the MIN — so an image and its rotated/flipped copy share one canonical hash (one cluster)."""
    import numpy as np
    u8 = to_uint8(arr)
    cands = []
    for k in range(4):
        r = np.rot90(u8, k)
        cands.append(_dhash_bits(r, hash_size))
        cands.append(_dhash_bits(np.fliplr(r), hash_size))
    return min(cands)


def parse_coco(path):
    """Return (by_image_stem: {stem: [ann...]}, categories: {id: name}, n_images_declared, file_name_by_id)."""
    with open(path) as f:
        coco = json.load(f)
    cats = {c["id"]: c.get("name", str(c["id"])) for c in coco.get("categories", [])}
    fn_by_id = {img["id"]: img.get("file_name", "") for img in coco.get("images", [])}
    id_to_stem = {i: stem_of(fn) for i, fn in fn_by_id.items()}
    by_stem = defaultdict(list)
    for ann in coco.get("annotations", []):
        st = id_to_stem.get(ann.get("image_id"))
        if st is not None:
            by_stem[st].append(ann)
    return by_stem, cats, len(coco.get("images", [])), fn_by_id


GROUP_CANDIDATE_PATTERNS = [
    (r"^(.*)_[^_]+$", "strip last _token (e.g. frame_0007_tile3 -> frame_0007)"),
    (r"^(.*?)_", "leading token before first _ (e.g. seqA_... -> seqA)"),
    (r"^(\D*\d+)", "leading run up to first number block"),
    (r"^(.*?)[._-]?\d+$", "strip trailing number (e.g. img_0042 -> img)"),
]


def group_candidates(stems):
    """Propose regexes usable directly as split-images --group-by. Report how many groups each yields.
    These are GUESSES from filenames — the true source key may live in FITS headers/a manifest."""
    out = []
    n = len(stems)
    for rx, desc in GROUP_CANDIDATE_PATTERNS:
        pat = re.compile(rx)
        groups, matched = {}, 0
        for s in stems:
            m = pat.match(s)
            if m and m.group(1):
                matched += 1
                groups[m.group(1)] = groups.get(m.group(1), 0) + 1
        if matched == 0:
            continue
        ng = len(groups)
        # a useful key groups many images into fewer groups AND matches (nearly) all filenames
        useful = matched >= 0.95 * n and 1 < ng < n
        example = None
        for s in stems[:50]:
            m = pat.match(s)
            if m and m.group(1):
                example = f"{s} -> {m.group(1)}"
                break
        out.append({"regex": rx, "description": desc, "n_groups": ng, "matched": matched,
                    "of_total": n, "looks_useful": bool(useful), "example": example})
    out.sort(key=lambda d: (not d["looks_useful"], d["n_groups"]))
    return out


def main():
    ap = argparse.ArgumentParser(description="Inspect an image dataset: bit-depth, near-dup leakage risk, group keys.")
    ap.add_argument("--images", required=True, help="directory of images (searched recursively)")
    ap.add_argument("--annotations", default=None, help="optional COCO annotations json")
    ap.add_argument("--sample", type=int, default=0,
                    help="cap images loaded for stats+dedup (0 = ALL, honest but slower). If >0, a seeded "
                         "random sample; near-dups outside the sample are NOT detected (reported as coverage).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--hash-size", type=int, default=16, help="dHash grid (higher = more discriminative)")
    ap.add_argument("--out", default="image_inspection.json")
    args = ap.parse_args()

    try:
        import numpy as np  # noqa: F401  (fail fast with a clear message if the base dep is missing)
    except Exception:
        die("numpy is required — use the project venv: .venv/bin/python", 2)

    if not os.path.isdir(args.images):
        die(f"--images is not a directory: {args.images}", 3)
    paths = list_images(args.images)
    if not paths:
        die(f"no images found under {args.images} (looked for {IMG_EXTS + FITS_EXTS})", 3)
    n_total = len(paths)

    import numpy as np
    coverage = "all"
    if args.sample and args.sample > 0 and args.sample < n_total:
        rng = np.random.RandomState(args.seed)
        idx = sorted(rng.choice(n_total, size=args.sample, replace=False).tolist())
        paths = [paths[i] for i in idx]
        coverage = f"sample {len(paths)}/{n_total}"

    # ---- load + hash ----
    modes, bitdepths, sizes = Counter(), Counter(), Counter()
    any_16bit = False
    hashes = {}          # stem -> canonical hash
    load_errors = []
    for p in paths:
        st = stem_of(p)
        try:
            arr, meta = load_gray_array(p)
        except SystemExit:
            raise
        except Exception as e:
            load_errors.append(f"{os.path.basename(p)}: {type(e).__name__}: {e}")
            continue
        modes[meta["mode"]] += 1
        bitdepths[meta["bit_depth"]] += 1
        sizes[f"{meta['width']}x{meta['height']}"] += 1
        any_16bit = any_16bit or meta["is_16bit"]
        try:
            hashes[st] = canonical_hash(arr, args.hash_size)
        except Exception as e:
            load_errors.append(f"{os.path.basename(p)}: hash failed: {e}")

    if not hashes:
        die("could not load/hash any image (see errors) — check Pillow/astropy and the files.\n  "
            + "\n  ".join(load_errors[:5]), 2)

    # ---- augmentation-aware dedup + reliability guard ----
    clusters_map = defaultdict(list)
    for st, h in hashes.items():
        clusters_map[h].append(st)
    dup_clusters = sorted([sorted(v) for v in clusters_map.values() if len(v) > 1], key=len, reverse=True)
    n_hashed = len(hashes)
    distinct = len(clusters_map)
    largest = max((len(v) for v in clusters_map.values()), default=0)
    # entropy of the hash distribution, normalized to [0,1]; near-0 => hash collapsed (sparse-sky footgun)
    counts = np.array([len(v) for v in clusters_map.values()], dtype="float64")
    probs = counts / counts.sum()
    ent = float(-(probs * np.log2(probs)).sum())
    max_ent = float(np.log2(distinct)) if distinct > 1 else 1.0
    norm_ent = ent / max_ent if max_ent > 0 else 0.0
    collapsed = (distinct <= max(2, n_hashed // 50)) or (largest > 0.5 * n_hashed) or (norm_ent < 0.3)
    dup_detector_reliable = not collapsed
    n_in_dups = sum(len(c) for c in dup_clusters)

    # ---- annotations ----
    ann_summary = None
    if args.annotations:
        if not os.path.exists(args.annotations):
            die(f"--annotations not found: {args.annotations}", 3)
        try:
            by_stem, cats, n_imgs_decl, _fn = parse_coco(args.annotations)
        except Exception as e:
            die(f"could not parse COCO annotations {args.annotations}: {e}", 3)
        boxes_per = [len(v) for v in by_stem.values()]
        cls_counter = Counter()
        wh = []
        for anns in by_stem.values():
            for a in anns:
                cid = a.get("category_id")
                cls_counter[cats.get(cid, str(cid))] += 1
                bb = a.get("bbox")
                if isinstance(bb, (list, tuple)) and len(bb) == 4:
                    wh.append((float(bb[2]), float(bb[3])))
        thin = sum(1 for w, h in wh if min(w, h) > 0 and max(w, h) / max(1e-9, min(w, h)) >= 5)
        ann_summary = {
            "n_images_declared": n_imgs_decl,
            "n_images_with_annotations": len(by_stem),
            "n_annotations": int(sum(boxes_per)),
            "class_distribution": dict(cls_counter),
            "boxes_per_image": {"min": int(min(boxes_per)) if boxes_per else 0,
                                "median": int(np.median(boxes_per)) if boxes_per else 0,
                                "max": int(max(boxes_per)) if boxes_per else 0},
            "thin_or_elongated_boxes": int(thin),
            "note_category_ids_are_coco_native": "scaffold-train remaps these to 0-based contiguous class ids",
        }

    gcands = group_candidates(sorted(hashes.keys()))

    warnings = []
    if any_16bit:
        warnings.append("16-BIT images present: a naive 8-bit loader (Ultralytics reads via cv2 /255) will "
                        "SILENTLY TRUNCATE these and can drop faint streaks below the noise floor. scaffold-train "
                        "must normalize per-image to 8-bit before YOLO sees them.")
    if not dup_detector_reliable:
        warnings.append(f"NEAR-DUP DETECTOR UNRELIABLE on this data (hash collapsed: {distinct} distinct hashes "
                        f"for {n_hashed} images, entropy {norm_ent:.2f}). Do NOT read the dup clusters as truth — "
                        "on sparse-sky imagery the hash cannot discriminate. Rely on a PROVENANCE group key "
                        "(filename tokens / FITS DATE-OBS/OBJECT/exposure) for split-images instead.")
    elif dup_clusters:
        warnings.append(f"{len(dup_clusters)} near-duplicate cluster(s) covering {n_in_dups} images (incl. "
                        "rot/flip copies). If these straddle a split you LEAK. split-images will fold them into "
                        "the group key when you pass --inspection this file.")
    if coverage != "all":
        warnings.append(f"Dedup ran on a {coverage} — near-dups OUTSIDE the sample were not detected. "
                        "Pass --sample 0 to hash every image.")
    if load_errors:
        warnings.append(f"{len(load_errors)} image(s) failed to load/hash (see load_errors).")

    result = {
        "images_dir": os.path.abspath(args.images),
        "n_images_total": n_total,
        "coverage": coverage,
        "n_images_inspected": len(paths),
        "n_images_hashed": n_hashed,
        "is_16bit": bool(any_16bit),
        "bit_depth_distribution": {str(k): v for k, v in bitdepths.items()},
        "mode_distribution": dict(modes),
        "size_distribution": dict(sizes),
        "dup_detector": {"hash_size": args.hash_size, "distinct_hashes": distinct,
                         "largest_cluster": largest, "normalized_entropy": round(norm_ent, 4),
                         "reliable": dup_detector_reliable},
        "dup_clusters": dup_clusters,          # <-- split-images consumes this (clusters of image stems)
        "n_images_in_dup_clusters": n_in_dups,
        "group_key_candidates": gcands,        # regexes usable as split-images --group-by
        "annotations": ann_summary,
        "load_errors": load_errors[:20],
        "warnings": warnings,
        "boundary": "Perceptual hashing finds NEAR-DUPLICATES by appearance, not semantic/provenance identity; "
                    "group_key_candidates are GUESSES from filenames, not confirmed source ids. This skill never "
                    "modifies images and does not decide the split — split-images does, honestly, from this sidecar.",
    }
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    write_report(result)
    print(f"Wrote {args.out} + image_inspection_report.md  "
          f"({n_total} images, 16-bit={any_16bit}, dup-detector reliable={dup_detector_reliable}, "
          f"{len(dup_clusters)} dup clusters)")
    if warnings:
        eprint("NOTES:")
        for w in warnings:
            eprint("  - " + w)


def write_report(r):
    dd = r["dup_detector"]
    ann = r["annotations"]
    top_cands = [c for c in r["group_key_candidates"] if c["looks_useful"]][:3]
    cand_lines = "\n".join(
        f"- `{c['regex']}` — {c['description']}: **{c['n_groups']} groups** from {c['matched']}/{c['of_total']} files "
        f"(e.g. {c['example']})" for c in top_cands) or "- (none looked useful — the source key is likely NOT in the filename)"
    dup_line = (f"{len(r['dup_clusters'])} cluster(s), {r['n_images_in_dup_clusters']} images"
                if dd["reliable"] else "⚠️ detector UNRELIABLE on this data — ignore the clusters, use provenance")
    md = f"""# Image inspection — {os.path.basename(r['images_dir'])}

## At a glance
```mermaid
flowchart LR
    D["{r['n_images_total']} images<br/>{'16-bit ⚠️' if r['is_16bit'] else '8-bit'}"] --> H["near-dup detector<br/>{dup_line}"]
    H --> G["group-key candidates<br/>{len(r['group_key_candidates'])} proposed"]
    G --> NEXT["→ split-images<br/>(--inspection this file)"]
```

- **Images:** {r['n_images_total']} total; inspected {r['n_images_inspected']} ({r['coverage']}). Sizes: {', '.join(f'{k}×{v}' for k, v in list(r['size_distribution'].items())[:4])}
- **Bit depth:** {r['bit_depth_distribution']} — {'**16-bit present ⚠️ do NOT let YOLO 8-bit-truncate**' if r['is_16bit'] else '8-bit'}
- **Near-dup detector:** {dd['distinct_hashes']} distinct hashes / {r['n_images_hashed']} hashed, entropy {dd['normalized_entropy']}, **reliable={dd['reliable']}**
- **Annotations:** {'none provided' if not ann else f"{ann['n_annotations']} boxes over {ann['n_images_with_annotations']} images, classes={ann['class_distribution']}, boxes/img med={ann['boxes_per_image']['median']}, thin/elongated={ann['thin_or_elongated_boxes']}"}

## Group-key candidates (confirm one for split-images)
These are GUESSES from filenames — the true source (exposure/field/night) may live in FITS headers, not the name.
{cand_lines}

## Leakage risk
{chr(10).join('- ' + w for w in r['warnings']) if r['warnings'] else '- No warnings.'}

## What this is / isn't
- ✅ Bit-depth + near-dup + group-key inspection to feed a leakage-safe split.
- ⚠️ Perceptual hash finds near-dups by APPEARANCE, not provenance; on sparse-sky imagery it can collapse
  (reported as `reliable:false`). Group-key candidates are guesses, not confirmed source ids.
- ⛔ Does NOT modify images, decide the split, or train anything.

## Next
→ `split-images --images {os.path.basename(r['images_dir'])} --inspection image_inspection.json --group-by <chosen regex|coco-field|none>`
"""
    with open("image_inspection_report.md", "w") as f:
        f.write(md)


if __name__ == "__main__":
    main()
