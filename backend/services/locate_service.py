import cv2
import numpy as np
import os

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "images")
_akaze = cv2.AKAZE_create()
_bf = cv2.BFMatcher(cv2.NORM_HAMMING)


def save_registration_images(product_id: str, image_bytes_list: list[bytes]):
    d = os.path.join(IMAGES_DIR, product_id)
    os.makedirs(d, exist_ok=True)
    for i, b in enumerate(image_bytes_list):
        with open(os.path.join(d, f"{i}.jpg"), "wb") as f:
            f.write(b)


def locate(frame_bytes: bytes, product_id: str) -> dict | None:
    d = os.path.join(IMAGES_DIR, product_id)
    if not os.path.isdir(d):
        return None
    template_paths = sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    if not template_paths:
        return None

    arr = np.frombuffer(frame_bytes, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    fh, fw = gray.shape

    kp_f, des_f = _akaze.detectAndCompute(gray, None)
    if des_f is None or len(kp_f) < 10:
        return None

    all_pts: list[tuple] = []

    for path in template_paths:
        tmpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            continue
        kp_t, des_t = _akaze.detectAndCompute(tmpl, None)
        if des_t is None:
            continue
        # Lowe's ratio test — robust across scale/rotation changes
        pairs = _bf.knnMatch(des_t, des_f, k=2)
        for pair in pairs:
            if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
                all_pts.append(kp_f[pair[0].trainIdx].pt)

    if len(all_pts) < 6:
        return None

    pts = np.array(all_pts)

    # Remove outliers using median absolute deviation
    median = np.median(pts, axis=0)
    mad = np.median(np.abs(pts - median), axis=0) + 1e-6
    mask = np.all(np.abs(pts - median) < 2.5 * mad, axis=1)
    pts = pts[mask]

    if len(pts) < 4:
        return None

    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)

    pw, ph = (x2 - x1) * 0.2, (y2 - y1) * 0.2
    x1 = float(max(0, x1 - pw) / fw)
    y1 = float(max(0, y1 - ph) / fh)
    x2 = float(min(fw, x2 + pw) / fw)
    y2 = float(min(fh, y2 + ph) / fh)

    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "matches": len(pts)}
