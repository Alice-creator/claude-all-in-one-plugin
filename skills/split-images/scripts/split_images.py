#!/usr/bin/env python3
"""split-images: leakage-safe train/val split for image data — the sacred leakage rule ported to CV.

The rule (grounded): every image derived from ONE source (tile of a frame, frame of an exposure/sequence)
must land in a SINGLE fold; a per-image random split leaks because near-identical images end up in both
train and val. This script keys the split on a SOURCE group and:
  - CONSUMES inspect-images' near-dup clusters (--inspection) and UNIONS each cluster into the group id, so a
    rotated/flipped/near-duplicate copy cannot straddle folds. This makes the post-check real, not tautological.
  - REFUSES a silent per-image split: no detectable group is NOT evidence of independence, so `--group-by none`
    requires an explicit, recorded `--allow-per-image-split` ack that propagates downstream (split_provenance),
    so evaluate-detection stamps the resulting mAP as likely-inflated.
  - Sanity-gates the group key: refuses a per-image COCO field (id/file_name), warns when n_groups ≈ n_images,
    and refuses a regex that fails to match some filenames (undefined grouping = silent leak).

Writes image_splits/ (fold id-lists or a single holdout) + split_summary.json. Works on image STEMS, never
loads pixels. Exit codes: 0 ok · 2 dep/IO · 3 bad input · 4 refused (would leak).

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical across scripts).
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def is_leaky_provenance(prov):
    """True if a split_summary provenance marks a leaky (per-image, acked) split — the single honesty stamp
    downstream skills must not silently drop if the provenance string is ever renamed."""
    return str(prov).startswith("per-image")


IMG_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".fits", ".fit", ".fts")


def stem_of(path):
    """Canonical image_id used across the whole CV pipeline: the file basename WITHOUT extension."""
    return os.path.splitext(os.path.basename(str(path)))[0]


def list_image_stems(images_dir):
    out = []
    for root, _dirs, files in os.walk(images_dir):
        base = os.path.basename(root)
        if base in ("labels", "smoke_throwaway"):
            continue
        for fn in files:
            if fn.lower().endswith(IMG_EXTS):
                out.append(stem_of(fn))
    return sorted(set(out))


def coco_field_by_stem(coco, field):
    """Map image stem -> str(field value) from COCO images[]. Refuses per-image fields upstream."""
    out = {}
    for img in coco.get("images", []):
        st = stem_of(img.get("file_name", str(img.get("id"))))
        if field not in img:
            die(f"COCO images[] has no field '{field}' (present keys e.g. {sorted(list(img.keys()))[:8]}).", 3)
        out[st] = str(img[field])
    return out


class UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def assign_groups(stems, group_by, coco, dup_clusters):
    """Return {stem: group_id}. group_by is 'none', 'coco:<field>', or a regex (bare). Near-dup clusters
    from inspect-images are UNIONED into whatever the base key produces, so a cluster can't straddle folds."""
    base = {}
    if group_by == "none":
        base = {s: s for s in stems}                      # each its own group (per-image) — gated by caller
    elif group_by.startswith("coco:"):
        field = group_by[len("coco:"):]
        if field in ("id", "file_name"):
            die(f"--group-by coco:{field} is a PER-IMAGE key (every image is its own group) — that is exactly "
                "the leaky split this skill prevents. Choose a real source field (exposure/sequence/field id) "
                "or, if the images are genuinely independent, --group-by none --allow-per-image-split.", 4)
        if coco is None:
            die("--group-by coco:<field> needs --annotations <coco.json>.", 3)
        m = coco_field_by_stem(coco, field)
        missing = [s for s in stems if s not in m]
        if missing:
            die(f"{len(missing)} image(s) have no COCO entry for the group field (e.g. {missing[:3]}). "
                "Every image must map to a group — fix the annotations or pick another key.", 3)
        base = {s: m[s] for s in stems}
    else:  # bare regex applied to the stem; capture group 1 is the group id
        try:
            pat = re.compile(group_by)
        except re.error as e:
            die(f"--group-by is not 'none', not 'coco:<field>', and not a valid regex: {e}", 3)
        if pat.groups < 1:
            die(f"--group-by regex '{group_by}' has no capture group — it must capture the group id as group 1, "
                r"e.g. '^(.*)_[^_]+$'. See inspect-images' group_key_candidates.", 3)
        unmatched = []
        for s in stems:
            mt = pat.match(s)
            if not mt or not mt.group(1):
                unmatched.append(s)
            else:
                base[s] = mt.group(1)
        if unmatched:
            die(f"regex --group-by '{group_by}' did not match {len(unmatched)} filename(s) "
                f"(e.g. {unmatched[:3]}). Refusing — an unmatched image would silently become its own group "
                "(per-image leak). Fix the regex to match ALL stems, or use --group-by none if truly ungrouped.", 4)

    uf = UnionFind(stems)
    stem_set = set(stems)
    # union same-base-group
    by_base = defaultdict(list)
    for s, g in base.items():
        by_base[g].append(s)
    for members in by_base.values():
        for other in members[1:]:
            uf.union(members[0], other)
    # union near-dup clusters (only stems we actually have)
    for cluster in dup_clusters or []:
        present = [s for s in cluster if s in stem_set]
        for other in present[1:]:
            uf.union(present[0], other)

    # base map is returned too: it lets main() measure the GENUINE, independent signal — how many near-dup
    # clusters spanned >1 base group, i.e. would have straddled folds under the raw key had we not folded them.
    return {s: uf.find(s) for s in stems}, base


def load_dup_clusters(inspection_path):
    if not inspection_path:
        return [], None
    if not os.path.exists(inspection_path):
        die(f"--inspection file not found: {inspection_path} (run inspect-images first, or omit it).", 3)
    with open(inspection_path) as f:
        insp = json.load(f)
    dd = insp.get("dup_detector", {})
    if not dd.get("reliable", True):
        # honest: don't fold in clusters we already flagged as garbage; say so
        return [], {"reliable": False}
    return insp.get("dup_clusters", []), {"reliable": True, "n_clusters": len(insp.get("dup_clusters", []))}


def main():
    ap = argparse.ArgumentParser(description="Leakage-safe grouped image split (GroupKFold / grouped holdout).")
    ap.add_argument("--images", help="image directory (stems become the id list)")
    ap.add_argument("--annotations", help="COCO json — source of ids when --images is omitted, and the source of "
                                          "coco:<field> group values. Pass both to list ids from --images and "
                                          "group by a COCO field.")
    ap.add_argument("--inspection", default=None,
                    help="image_inspection.json from inspect-images — its near-dup clusters are folded into groups")
    ap.add_argument("--group-by", required=True,
                    help="'none' (per-image, needs --allow-per-image-split) | 'coco:<field>' | a regex on the stem "
                         "with one capture group (as proposed by inspect-images)")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--k", type=int, help="number of GroupKFold folds")
    grp.add_argument("--val-frac", type=float, help="single grouped holdout: fraction of GROUPS held out")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--allow-per-image-split", action="store_true",
                    help="explicit, RECORDED ack that the images are independent (no shared exposure/field/"
                         "sequence). Required for --group-by none. Propagated downstream as a leakage flag.")
    ap.add_argument("--out", default="image_splits")
    args = ap.parse_args()

    try:
        from sklearn.model_selection import GroupKFold, GroupShuffleSplit
        import numpy as np
    except Exception:
        die("scikit-learn + numpy required — use the project venv: .venv/bin/python", 2)

    if args.k is None and args.val_frac is None:
        args.val_frac = 0.2  # default: a single grouped 80/20 holdout

    if not args.images and not args.annotations:
        die("need --images (a directory) or --annotations (a COCO json) to get the image list", 3)
    coco = None
    if args.annotations:
        if not os.path.exists(args.annotations):
            die(f"--annotations not found: {args.annotations}", 3)
        with open(args.annotations) as f:
            coco = json.load(f)
    if args.images:
        if not os.path.isdir(args.images):
            die(f"--images is not a directory: {args.images}", 3)
        stems = list_image_stems(args.images)
    else:
        stems = sorted({stem_of(img.get("file_name", str(img.get("id")))) for img in coco.get("images", [])})
    if not stems:
        die("no images found to split", 3)

    if args.group_by == "none" and not args.allow_per_image_split:
        die("--group-by none would put each image in its own group (a PER-IMAGE split). Absence of a filename "
            "group is NOT evidence the images are independent — a shared exposure/field/sequence may be invisible "
            "in the names (or live in FITS headers). If you have CONFIRMED the images are independent, re-run with "
            "--allow-per-image-split (recorded as a leakage flag). Otherwise give a real --group-by "
            "regex/coco:field (see inspect-images' group_key_candidates).", 4)

    dup_clusters, dup_meta = load_dup_clusters(args.inspection)
    groups_map, base_map = assign_groups(stems, args.group_by, coco, dup_clusters)

    uniq_groups = sorted(set(groups_map.values()))
    n_groups, n_images = len(uniq_groups), len(stems)

    warnings = []
    if dup_meta and dup_meta.get("reliable") is False:
        warnings.append("inspect-images flagged its near-dup detector as UNRELIABLE on this data, so no clusters "
                        "were folded in. The group key alone must capture provenance — verify it does.")
    per_image_like = n_groups >= 0.95 * n_images
    if per_image_like and args.group_by != "none":
        warnings.append(f"group key yields {n_groups} groups for {n_images} images (~1 per image) — it is "
                        "effectively a PER-IMAGE split and likely leaks. Pick a coarser source key.")

    stems_sorted = sorted(stems)
    X = np.zeros(len(stems_sorted))
    grp_ids = [groups_map[s] for s in stems_sorted]

    folds = []
    if args.k is not None:
        if args.k < 2:
            die("--k must be >= 2", 3)
        if n_groups < args.k:
            die(f"only {n_groups} groups but --k {args.k}: GroupKFold needs n_groups >= k. "
                "Use fewer folds or a finer (but still non-per-image) group key.", 3)
        gkf = GroupKFold(n_splits=args.k)
        for tr, va in gkf.split(X, groups=grp_ids):
            folds.append(([stems_sorted[i] for i in tr], [stems_sorted[i] for i in va]))
        strategy = f"GroupKFold(k={args.k})"
    else:
        if not (0.0 < args.val_frac < 1.0):
            die("--val-frac must be in (0,1)", 3)
        if n_groups < 2:
            die(f"only {n_groups} group(s) — cannot hold out any groups for validation. The group key is too "
                "coarse (everything is one source).", 3)
        gss = GroupShuffleSplit(n_splits=1, test_size=args.val_frac, random_state=args.seed)
        tr, va = next(gss.split(X, groups=grp_ids))
        folds.append(([stems_sorted[i] for i in tr], [stems_sorted[i] for i in va]))
        strategy = f"grouped holdout (val_frac={args.val_frac})"

    group_of = groups_map
    stem_set = set(stems_sorted)
    # GENUINE, independent signal: how many near-dup clusters spanned MORE THAN ONE base group under the raw
    # --group-by key. >0 means the group key ALONE would have leaked, and folding the clusters in is what
    # prevented it — this is the number that actually says something the folding didn't already guarantee.
    dup_spanned_base = 0
    for cluster in dup_clusters or []:
        present = [s for s in cluster if s in stem_set]
        if len({base_map.get(s) for s in present}) > 1:
            dup_spanned_base += 1

    # Regression GUARDS (0 by construction once GroupKFold runs on the folded key): they catch a bug in
    # UnionFind/GroupKFold, NOT unseen leakage — a near-dup the detector missed isn't in dup_clusters, so no
    # check here can see it. Honest framing: the folding is the protection; these confirm it held.
    dup_straddle = 0
    grp_straddle = 0
    for _tr, va in folds:
        va_set = set(va)
        va_groups = {group_of[s] for s in va}
        for s in stems_sorted:
            if s not in va_set and group_of[s] in va_groups:
                grp_straddle += 1
    for cluster in dup_clusters or []:
        present = [s for s in cluster if s in stem_set]
        for _tr, va in folds:
            va_set = set(va)
            in_va = [s for s in present if s in va_set]
            if in_va and len(in_va) != len(present):
                dup_straddle += 1
                break

    os.makedirs(args.out, exist_ok=True)
    per_fold = []
    for fi, (tr, va) in enumerate(folds):
        if len(folds) == 1:
            fdir = args.out
        else:
            fdir = os.path.join(args.out, f"fold_{fi}")
            os.makedirs(fdir, exist_ok=True)
        with open(os.path.join(fdir, "train_ids.txt"), "w") as f:
            f.write("\n".join(sorted(tr)) + "\n")
        with open(os.path.join(fdir, "val_ids.txt"), "w") as f:
            f.write("\n".join(sorted(va)) + "\n")
        per_fold.append({"fold": fi, "n_train": len(tr), "n_val": len(va),
                         "n_val_groups": len({group_of[s] for s in va})})

    provenance = ("per-image-ACKED-leaky" if args.group_by == "none"
                  else f"grouped:{args.group_by}")
    grp_sizes = defaultdict(int)
    for g in grp_ids:
        grp_sizes[g] += 1
    sizes = sorted(grp_sizes.values())
    summary = {
        "strategy": strategy,
        "group_by": args.group_by,
        "split_provenance": provenance,
        "leakage_ack": bool(args.group_by == "none" and args.allow_per_image_split),
        "n_images": n_images,
        "n_groups": n_groups,
        "group_size": {"min": sizes[0], "median": sizes[len(sizes) // 2], "max": sizes[-1]},
        "near_dup_clusters_folded_in": len(dup_clusters or []),
        "near_dup_clusters_that_spanned_base_groups": dup_spanned_base,
        "dup_detector_reliable": None if dup_meta is None else dup_meta.get("reliable"),
        "integrity": {"groups_straddling_folds": grp_straddle,           # regression guard (0 by construction)
                      "dup_clusters_straddling_folds": dup_straddle,      # regression guard (0 by construction)
                      "near_dup_clusters_that_spanned_base_groups": dup_spanned_base,
                      "note": "The two *_straddling_folds counts are regression GUARDS — 0 by construction once "
                              "GroupKFold runs on the folded key; they catch a code bug, not unseen leakage, and "
                              "prove nothing about whether the key is the true source. The genuine signal is "
                              "near_dup_clusters_that_spanned_base_groups: >0 means the --group-by key ALONE would "
                              "have leaked and folding the near-dups in is what saved the split. A near-dup the "
                              "detector MISSED is in no check here — that risk is on the group key you chose."},
        "per_fold": per_fold,
        "warnings": warnings,
        "boundary": "A leakage-safe split by a chosen key. It cannot verify the key IS the true source of "
                    "correlation — that judgment is yours (see inspect-images).",
    }
    with open(os.path.join(args.out, "split_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    write_report(args.out, summary)
    if grp_straddle or dup_straddle:
        die(f"POST-CHECK FAILED: {grp_straddle} group-straddles, {dup_straddle} dup-cluster-straddles — the split "
            "leaks. This is a bug; do not use these splits.", 2)
    print(f"Wrote {args.out}/ ({strategy}, {n_groups} groups over {n_images} images, "
          f"{len(dup_clusters or [])} dup-clusters folded in) + split_summary.json")
    if is_leaky_provenance(provenance):
        eprint("  WARNING: PER-IMAGE split (acked). Every downstream metric will be stamped 'likely inflated'.")
    for w in warnings:
        eprint("  - " + w)


def write_report(out_dir, s):
    integ = s["integrity"]
    prov = s["split_provenance"]
    leak_badge = "🔴 PER-IMAGE (acked leaky)" if is_leaky_provenance(prov) else "🟢 grouped"
    md = f"""# Image split — {s['strategy']}

## At a glance
```mermaid
flowchart LR
    IMG["{s['n_images']} images"] --> G["group by<br/>{s['group_by']}<br/>{s['n_groups']} groups"]
    G --> DUP["+ {s['near_dup_clusters_folded_in']} near-dup<br/>clusters folded in"]
    DUP --> SPL["{leak_badge}"]
    SPL --> CHK["{integ['near_dup_clusters_that_spanned_base_groups']} near-dups the<br/>key alone would have leaked"]
```

- **Provenance:** `{prov}` · leakage_ack={s['leakage_ack']}
- **Groups:** {s['n_groups']} over {s['n_images']} images (size min/med/max = {s['group_size']['min']}/{s['group_size']['median']}/{s['group_size']['max']})
- **Genuine leak signal:** {integ['near_dup_clusters_that_spanned_base_groups']} near-dup cluster(s) spanned >1 base group under `{s['group_by']}` (folding them in prevented that leak). Regression guards: groups-straddling={integ['groups_straddling_folds']}, dup-straddling={integ['dup_clusters_straddling_folds']} (both 0 by construction).
- **Folds:** {', '.join(f"#{f['fold']}: {f['n_train']}tr/{f['n_val']}va" for f in s['per_fold'])}

## Honesty
- The `*_straddling_folds` counts are **regression guards**, 0 by construction once GroupKFold runs — they catch a
  code bug, **not** unseen leakage, and prove nothing about whether `{s['group_by']}` is the true source. The one
  number that says something independent is **near_dup_clusters_that_spanned_base_groups** ({integ['near_dup_clusters_that_spanned_base_groups']}):
  >0 means the key alone would have leaked. A near-dup the detector MISSED is in no check here — that risk rides
  on the group key you chose.
{chr(10).join('- ⚠️ ' + w for w in s['warnings']) if s['warnings'] else '- No warnings.'}
{"- 🔴 This is a PER-IMAGE split you acked as independent. evaluate-detection will stamp its mAP 'likely inflated'." if is_leaky_provenance(prov) else ''}

## Next
→ `scaffold-train --splits {out_dir}/ ...` (generates a YOLO training bundle; normalizes 16-bit; smoke-trains on CPU).
"""
    with open(os.path.join(out_dir, "split_report.md"), "w") as f:
        f.write(md)


if __name__ == "__main__":
    main()
