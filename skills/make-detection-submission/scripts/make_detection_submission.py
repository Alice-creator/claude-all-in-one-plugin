#!/usr/bin/env python3
"""make-detection-submission: format a predictions file into a competition submission and VALIDATE the format
against the competition's own sample_submission.

It validates FORMAT, not correctness — a perfectly-formatted submission of garbage boxes scores ~0. It never
presents a format-valid file as a good result. It also refuses to guess the one thing only the competition can
tell you: the per-box field ORDER and units. The default box order is `conf x y w h` (top-left pixels), stated
loudly as MUST-CONFIRM against the comp's sample/rules — pass --box-order to change it.

Two formats:
  - streak  : per-image `prediction_string` = "conf x y w h conf x y w h ..." aligned to sample_submission
              (EVERY sample image present; empty string if the detector found nothing). This is the ESA
              debris-streak style.
  - coco    : a COCO-detection results.json (list of {image_id, category_id, bbox, score}).

Predictions schema (scaffold-train's predict.py): image_id(stem), class_id(0-based), score, x, y, w, h(top-left px).
Emits the submission + submission_manifest.json. Exit codes: 0 ok · 2 dep/IO · 3 bad input.

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


def stem_of(path):
    """Canonical image_id used across the whole CV pipeline: the file basename WITHOUT extension."""
    return os.path.splitext(os.path.basename(str(path)))[0]


def load_predictions(path):
    if not os.path.exists(path):
        die(f"--predictions not found: {path}", 3)
    by_stem = defaultdict(list)
    n = 0
    with open(path) as f:
        rd = csv.DictReader(f)
        need = {"image_id", "class_id", "score", "x", "y", "w", "h"}
        if not need.issubset(set(rd.fieldnames or [])):
            die(f"predictions file must have columns {sorted(need)} (got {rd.fieldnames}).", 3)
        for r in rd:
            try:
                by_stem[stem_of(r["image_id"])].append(
                    {"class_id": int(float(r["class_id"])), "score": float(r["score"]),
                     "x": float(r["x"]), "y": float(r["y"]), "w": float(r["w"]), "h": float(r["h"])})
                n += 1
            except (ValueError, KeyError) as e:
                die(f"bad prediction row {r}: {e}", 3)
    return by_stem, n


def detect_columns(header):
    """Return (id_col, pred_col) from a sample_submission header. pred_col = a name containing 'predict';
    id_col = the other (or the first column)."""
    if not header:
        die("sample_submission has no header row", 3)
    pred_col = next((c for c in header if "predict" in c.lower()), None)
    if pred_col is None and len(header) >= 2:
        pred_col = header[1]
    id_col = next((c for c in header if c != pred_col), header[0])
    return id_col, pred_col


def box_tokens(det, order):
    vals = {"conf": det["score"], "x": det["x"], "y": det["y"], "w": det["w"], "h": det["h"]}
    return [f"{vals[k]:.6f}" if k == "conf" else f"{vals[k]:.2f}" for k in order]


def main():
    ap = argparse.ArgumentParser(description="Format predictions into a competition submission + validate format.")
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--sample-submission", default=None, help="the comp's sample_submission (required for streak)")
    ap.add_argument("--format", choices=["streak", "coco"], default="streak")
    ap.add_argument("--box-order", default="conf,x,y,w,h",
                    help="per-box field order — MUST match the comp's rules (default conf,x,y,w,h, top-left px)")
    ap.add_argument("--conf-threshold", type=float, default=0.0, help="drop boxes below this score")
    ap.add_argument("--max-per-image", type=int, default=0, help="keep only the top-N boxes/image (0 = all)")
    ap.add_argument("--class-map", default=None, help="class_map.json (coco format: decode 0-based -> COCO cat)")
    ap.add_argument("--out", default="submission.csv")
    args = ap.parse_args()

    order = [t.strip() for t in args.box_order.split(",") if t.strip()]
    if set(order) != {"conf", "x", "y", "w", "h"}:
        die(f"--box-order must be a permutation of conf,x,y,w,h (got {order})", 3)

    by_stem, n_preds = load_predictions(args.predictions)

    def prep(dets):
        d = [x for x in dets if x["score"] >= args.conf_threshold]
        d.sort(key=lambda x: -x["score"])
        return d[:args.max_per_image] if args.max_per_image else d

    if args.format == "coco":
        return write_coco(args, by_stem, prep, order, n_preds)

    if not args.sample_submission or not os.path.exists(args.sample_submission):
        die("streak format needs --sample-submission (the comp's file defines the id set + columns).", 3)
    with open(args.sample_submission) as f:
        rd = csv.reader(f)
        header = next(rd, None)
        raw_rows = [row for row in rd if row]
    id_col, pred_col = detect_columns(header)
    id_idx = header.index(id_col)  # honor the DETECTED id column, don't assume it's column 0
    sample_ids = [row[id_idx] for row in raw_rows if len(row) > id_idx]

    n_with, n_empty, extra = 0, 0, 0
    used_stems = set()
    rows = []
    for sid in sample_ids:
        st = stem_of(sid)
        dets = prep(by_stem.get(st, []))
        used_stems.add(st)
        if dets:
            n_with += 1
            toks = []
            for d in dets:
                toks.extend(box_tokens(d, order))
            rows.append([sid, " ".join(toks)])
        else:
            n_empty += 1
            rows.append([sid, ""])
    extra = len({s for s in by_stem if s not in used_stems})

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([id_col, pred_col])
        w.writerows(rows)

    manifest = {
        "format": "streak",
        "box_order": order,
        "box_order_confirmed": False,
        "columns": [id_col, pred_col],
        "n_sample_images": len(sample_ids),
        "n_with_detections": n_with,
        "n_empty": n_empty,
        "n_predicted_images_not_in_sample": extra,
        "all_sample_images_written": len(rows) == len(sample_ids),
        "conf_threshold": args.conf_threshold,
        "validates": "format_only",
        "scores_correctness": "not_validated",
        "boundary": "Validates the submission FORMAT only. A well-formatted file of wrong boxes scores ~0. The "
                    "per-box field order/units are assumed (conf,x,y,w,h, top-left px) and MUST be confirmed "
                    "against the competition's sample/rules.",
    }
    json.dump(manifest, open("submission_manifest.json", "w"), indent=2)
    write_report(manifest, args.out)

    print(f"Wrote {args.out} ({len(sample_ids)} images: {n_with} with detections, {n_empty} empty) + "
          "submission_manifest.json")
    eprint("  ⚠️ CONFIRM the per-box order/units against the comp's sample/rules — assumed "
           f"'{','.join(order)}', top-left pixels.")
    if extra:
        eprint(f"  ⚠️ {extra} predicted image(s) are NOT in sample_submission — they were dropped.")
    if n_with == 0:
        eprint("  ⚠️ 0/{} images have any detection — this submission will score ~0.".format(len(sample_ids)))
    elif n_with < 0.05 * len(sample_ids):
        eprint(f"  ⚠️ only {n_with}/{len(sample_ids)} images have detections — suspiciously sparse; will score low.")


def write_coco(args, by_stem, prep, order, n_preds):
    yolo_to_coco = None
    if args.class_map and os.path.exists(args.class_map):
        cm = json.load(open(args.class_map))
        yolo_to_coco = {int(v): int(k) for k, v in cm["coco_id_to_yolo"].items()}
    dets = []
    n_with = 0
    for st, ds in by_stem.items():
        kept = prep(ds)
        if kept:
            n_with += 1
        for d in kept:
            cat = yolo_to_coco.get(d["class_id"], d["class_id"]) if yolo_to_coco else d["class_id"]
            dets.append({"image_id": st, "category_id": cat,
                         "bbox": [round(d["x"], 2), round(d["y"], 2), round(d["w"], 2), round(d["h"], 2)],
                         "score": round(d["score"], 6)})
    out = args.out if args.out.endswith(".json") else "submission_coco.json"
    json.dump(dets, open(out, "w"))
    manifest = {"format": "coco", "n_detections": len(dets), "n_images_with_detections": n_with,
                "image_id_space": "file stem (map to the comp's id space if it expects integer COCO ids)",
                "category_id_space": "COCO native (via class_map)" if yolo_to_coco else "0-based YOLO (no class_map given)",
                "validates": "format_only", "scores_correctness": "not_validated",
                "boundary": "COCO-detection results.json. image_id is the file stem; if the comp expects integer "
                            "COCO image ids, remap. Validates shape only, not correctness."}
    json.dump(manifest, open("submission_manifest.json", "w"), indent=2)
    write_report(manifest, out)
    print(f"Wrote {out} ({len(dets)} detections over {n_with} images) + submission_manifest.json")
    if not yolo_to_coco:
        eprint("  ⚠️ no --class-map: category_id is left as 0-based YOLO. Pass class_map.json to decode to COCO ids.")
    if len(dets) == 0:
        eprint("  ⚠️ 0 detections — this submission will score ~0.")


def write_report(m, out_path):
    fmt = m["format"]
    if fmt == "streak":
        detail = (f"- **Images:** {m['n_sample_images']} (sample) · {m['n_with_detections']} with detections · "
                  f"{m['n_empty']} empty\n- **Columns:** {m['columns']} · box order `{','.join(m['box_order'])}` "
                  f"(**confirmed={m['box_order_confirmed']}**)\n- **all sample images written:** "
                  f"{m['all_sample_images_written']} · predicted-but-not-in-sample (dropped): "
                  f"{m['n_predicted_images_not_in_sample']}")
        glance = f'S["{m["n_sample_images"]} images<br/>{m["n_with_detections"]} w/ boxes"]'
    else:
        detail = (f"- **Detections:** {m['n_detections']} over {m['n_images_with_detections']} images\n"
                  f"- **category ids:** {m['category_id_space']}")
        glance = f'S["{m["n_detections"]} detections"]'
    md = f"""# Detection submission — {fmt}

## At a glance
```mermaid
flowchart LR
    P["preds.csv"] --> {glance}
    S --> V["format valid ✓<br/>correctness: NOT validated"]
    V --> SUB["submit (human)"]
```

{detail}

## What this is / isn't
- ✅ A submission in the competition's format, validated for shape (columns/ids/box tokens).
- ⛔ **Validates FORMAT, not correctness.** A well-formatted file of wrong boxes scores ~0. This tool cannot tell
  you your boxes are good — only `evaluate-detection` (offline) and the leaderboard (online) can.
- ⚠️ The per-box field **order/units are ASSUMED** ({','.join(m['box_order']) if fmt == 'streak' else 'n/a'}) and
  must be confirmed against the competition's own sample/rules.

## Next
→ Confirm the box order/units, then submit (a human decision). Remember: this pipeline handles the DETECTION
sub-task only — a competition with a poisoned-model / unlearning sub-task is not complete with a detection
submission alone.
"""
    with open("submission_report.md", "w") as f:
        f.write(md)


if __name__ == "__main__":
    main()
