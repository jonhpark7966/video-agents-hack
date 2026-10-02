"""Follow the ball on every source frame.

Claude reads contact sheets and writes coarse keys (t, x, y normalized) into
track_keys.json. This script snaps each frame to the nearest small bright,
roundish blob around the interpolated key, so the trail sits on the real ball
instead of a straight line between guesses. Frames with no blob keep the
interpolated point and are marked `guess`.

  python track.py VIDEO track_keys.json track.json [--debug sheet.jpg]
"""

import json
import sys

import cv2
import numpy as np


def interp_keys(keys, t):
    if t <= keys[0]["t"]:
        return keys[0]["x"], keys[0]["y"]
    for a, b in zip(keys, keys[1:]):
        if a["t"] <= t <= b["t"]:
            u = (t - a["t"]) / max(1e-6, b["t"] - a["t"])
            return a["x"] + (b["x"] - a["x"]) * u, a["y"] + (b["y"] - a["y"]) * u
    return keys[-1]["x"], keys[-1]["y"]


def blobs(frame, cx, cy, radius):
    h, w = frame.shape[:2]
    x0, y0 = max(0, int(cx - radius)), max(0, int(cy - radius))
    x1, y1 = min(w, int(cx + radius)), min(h, int(cy + radius))
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return []
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 2] > 165) & (hsv[..., 1] < 70)).astype(np.uint8)
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    found = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (5 <= area <= 140):
            continue
        if bw > 16 or bh > 16:
            continue
        ratio = max(bw, bh) / max(1, min(bw, bh))
        if ratio > 2.6:
            continue
        found.append((cents[i][0] + x0, cents[i][1] + y0, area))
    return found


def track(video, keys_doc):
    keys = sorted(keys_doc["keys"], key=lambda k: k["t"])
    spans = keys_doc.get("visible", [[0, 1e9]])
    radius_px = keys_doc.get("radius", 34)
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = []
    prev = None
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = index / fps
        visible = any(a <= t <= b for a, b in spans)
        gx, gy = interp_keys(keys, t)
        px, py = gx * w, gy * h
        point = {"f": index, "t": round(t, 4), "x": gx, "y": gy, "visible": visible, "guess": True}
        if visible:
            cands = blobs(frame, px, py, radius_px)
            if cands:
                def cost(c):
                    d = np.hypot(c[0] - px, c[1] - py)
                    if prev is not None:
                        d = 0.6 * d + 0.4 * np.hypot(c[0] - prev[0], c[1] - prev[1])
                    return d
                best = min(cands, key=cost)
                point.update(x=best[0] / w, y=best[1] / h, guess=False)
                prev = (best[0], best[1])
            else:
                prev = None
        out.append(point)
        index += 1
    cap.release()
    # light smoothing that keeps snapped points but softens jitter
    xs = np.array([p["x"] for p in out])
    ys = np.array([p["y"] for p in out])
    k = np.array([1, 2, 3, 2, 1], float)
    k /= k.sum()
    sx = np.convolve(np.pad(xs, 2, mode="edge"), k, "valid")
    sy = np.convolve(np.pad(ys, 2, mode="edge"), k, "valid")
    for p, x, y in zip(out, sx, sy):
        p["sx"], p["sy"] = float(x), float(y)
    return {"fps": fps, "size": [w, h], "frames": out}


def debug_sheet(video, result, out, times, width=640, cols=4):
    from PIL import Image, ImageDraw
    cap = cv2.VideoCapture(video)
    fps = result["fps"]
    w, h = result["size"]
    tiles = []
    for t in times:
        f = int(round(t * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok:
            continue
        p = result["frames"][min(f, len(result["frames"]) - 1)]
        cx, cy = int(p["x"] * w), int(p["y"] * h)
        x0, y0 = max(0, cx - 160), max(0, cy - 90)
        crop = frame[y0:y0 + 180, x0:x0 + 320].copy()
        color = (0, 0, 255) if p["guess"] else (0, 255, 0)
        cv2.circle(crop, (cx - x0, cy - y0), 12, color, 1)
        crop = cv2.resize(crop, (width, width * 180 // 320))
        cv2.putText(crop, f"{t:.2f}s f{f} {'GUESS' if p['guess'] else 'snap'}", (6, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        tiles.append(crop)
    cap.release()
    rows = (len(tiles) + cols - 1) // cols
    th = tiles[0].shape[0]
    canvas = np.zeros((rows * th, cols * width, 3), np.uint8)
    for i, tile in enumerate(tiles):
        r, c = divmod(i, cols)
        canvas[r * th:(r + 1) * th, c * width:(c + 1) * width] = tile
    cv2.imwrite(out, canvas)


if __name__ == "__main__":
    video, keys_path, out_path = sys.argv[1:4]
    with open(keys_path) as handle:
        doc = json.load(handle)
    result = track(video, doc)
    with open(out_path, "w") as handle:
        json.dump(result, handle)
    snapped = sum(1 for p in result["frames"] if p["visible"] and not p["guess"])
    visible = sum(1 for p in result["frames"] if p["visible"])
    print(f"{snapped}/{visible} visible frames snapped to a blob")
    if "--debug" in sys.argv:
        dbg = sys.argv[sys.argv.index("--debug") + 1]
        start = float(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else 0
        end = float(sys.argv[sys.argv.index("--to") + 1]) if "--to" in sys.argv else result["frames"][-1]["t"]
        step = float(sys.argv[sys.argv.index("--step") + 1]) if "--step" in sys.argv else 0.25
        times = list(np.arange(start, end, step))
        debug_sheet(video, result, dbg, times)
