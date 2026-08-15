#!/usr/bin/env python3
"""evaluate-detection: honest offline detection metrics (mAP / per-class AP) from a predictions file + COCO
ground truth.

Honesty is the whole point. Offline mAP is NOT the leaderboard and NOT a deployable operating point:
  - It PREFERS pycocotools when installed (the metric real COCO comps are scored by; maxDets=100), and labels
    the numpy fallback APPROXIMATE.
  - The numpy fallback accumulates detections GLOBALLY per class across the eval set (not per-image-then-average,
    a common wrong shortcut) and states its AP-integration method.
  - It reads split provenance (--split) and STAMPS the result: a per-image / leaky split -> "mAP likely inflated";
    an unknown split -> "cannot rule out evaluating on training data".
  - It reports boxes/image and min confidence, and states that COCO scores only the top-100 boxes/image (hiding
    false-positive load) and that reported thresholds are often absurdly low.

Predictions schema (from scaffold-train's predict.py): CSV with columns
  image_id, class_id, score, x, y, w, h   (image_id = file stem; class_id = 0-based YOLO; x,y,w,h = TOP-LEFT px).
Ground-truth classes are aligned to the same 0-based space via class_map.json (or derived deterministically).

Emits detection_metrics.json + a Mermaid-led report. Exit codes: 0 ok · 2 dep/IO · 3 bad input.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical across scripts).
"""
import argparse
import csv
import json
import os
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


def stem_of(path):
    """Canonical image_id used across the whole CV pipeline: the file basename WITHOUT extension."""
    return os.path.splitext(os.path.basename(str(path)))[0]


def load_predictions(path):
    """Return list of dicts {image_id, class_id, score, box=[x,y,w,h] top-left pixel}."""
    if not os.path.exists(path):
        die(f"--predictions not found: {path}", 3)
    rows = []
    with open(path) as f:
        rd = csv.DictReader(f)
        need = {"image_id", "class_id", "score", "x", "y", "w", "h"}
        if not need.issubset(set(rd.fieldnames or [])):
            die(f"predictions file must have columns {sorted(need)} (got {rd.fieldnames}). "
                "Use scaffold-train's predict.py to produce it.", 3)
        for r in rd:
            try:
                rows.append({"image_id": str(r["image_id"]), "class_id": int(float(r["class_id"])),
                             "score": float(r["score"]),
                             "box": [float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"])]})
            except (ValueError, KeyError) as e:
                die(f"bad prediction row {r}: {e}", 3)
    return rows


def build_class_map(coco, class_map_path):
    """coco category_id -> 0-based yolo id, matching scaffold-train's rule. Prefer the shipped class_map.json."""
    if class_map_path and os.path.exists(class_map_path):
        cm = json.load(open(class_map_path))
        return {int(k): int(v) for k, v in cm["coco_id_to_yolo"].items()}, cm.get("names_ordered")
    cats = coco.get("categories", [])
    ids = sorted({c["id"] for c in cats})
    name_by_id = {c["id"]: c.get("name", str(c["id"])) for c in cats}
    coco_to_yolo = {cid: i for i, cid in enumerate(ids)}
    names = [name_by_id[cid] for cid in ids]
    return coco_to_yolo, names


def load_gt(coco, coco_to_yolo, eval_stems):
    """GT boxes by (stem, yolo_class). Also stem<->coco image id maps for the pycocotools path."""
    stem_by_cocoid = {img["id"]: stem_of(img.get("file_name", str(img["id"]))) for img in coco["images"]}
    gt = defaultdict(list)
    n = 0
    for a in coco.get("annotations", []):
        st = stem_by_cocoid.get(a["image_id"])
        if st is None or (eval_stems is not None and st not in eval_stems):
            continue
        cid = a.get("category_id")
        if cid not in coco_to_yolo:
            continue
        bb = a.get("bbox")
        if not (isinstance(bb, (list, tuple)) and len(bb) == 4):
            continue
        gt[(st, coco_to_yolo[cid])].append([float(v) for v in bb])
        n += 1
    return gt, stem_by_cocoid, n


def iou_xywh(a, b):
    ax1, ay1, aw, ah = a; bx1, by1, bw, bh = b
    ax2, ay2, bx2, by2 = ax1 + aw, ay1 + ah, bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def ap_all_point(recall, precision):
    """COCO-style all-point AP: area under the precision envelope (monotone-decreasing)."""
    import numpy as np
    mrec = np.concatenate(([0.0], recall, [1.0]))
    mpre = np.concatenate(([0.0], precision, [0.0]))
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def ap_at_iou(preds, gt, classes, iou_thr):
    """Global (not per-image-averaged) per-class AP at one IoU threshold. Returns {yolo_class: AP}."""
    import numpy as np
    out = {}
    for c in classes:
        cls_preds = sorted([p for p in preds if p["class_id"] == c], key=lambda p: -p["score"])
        gt_c = {k: v for k, v in gt.items() if k[1] == c}
        n_gt = sum(len(v) for v in gt_c.values())
        matched = {k: [False] * len(v) for k, v in gt_c.items()}
        if n_gt == 0:
            continue  # class absent from GT — excluded from mAP (COCO convention)
        tp = np.zeros(len(cls_preds)); fp = np.zeros(len(cls_preds))
        for i, p in enumerate(cls_preds):
            key = (p["image_id"], c)
            boxes = gt_c.get(key, [])
            best_iou, best_j = 0.0, -1
            for j, gb in enumerate(boxes):
                iou = iou_xywh(p["box"], gb)
                if iou > best_iou:
                    best_iou, best_j = iou, j
            if best_j >= 0 and best_iou >= iou_thr and not matched[key][best_j]:
                tp[i] = 1; matched[key][best_j] = True
            else:
                fp[i] = 1
        tpc, fpc = np.cumsum(tp), np.cumsum(fp)
        recall = tpc / n_gt
        precision = tpc / np.maximum(tpc + fpc, 1e-9)
        out[c] = ap_all_point(recall, precision)
    return out


def run_pycocotools(annotations_path, preds, coco_to_yolo, stem_by_cocoid, eval_stems):
    """Preferred path: score with the same tool real COCO comps use (maxDets=100). Returns dict or None."""
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except Exception:
        return None
    import contextlib, io
    yolo_to_coco = {v: k for k, v in coco_to_yolo.items()}
    cocoid_by_stem = {v: k for k, v in stem_by_cocoid.items()}
    dets = []
    for p in preds:
        img_id = cocoid_by_stem.get(p["image_id"])
        cat = yolo_to_coco.get(p["class_id"])
        if img_id is None or cat is None:
            continue
        dets.append({"image_id": img_id, "category_id": cat, "bbox": p["box"], "score": p["score"]})
    if not dets:
        return {"unavailable": "no predictions mapped to COCO image/category ids (stem/class mismatch)"}
    with contextlib.redirect_stdout(io.StringIO()):
        gt = COCO(annotations_path)
        dt = gt.loadRes(dets)
        ev = COCOeval(gt, dt, "bbox")
        if eval_stems is not None:
            ev.params.imgIds = [i for i, st in stem_by_cocoid.items() if st in eval_stems]
        ev.evaluate(); ev.accumulate(); ev.summarize()
    return {"mAP_0.50:0.95": round(float(ev.stats[0]), 4), "mAP_0.50": round(float(ev.stats[1]), 4),
            "mAP_0.75": round(float(ev.stats[2]), 4), "maxDets": 100}


def read_eval_stems(splits_dir, fold):
    if not splits_dir:
        return None, "UNKNOWN", None
    ss = os.path.join(splits_dir, "split_summary.json")
    prov = "UNKNOWN"
    if os.path.exists(ss):
        prov = json.load(open(ss)).get("split_provenance", "UNKNOWN")
    for cand in (os.path.join(splits_dir, "val_ids.txt"), os.path.join(splits_dir, f"fold_{fold}", "val_ids.txt")):
        if os.path.exists(cand):
            with open(cand) as f:
                return {ln.strip() for ln in f if ln.strip()}, prov, cand
    die(f"--split given but no val_ids.txt in {splits_dir} (or fold_{fold}/).", 3)


def main():
    ap = argparse.ArgumentParser(description="Honest offline detection metrics (mAP / AP) vs COCO ground truth.")
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--annotations", required=True, help="COCO ground-truth json")
    ap.add_argument("--class-map", default=None, help="class_map.json from scaffold-train (aligns GT classes)")
    ap.add_argument("--iou", type=float, default=0.5, help="IoU threshold for the numpy AP")
    ap.add_argument("--coco", action="store_true", help="also average AP over IoU 0.50:0.05:0.95 (numpy path)")
    ap.add_argument("--no-pycocotools", action="store_true", help="force the numpy fallback even if installed")
    ap.add_argument("--split", default=None, help="image_splits/ — restrict eval to its val set + record provenance")
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--out", default="detection_metrics.json")
    args = ap.parse_args()

    try:
        import numpy as np  # noqa: F401
    except Exception:
        die("numpy required — use the project venv: .venv/bin/python", 2)
    if not os.path.exists(args.annotations):
        die(f"--annotations not found: {args.annotations}", 3)
    coco = json.load(open(args.annotations))
    preds = load_predictions(args.predictions)
    coco_to_yolo, names = build_class_map(coco, args.class_map)
    eval_stems, provenance, val_path = read_eval_stems(args.split, args.fold)
    if eval_stems is not None:
        preds = [p for p in preds if p["image_id"] in eval_stems]
    gt, stem_by_cocoid, n_gt = load_gt(coco, coco_to_yolo, eval_stems)
    if n_gt == 0:
        die("no ground-truth boxes to evaluate against (check --split val set and class map).", 3)

    classes = sorted({k[1] for k in gt})
    import numpy as np
    # numpy AP (always available)
    per_class = ap_at_iou(preds, gt, classes, args.iou)
    m_ap = float(np.mean(list(per_class.values()))) if per_class else 0.0
    coco_mean = None
    if args.coco:
        thrs = [round(0.5 + 0.05 * i, 2) for i in range(10)]
        aps = []
        for t in thrs:
            pc = ap_at_iou(preds, gt, classes, t)
            if pc:
                aps.append(float(np.mean(list(pc.values()))))
        coco_mean = round(float(np.mean(aps)), 4) if aps else None

    pyco = None if args.no_pycocotools else run_pycocotools(
        args.annotations, preds, coco_to_yolo, stem_by_cocoid, eval_stems)
    used = "pycocotools" if (pyco and "unavailable" not in pyco) else "numpy(approximate)"

    # honesty signals
    boxes_per_img = defaultdict(int)
    for p in preds:
        boxes_per_img[p["image_id"]] += 1
    max_bpi = max(boxes_per_img.values(), default=0)
    min_conf = min((p["score"] for p in preds), default=None)

    caveats = [
        "Offline mAP is NOT the competition leaderboard and NOT a deployable operating point.",
        "COCO mAP scores only the top-100 boxes per image, so extra low-confidence boxes are unpenalized — mAP "
        "hides false-positive load that matters in deployment.",
        "mAP integrates over all confidence thresholds; it does NOT give you a threshold to deploy at.",
    ]
    if max_bpi > 100:
        caveats.append(f"predictions have up to {max_bpi} boxes/image (>100): COCO ignores all but the top 100, "
                       "so this mAP hides your false-positive load.")
    if min_conf is not None and min_conf < 0.05:
        caveats.append(f"min prediction confidence is {min_conf:.4f} (<0.05): a leaderboard mAP over near-zero "
                       "confidences does not reflect a usable threshold.")
    if provenance == "UNKNOWN":
        caveats.append("SPLIT PROVENANCE UNKNOWN (no --split given): cannot rule out evaluating on images the "
                       "model trained on — this number may be meaningless.")
    elif is_leaky_provenance(provenance):
        caveats.append("SPLIT WAS PER-IMAGE / ACKED LEAKY: this mAP is very likely INFLATED — near-duplicate "
                       "images were in both train and val.")
    if used.startswith("numpy"):
        caveats.append("Scored with the numpy fallback (APPROXIMATE): no iscrowd/area-range/maxDets handling — "
                       "install pycocotools for the metric real COCO comps use.")

    result = {
        "metric_definition": {"numpy_AP_iou": args.iou, "ap_integration": "all-point (COCO-style)",
                              "coco_0.50:0.95": args.coco},
        "scored_with": used,
        "mAP_numpy": round(m_ap, 4),
        "mAP_numpy_0.50:0.95": coco_mean,
        "per_class_AP_numpy": {(names[c] if names and c < len(names) else str(c)): round(v, 4)
                               for c, v in per_class.items()},
        "pycocotools": pyco,
        "n_predictions": len(preds),
        "n_gt_boxes": n_gt,
        "n_eval_images": len(eval_stems) if eval_stems is not None else len({p["image_id"] for p in preds}),
        "max_boxes_per_image": max_bpi,
        "min_confidence": min_conf,
        "split_provenance": provenance,
        "offline_only": True,
        "matches_leaderboard": False,
        "is_deployable_operating_point": False,
        "threshold_free": True,
        "caveats": caveats,
    }
    json.dump(result, open(args.out, "w"), indent=2)
    headline = pyco.get("mAP_0.50") if (pyco and "unavailable" not in pyco) else round(m_ap, 4)
    write_report(result, headline)
    print(f"Wrote {args.out} + detection_report.md — mAP@0.5≈{headline} ({used}, provenance={provenance})")
    if provenance == "UNKNOWN" or is_leaky_provenance(provenance):
        eprint("  WARNING: this mAP is untrustworthy — see caveats (split provenance).")


def write_report(r, headline):
    prov = r["split_provenance"]
    prov_badge = ("🔴 PER-IMAGE (leaky) — mAP inflated" if is_leaky_provenance(prov)
                  else "❓ UNKNOWN — may be on training data" if prov == "UNKNOWN" else "🟢 " + str(prov))
    pc = "\n".join(f"- {k}: {v}" for k, v in r["per_class_AP_numpy"].items()) or "- (none)"
    md = f"""# Detection evaluation

## At a glance
```mermaid
flowchart LR
    P["{r['n_predictions']} preds"] --> M["mAP@0.5 ≈ {headline}<br/>({r['scored_with']})"]
    M --> PROV["split: {prov_badge}"]
    PROV --> HON["offline_only ✓<br/>matches_leaderboard ✗<br/>deployable ✗"]
```

- **mAP@0.5:** numpy≈{r['mAP_numpy']}{f", pycocotools={r['pycocotools'].get('mAP_0.50')}" if r['pycocotools'] and 'unavailable' not in r['pycocotools'] else ''}  ·  **scored with {r['scored_with']}**
- **COCO 0.50:0.95:** {r['mAP_numpy_0.50:0.95'] if r['mAP_numpy_0.50:0.95'] is not None else (r['pycocotools'].get('mAP_0.50:0.95') if r['pycocotools'] and 'unavailable' not in r['pycocotools'] else 'not computed')}
- **Eval set:** {r['n_eval_images']} images, {r['n_gt_boxes']} GT boxes; up to {r['max_boxes_per_image']} preds/image; min conf {r['min_confidence']}
- **Split provenance:** {prov_badge}

## Per-class AP@{r['metric_definition']['numpy_AP_iou']} (numpy)
{pc}

## Honesty — read before trusting the number
{chr(10).join('- ' + c for c in r['caveats'])}

## Next
→ `make-detection-submission` (format for the leaderboard — a good mAP here still needs the exact comp metric).
"""
    with open("detection_report.md", "w") as f:
        f.write(md)


if __name__ == "__main__":
    main()
