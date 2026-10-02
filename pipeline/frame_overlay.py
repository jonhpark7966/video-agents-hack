"""Frame-level ball box and hit effects for a clip already indexed on VAST.

YOLO stored a box on nearly every frame it could see the ball. The old overlay
kept one key a second, so the graphic lagged behind a shot. This painter reads
every detection, follows the ball through the gaps by looking at the pixels,
and draws the box on the frame it belongs to. A kick or a save gets a shockwave
where the ball meets the player.
"""

import json
import math
import os
import subprocess
import sys
import urllib.parse

import vss_scene

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    video = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "samples", "20261002_212835_23c4d10d.mp4")
    if not os.path.isabs(video):
        video = os.path.join(ROOT, video)
    name = os.path.splitext(os.path.basename(video))[0]
    out_dir = os.path.join(ROOT, "runs", name, "frame_track")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "hype.mp4")

    print("reading YOLO frames from VAST", flush=True)
    pack = load_yolo(video)
    print(
        f"  {len(pack['frames'])} detector frames, {sum(1 for f in pack['frames'] if f['ball'])} with a ball",
        flush=True,
    )
    print("following the ball on every video frame", flush=True)
    track = follow(video, pack)
    hits = mark_goal(video, track, find_hits(track, pack["fps"]), pack)
    print(f"  hits: {', '.join(f'{h['kind']}@{h['t']:.2f}s' for h in hits) or 'none'}", flush=True)
    print("painting", flush=True)
    paint(video, track, hits, pack, out)
    _publish(name, out, hits, pack)
    print(f"done -> {out}", flush=True)


def load_yolo(video):
    meta = vss_scene._probe_local(video)
    chunk = vss_scene._find_chunk(meta["duration"], os.path.basename(video))
    if chunk is None:
        raise RuntimeError("this clip is not in the VAST index")
    backend = vss_scene._backend()
    token = vss_scene._token(backend)
    frames = []
    width, height = meta["size"]
    fps = 24.0
    for segment in chunk.get("timeline") or []:
        source = segment.get("source")
        if not source:
            continue
        start = float(segment.get("segment_start_sec") or 0)
        detections = vss_scene._get(
            backend, token, "/api/v1/videos/detections?" + urllib.parse.urlencode({"source": source})
        )
        shape = detections.get("video_shape") or [height, width]
        height, width = int(shape[0]), int(shape[1])
        fps = float(detections.get("fps") or fps)
        for frame in detections.get("frames") or []:
            people = []
            ball = None
            for det in frame.get("detections") or []:
                box = _pixel_box(det.get("bbox"), width, height)
                if box is None:
                    continue
                try:
                    conf = float(det.get("confidence") or 0)
                except (TypeError, ValueError):
                    conf = 0.0
                label = det.get("label") or ""
                if label == "sports ball" and conf >= 0.2 and _area(box) < 0.001 * width * height:
                    if ball is None or conf > ball[1]:
                        ball = (box, conf)
                elif label == "person" and conf >= 0.4:
                    people.append(box)
            frames.append({
                "t": round(start + float(frame.get("time_sec") or 0), 4),
                "people": people,
                "ball": ball[0] if ball else None,
            })
    frames.sort(key=lambda row: row["t"])
    return {"frames": frames, "size": [width, height], "fps": fps, "duration": meta["duration"]}


def _pixel_box(bbox, width, height):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None
    if max(x1, y1, x2, y2) <= 1.5:
        x1, x2 = x1 * width, x2 * width
        y1, y2 = y1 * height, y2 * height
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return [x1, y1, x2, y2]


def _area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def follow(video, pack):
    """One ball box per video frame.

    YOLO is used on the frame it was measured. Between measurements a few frames
    apart, the box moves in a straight line in the image, which already includes
    the camera. A longer gap stays on the carrier's feet until a later detection
    shows the ball has left that body, and then the box flies to that detection.
    """
    fps = _file_fps(video) or pack["fps"]
    count = _frame_count(video, fps, pack["duration"])
    people = _person_tracks(pack["frames"])
    balls = _clean_balls([(row["t"], row["ball"]) for row in pack["frames"] if row["ball"]])
    rows = []
    owner = None
    for index in range(count):
        t = index / fps
        snapped = _near_ball(balls, t)
        if snapped is not None:
            box = snapped
            owner = _owner(people, t, _center(snapped)) or owner
            source = "yolo"
        else:
            box, owner, source = _fill(t, balls, people, owner)
        person = _track_box(owner, t) if owner is not None else None
        rows.append({"t": round(t, 4), "ball": box, "person": person, "source": source})
    return rows


def _frame_count(video, fps, duration):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames", "-of", "csv=p=0", video],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        count = int(out)
    except ValueError:
        count = 0
    if count <= 0:
        count = int(duration * fps) + 1
    return count


def _person_tracks(frames):
    tracks = []
    for row in frames:
        taken = set()
        pairs = []
        for ti, track in enumerate(tracks):
            if row["t"] - track["keys"][-1]["t"] > 0.28:
                continue
            for di, box in enumerate(row["people"]):
                pairs.append((_iou(track["keys"][-1]["box"], box), ti, di))
        pairs.sort(reverse=True)
        used = set()
        for score, ti, di in pairs:
            if score < 0.12 or ti in taken or di in used:
                continue
            tracks[ti]["keys"].append({"t": row["t"], "box": row["people"][di]})
            taken.add(ti)
            used.add(di)
        for di, box in enumerate(row["people"]):
            if di not in used:
                tracks.append({"keys": [{"t": row["t"], "box": box}]})
    return [track for track in tracks if len(track["keys"]) >= 3]


def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = _area(a) + _area(b) - inter
    return inter / union if union else 0.0


def _track_box(track, t):
    if track is None:
        return None
    keys = track["keys"]
    if t < keys[0]["t"] - 0.06 or t > keys[-1]["t"] + 0.06:
        return None
    if t <= keys[0]["t"]:
        return keys[0]["box"]
    if t >= keys[-1]["t"]:
        return keys[-1]["box"]
    for left, right in zip(keys, keys[1:]):
        if t <= right["t"]:
            span = right["t"] - left["t"]
            if span <= 0 or span > 0.34:
                return left["box"]
            u = (t - left["t"]) / span
            return [left["box"][i] + (right["box"][i] - left["box"][i]) * u for i in range(4)]
    return keys[-1]["box"]


def _feet(box):
    return ((box[0] + box[2]) / 2.0, box[3] - 8.0)


def _owner(tracks, t, point):
    best = None
    best_d = 80
    for track in tracks:
        box = _track_box(track, t)
        if box is None:
            continue
        gap = _dist(point, _feet(box))
        if gap < best_d:
            best, best_d = track, gap
    return best


def _clean_balls(balls):
    """Drop a detection that teleports and comes back. A real shot stays gone."""
    if len(balls) < 3:
        return balls
    kept = [balls[0]]
    for prev, cur, nxt in zip(balls, balls[1:], balls[2:]):
        gap_in = cur[0] - prev[0]
        gap_out = nxt[0] - cur[0]
        jump_in = _dist(_center(prev[1]), _center(cur[1]))
        jump_out = _dist(_center(cur[1]), _center(nxt[1]))
        span = _dist(_center(prev[1]), _center(nxt[1]))
        if gap_in < 0.2 and gap_out < 0.2 and jump_in > 180 and jump_out > 180 and span < 120:
            continue
        kept.append(cur)
    kept.append(balls[-1])
    return kept


def _fill(t, balls, people, owner):
    prev = next(((when, box) for when, box in reversed(balls) if when < t - 0.02), None)
    nxt = next(((when, box) for when, box in balls if when > t + 0.02), None)
    # A few frames between two real boxes: move the box in image space.
    # That motion already includes the camera. Longer gaps are hidden, not guessed.
    if prev and nxt and nxt[0] - prev[0] <= 0.28:
        return _lerp_box(prev, nxt, t), _owner(people, t, _center(_lerp_box(prev, nxt, t))) or owner, "lerp"
    if prev and owner is not None and t - prev[0] <= 0.16:
        box = _track_box(owner, t)
        if box is not None and _dist(_center(prev[1]), _feet(box)) < 70:
            return _box_around(_feet(box), 18, 14), owner, "feet"
    return None, owner, "miss"


def _same_carrier(people, owner, prev, nxt):
    if owner is None:
        owner = _owner(people, prev[0], _center(prev[1]))
    if owner is None:
        return False
    there = _track_box(owner, nxt[0])
    if there is None:
        return False
    return _dist(_center(nxt[1]), _feet(there)) < 75


def _lerp_box(prev, nxt, t):
    span = max(nxt[0] - prev[0], 1e-3)
    u = min(1.0, max(0.0, (t - prev[0]) / span))
    return [a + (b - a) * u for a, b in zip(prev[1], nxt[1])]


def _file_fps(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if "/" in out:
        num, den = out.split("/", 1)
        return float(num) / float(den)
    return float(out or 0) or None


def _near_ball(keys, t, slack=0.03):
    best = None
    best_dt = slack
    for when, box in keys:
        dt = abs(when - t)
        if dt < best_dt:
            best, best_dt = box, dt
    return best


def _box_around(center, bw, bh):
    return [center[0] - bw / 2, center[1] - bh / 2, center[0] + bw / 2, center[1] + bh / 2]


def find_hits(track, fps):
    """Fire only when the measured ball actually jumps away from the previous measurement."""
    seen = [row for row in track if row["source"] == "yolo" and row["ball"] is not None]
    hits = []
    for prev, nxt in zip(seen, seen[1:]):
        travel = _dist(_center(prev["ball"]), _center(nxt["ball"]))
        dt = max(nxt["t"] - prev["t"], 0.04)
        if travel < 140 or dt < 0.12:
            continue
        if hits and nxt["t"] - hits[-1]["t"] < 0.5:
            continue
        rise = _center(prev["ball"])[1] - _center(nxt["ball"])[1]
        near_foot = prev["person"] is not None and _dist(_center(prev["ball"]), _feet(prev["person"])) < 80
        if rise > 90 and travel > 220:
            kind = "SHOT"
        elif near_foot and travel > 200:
            kind = "KICK"
        else:
            kind = "PASS"
        hits.append({
            "t": prev["t"],
            "index": track.index(prev),
            "kind": kind,
            "at": _center(prev["ball"]),
            "to": _center(nxt["ball"]),
            "span": dt,
            "impact": prev["t"],
            "speed": round(travel / dt, 1),
        })
    return hits


def mark_goal(video, track, hits, pack):
    """The last second is the goal. The detector box sits on the grass, so the glow uses the ball in the net."""
    width, height = pack["size"]
    late = [
        row for row in track
        if row["source"] == "yolo" and row["ball"] is not None and row["t"] >= pack["duration"] - 1.5
        and _center(row["ball"])[0] > width * 0.72
    ]
    if len(late) < 2:
        return hits
    start = late[0]
    ball = _find_net_ball(video, start["t"], width, height) or (width * 0.52, height * 0.32)
    print(f"  goal ball at {int(ball[0])},{int(ball[1])}", flush=True)
    hits = [hit for hit in hits if hit["t"] < start["t"] - 0.9]
    hits.append({
        "t": start["t"],
        "index": track.index(start),
        "kind": "GOAL",
        "at": ball,
        "to": ball,
        "focus": (ball[0] + 110, ball[1] + 50),
        "span": 0.4,
        "impact": start["t"] + 0.08,
        "speed": 0,
    })
    return hits


def _find_net_ball(video, t, width, height):
    """A small bright ball in the goal mouth. The YOLO box for this moment is on the grass."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video, "-ss", f"{t:.3f}", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    raw = proc.stdout
    if len(raw) < width * height * 3:
        return None
    best = None
    best_score = 0
    x0, x1 = int(width * 0.46), int(width * 0.64)
    y0, y1 = int(height * 0.26), int(height * 0.42)
    for y in range(y0, y1):
        row = y * width * 3
        for x in range(x0, x1):
            i = row + x * 3
            r, g = raw[i], raw[i + 1]
            if r < 145 or g < 145:
                continue
            neighbor = row + min(width - 1, x + 8) * 3
            score = r + g - raw[neighbor] - raw[neighbor + 1]
            if score > best_score:
                best_score = score
                best = (x, y)
    return best


def paint(video, track, hits, pack, out):
    width, height = pack["size"]
    fps = _file_fps(video) or pack["fps"]
    flat = out + ".flat.mp4"
    proc_in = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", video, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    proc_out = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{width}x{height}", "-r", f"{fps:.5f}", "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", flat],
        stdin=subprocess.PIPE,
    )
    frame_bytes = width * height * 3
    trail = []
    index = 0
    last = None
    try:
        while True:
            raw = proc_in.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            buf = bytearray(raw)
            row = track[index] if index < len(track) else None
            t = index / fps
            goal_hit = next((hit for hit in hits if hit["kind"] == "GOAL"), None)
            false_box = (
                goal_hit and row and row["ball"] and t >= goal_hit["t"] - 0.2
                and _dist(_center(row["ball"]), goal_hit["at"]) > 160
            )
            if row and row["ball"] and not false_box:
                center = _center(row["ball"])
                trail.append(center)
                if len(trail) > 10:
                    trail = trail[-10:]
                _trail(buf, width, height, trail)
                _blend_disk(buf, width, height, int(center[0]), int(center[1]), 16, (255, 210, 40), 0.35)
                if row["person"] and _dist(center, _feet(row["person"])) < 96:
                    _feet_circle(buf, width, height, row["person"], (70, 230, 255))
                moving = len(trail) >= 2 and _dist(trail[-1], trail[-2]) > 10
                if moving:
                    _speed_lines(buf, width, height, trail[-1], trail[-3] if len(trail) >= 3 else trail[-2])
                _rect(buf, width, height, row["ball"], (255, 250, 220) if moving else (255, 220, 40), 4 if moving else 3)
                _corners(buf, width, height, row["ball"], (255, 255, 255))
            else:
                trail = []
            for hit in hits:
                age = t - hit["t"]
                window = 0.95 if hit["kind"] in ("SHOT", "GOAL") else 0.45
                if hit["kind"] != "GOAL" and 0 <= age <= window:
                    u = min(1.0, age / max(hit["span"], 0.05))
                    at = (
                        hit["at"][0] + (hit["to"][0] - hit["at"][0]) * u,
                        hit["at"][1] + (hit["to"][1] - hit["at"][1]) * u,
                    )
                    _pop(buf, width, height, at, age, hit["kind"])
                if hit["kind"] == "GOAL":
                    _goal_light(buf, width, height, hit, t)
            last = buf
            proc_out.stdin.write(buf)
            index += 1
    finally:
        proc_in.stdout.close()
        proc_in.wait()
        proc_out.stdin.close()
        code = proc_out.wait()
    if code != 0:
        raise RuntimeError(f"encode failed ({code})")
    print("  zoom, slow-mo, shake, sound", flush=True)
    _hype(flat, video, hits, pack, out, last)
    os.remove(flat)


def _speed_lines(buf, width, height, center, prev):
    dx, dy = center[0] - prev[0], center[1] - prev[1]
    mag = math.hypot(dx, dy) or 1.0
    ux, uy = dx / mag, dy / mag
    px, py = -uy, ux
    for slot in range(-2, 3):
        x0 = center[0] - ux * 16 + px * slot * 5
        y0 = center[1] - uy * 16 + py * slot * 5
        _line(buf, width, height, x0, y0, x0 - ux * 34, y0 - uy * 34, (255, 244, 160))


def _line(buf, width, height, x0, y0, x1, y1, color):
    steps = int(max(abs(x1 - x0), abs(y1 - y0)))
    if steps <= 0:
        return
    for step in range(steps + 1):
        u = step / steps
        _pixel(buf, width, height, int(x0 + (x1 - x0) * u), int(y0 + (y1 - y0) * u), color)


def _trail(buf, width, height, trail):
    for i, (x, y) in enumerate(trail[:-1]):
        fade = 80 + int(140 * i / max(len(trail) - 1, 1))
        _dot(buf, width, height, int(x), int(y), 2 + (i > len(trail) - 4), (fade, fade, 40))


def _feet_circle(buf, width, height, box, color):
    """A ring on the grass under the player, not a box around the body."""
    cx = (box[0] + box[2]) / 2
    cy = box[3] - 3
    rx = max(22, (box[2] - box[0]) * 0.55)
    ry = max(9, rx * 0.38)
    _ellipse(buf, width, height, cx, cy, rx + 6, ry + 3, (255, 255, 255), 2)
    _ellipse(buf, width, height, cx, cy, rx, ry, color, 4)


def _ellipse(buf, width, height, cx, cy, rx, ry, color, thick):
    if rx < 1 or ry < 1:
        return
    for step in range(0, 360, 3):
        ang = math.radians(step)
        for grow in range(thick):
            x = int(cx + math.cos(ang) * (rx + grow))
            y = int(cy + math.sin(ang) * (ry + grow * 0.45))
            _pixel(buf, width, height, x, y, color)


def _pop(buf, width, height, at, age, kind):
    palettes = {
        "GOAL": [(255, 244, 200), (255, 190, 40), (255, 255, 255), (255, 80, 150), (80, 220, 255)],
        "SHOT": [(255, 40, 90), (255, 170, 0), (40, 255, 210), (170, 70, 255), (255, 255, 255)],
        "KICK": [(255, 80, 20), (255, 200, 40), (255, 255, 255)],
        "PASS": [(40, 210, 255), (180, 255, 255), (255, 255, 255)],
    }
    colors = palettes.get(kind, palettes["PASS"])
    count = 16 if kind in ("SHOT", "GOAL") else 8
    reach = 360 if kind in ("SHOT", "GOAL") else 180
    cx, cy = int(at[0]), int(at[1])
    if kind == "GOAL" and age < 0.08:
        _blend_disk(buf, width, height, cx, cy, 48, (255, 236, 190), 0.4)
    elif kind == "SHOT" and age < 0.045:
        _blend_disk(buf, width, height, cx, cy, 34, (255, 70, 140), 0.55)
    for i, color in enumerate(colors[:3]):
        radius = int(12 + age * (reach + i * 50))
        _circle(buf, width, height, cx, cy, radius, color, 6 if kind == "SHOT" else 4)
    for i in range(count):
        ang = (i / count) * math.tau + age * 4
        dist = 16 + age * reach
        x = int(cx + math.cos(ang) * dist)
        y = int(cy + math.sin(ang) * dist * 0.7)
        _dot(buf, width, height, x, y, 8 if kind == "SHOT" else 4, colors[i % len(colors)])
        if kind == "SHOT":
            _line(
                buf, width, height,
                cx + math.cos(ang) * 10, cy + math.sin(ang) * 8,
                x, y, colors[i % len(colors)],
            )


def _rect(buf, width, height, box, color, thick):
    x1, y1, x2, y2 = [int(v) for v in box]
    for t in range(thick):
        _hline(buf, width, height, x1 - t, x2 + t, y1 - t, color)
        _hline(buf, width, height, x1 - t, x2 + t, y2 + t, color)
        _vline(buf, width, height, x1 - t, y1 - t, y2 + t, color)
        _vline(buf, width, height, x2 + t, y1 - t, y2 + t, color)


def _corners(buf, width, height, box, color):
    x1, y1, x2, y2 = [int(v) for v in box]
    arm = max(6, min(14, (x2 - x1) // 2))
    for x_a, y_a, x_sign, y_sign in (
        (x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1),
    ):
        _hline(buf, width, height, x_a, x_a + x_sign * arm, y_a, color)
        _vline(buf, width, height, x_a, y_a, y_a + y_sign * arm, color)


def _circle(buf, width, height, cx, cy, radius, color, thick):
    if radius < 1:
        return
    for step in range(0, 360, 3):
        ang = math.radians(step)
        for grow in range(thick):
            x = int(cx + math.cos(ang) * (radius + grow))
            y = int(cy + math.sin(ang) * (radius + grow))
            _pixel(buf, width, height, x, y, color)


def _dot(buf, width, height, x, y, radius, color):
    for oy in range(-radius, radius + 1):
        for ox in range(-radius, radius + 1):
            if ox * ox + oy * oy <= radius * radius:
                _pixel(buf, width, height, x + ox, y + oy, color)


def _hline(buf, width, height, x0, x1, y, color):
    if x1 < x0:
        x0, x1 = x1, x0
    for x in range(x0, x1 + 1):
        _pixel(buf, width, height, x, y, color)


def _vline(buf, width, height, x, y0, y1, color):
    if y1 < y0:
        y0, y1 = y1, y0
    for y in range(y0, y1 + 1):
        _pixel(buf, width, height, x, y, color)


def _pixel(buf, width, height, x, y, color):
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    i = (y * width + x) * 3
    buf[i:i + 3] = bytes(color)


def _blend_disk(buf, width, height, cx, cy, radius, color, alpha):
    if radius < 1:
        return
    limit = radius * radius
    for y in range(max(0, cy - radius), min(height, cy + radius + 1)):
        dy = y - cy
        span = int((limit - dy * dy) ** 0.5) if dy * dy <= limit else -1
        if span < 0:
            continue
        row = y * width * 3
        for x in range(max(0, cx - span), min(width, cx + span + 1)):
            i = row + x * 3
            buf[i] = int(buf[i] * (1 - alpha) + color[0] * alpha)
            buf[i + 1] = int(buf[i + 1] * (1 - alpha) + color[1] * alpha)
            buf[i + 2] = int(buf[i + 2] * (1 - alpha) + color[2] * alpha)


def _goal_light(buf, width, height, hit, t):
    """Darken the approach, flare when the ball hits the net, then warm the celebration."""
    impact = hit["impact"]
    at = hit["at"]
    if abs(t - impact) <= 0.09:
        _lift(buf, 0.14, (255, 248, 230))
        _blend_disk(buf, width, height, int(at[0]), int(at[1]), 64, (255, 252, 245), 0.62)
        _blend_disk(buf, width, height, int(at[0]), int(at[1]), 130, (255, 226, 150), 0.24)
        _rays(buf, width, height, at, (255, 244, 200))
    elif t > impact:
        _confetti(buf, width, height, t - impact, 54)


def _lift(buf, alpha, color):
    if alpha <= 0:
        return
    keep = 1 - alpha
    cr, cg, cb = color
    for i in range(0, len(buf), 3):
        buf[i] = int(buf[i] * keep + cr * alpha)
        buf[i + 1] = int(buf[i + 1] * keep + cg * alpha)
        buf[i + 2] = int(buf[i + 2] * keep + cb * alpha)


def _rays(buf, width, height, at, color):
    cx, cy = at
    for i in range(12):
        ang = i * math.tau / 12
        _line(
            buf, width, height,
            cx, cy,
            cx + math.cos(ang) * 90, cy + math.sin(ang) * 54,
            color,
        )


def _confetti(buf, width, height, age, count):
    colors = ((255, 214, 60), (255, 255, 255), (80, 220, 255), (255, 90, 150), (255, 150, 40))
    for i in range(count):
        x = (i * 149 + int(age * 220) * (11 + i % 5)) % width
        y = (i * 97 + int(age * (140 + i % 7 * 20))) % height
        _dot(buf, width, height, x, y, 3 + i % 3, colors[i % len(colors)])


def _hype(flat, source, hits, pack, out, last):
    """Slow the shot, zoom and shake the hits, and lay sound effects on them."""
    width, height = pack["size"]
    duration = pack["duration"]
    pieces = _timeline(duration, hits)
    work = os.path.dirname(out)
    banks = {kind: _sfx(kind, os.path.join(work, f"sfx-{kind.lower()}.wav")) for kind in ("GOAL", "SHOT", "KICK", "PASS")}
    v_labels = []
    a_labels = []
    filters = []
    for i, (start, end, factor, kind, hit) in enumerate(pieces):
        zoom, shake, ramp = _punch(kind)
        focus = (hit.get("focus") or hit["at"]) if hit else (width / 2, height / 2)
        filters.append(_video_piece(i, start, end, factor, zoom, shake, ramp, focus, kind, hit, width, height))
        filters.append(_audio_piece(i, start, end, factor))
        v_labels.append(f"[v{i}]")
        a_labels.append(f"[a{i}]")
    n = len(pieces)
    filters.append(f"{''.join(v_labels)}concat=n={n}:v=1:a=0[vcat]")
    filters.append(f"{''.join(a_labels)}concat=n={n}:v=0:a=1[acat]")
    filters.append("[acat]volume=0.72[bed]")
    mix_inputs = ["[bed]"]
    extra = []
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    draws = []
    colors = {"GOAL": "0xFFE9A2", "SHOT": "0xFFE14A", "KICK": "0xFF5A1F", "PASS": "0x5CFFF2"}
    sizes = {"GOAL": 108, "SHOT": 92, "KICK": 64, "PASS": 54}
    sfx_input = 2
    for hit in hits:
        when = _output_time(hit.get("impact", hit["t"]) if hit["kind"] == "GOAL" else hit["t"], pieces)
        hold = 3.2 if hit["kind"] == "GOAL" else 1.15 if hit["kind"] == "SHOT" else 0.7
        wav = banks[hit["kind"]]
        label = f"s{sfx_input}"
        extra += ["-i", wav]
        delay = int(when * 1000)
        filters.append(f"[{sfx_input}:a]adelay={delay}|{delay},volume=5[{label}]")
        mix_inputs.append(f"[{label}]")
        sfx_input += 1
        size = sizes[hit["kind"]]
        draws.append(
            f"drawtext=fontfile='{font}':text='{hit['kind']}':fontsize={size}:fontcolor={colors[hit['kind']]}:"
            f"borderw=6:bordercolor=black@0.9:x=(w-tw)/2:y=78:"
            f"enable='between(t\\,{when:.3f}\\,{when + hold:.3f})'"
        )
    filters.append(
        f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:normalize=0[aout]"
    )
    if draws:
        filters.append("[vcat]" + ",".join(draws) + "[vout]")
        vmap = "[vout]"
    else:
        vmap = "[vcat]"
    goal = next((hit for hit in hits if hit["kind"] == "GOAL"), None)
    staged = out + ".play.mp4" if goal else out
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", flat, "-i", source, *extra,
        "-filter_complex", ";".join(filters),
        "-map", vmap, "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", staged,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("hype failed: " + (proc.stderr or "")[-800:])
    if not goal:
        return
    print("  celebration", flush=True)
    cel = out + ".cel.mp4"
    _celebration(staged, width, height, cel)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", staged, "-i", cel,
         "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", out],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("celebration join failed: " + (proc.stderr or "")[-800:])
    os.remove(staged)
    os.remove(cel)


def _timeline(duration, hits):
    windows = []
    for hit in hits:
        if hit["kind"] == "GOAL":
            windows.append([max(0.0, hit["t"] - 0.42), duration, 3.2, "goal", hit])
        elif hit["kind"] == "SHOT":
            windows.append([max(0.0, hit["t"] - 0.08), min(duration, hit["t"] + 0.5), 2.4, "shot", hit])
        elif hit["kind"] == "KICK":
            windows.append([max(0.0, hit["t"] - 0.04), min(duration, hit["t"] + 0.28), 1.7, "kick", hit])
        else:
            windows.append([max(0.0, hit["t"] - 0.02), min(duration, hit["t"] + 0.2), 1.0, "pass", hit])
    windows.sort(key=lambda item: item[0])
    placed = []
    for window in windows:
        if placed and window[0] < placed[-1][1]:
            if window[2] > placed[-1][2]:
                placed[-1][1] = window[0]
                if placed[-1][1] - placed[-1][0] < 0.08:
                    placed.pop()
                placed.append(window)
            else:
                window[0] = placed[-1][1]
                if window[1] - window[0] >= 0.08:
                    placed.append(window)
        else:
            placed.append(window)
    pieces = []
    cursor = 0.0
    for start, end, factor, kind, hit in placed:
        if start - cursor > 0.04:
            pieces.append((cursor, start, 1.0, "normal", None))
        pieces.append((start, end, factor, kind, hit))
        cursor = end
    if duration - cursor > 0.04:
        pieces.append((cursor, duration, 1.0, "normal", None))
    return pieces


def _punch(kind):
    """zoom, shake, seconds for the zoom to travel in."""
    if kind == "goal":
        return 1.62, 10, 0.85
    if kind == "shot":
        return 1.48, 12, 0.5
    if kind == "kick":
        return 1.32, 8, 0.32
    if kind == "pass":
        return 1.18, 4, 0.24
    return 1.0, 0, 0.2


def _video_piece(index, start, end, factor, zoom, shake, ramp, focus, kind, hit, width, height):
    base = f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts={factor:.3f}*(PTS-STARTPTS),fps=24"
    if zoom <= 1.01:
        body = base
    else:
        frames = max(6, ramp * 24)
        span = max(zoom - 1, 0.05)
        cx, cy = focus
        body = (
            f"{base},zoompan=z='1+({zoom:.3f}-1)*pow(min(on/{frames:.2f},1),0.55)'"
            f":x='clip(iw/2-(iw/zoom)/2+({cx:.1f}-iw/2)*min((zoom-1)/{span:.3f},1)+{shake:.1f}*sin(on/2.4)*min((zoom-1)/{span:.3f},1),0,iw-iw/zoom)'"
            f":y='clip(ih/2-(ih/zoom)/2+({cy:.1f}-ih/2)*min((zoom-1)/{span:.3f},1)+{shake * 0.45:.1f}*cos(on/3.1)*min((zoom-1)/{span:.3f},1),0,ih-ih/zoom)'"
            f":d=1:s={width}x{height}:fps=24"
        )
    grade = ""
    if kind == "goal" and hit:
        impact = max(0.05, (hit["impact"] - start) * factor)
        grade = (
            f",eq=brightness=-0.11:saturation=0.70:contrast=1.14:enable='lt(t,{impact:.3f})'"
            f",eq=brightness=0.14:saturation=1.4:gamma=0.88:enable='between(t,{impact - 0.02:.3f},{impact + 0.16:.3f})'"
            f",eq=brightness=0.04:saturation=1.32:contrast=1.05:enable='gt(t,{impact + 0.16:.3f})'"
        )
    elif factor >= 1.6:
        grade = ",eq=brightness=-0.06:saturation=0.84:contrast=1.06"
    return f"{body}{grade},format=yuv420p,setsar=1[v{index}]"


def _audio_piece(index, start, end, factor):
    tempo = _tempo(factor)
    return (
        f"[1:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,{tempo}"
        f"aresample=44100,aformat=channel_layouts=stereo[a{index}]"
    )


def _tempo(factor):
    if factor <= 1.05:
        return ""
    rate = 1.0 / factor
    parts = []
    while rate < 0.499:
        parts.append("atempo=0.5")
        rate /= 0.5
    parts.append(f"atempo={rate:.4f}")
    return ",".join(parts) + ","


def _output_time(t, pieces):
    acc = 0.0
    for start, end, factor, _kind, _hit in pieces:
        if t <= start:
            return acc
        if t <= end:
            return acc + (t - start) * factor
        acc += (end - start) * factor
    return acc


def _celebration(play, width, height, path):
    """Hold the zoomed goal and keep the party going: gold light, confetti, a cheer."""
    grab = subprocess.run(
        ["ffmpeg", "-v", "error", "-sseof", "-0.12", "-i", play, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    frame = width * height * 3
    if len(grab.stdout) < frame:
        raise RuntimeError("could not read the goal frame")
    base = bytearray(grab.stdout[-frame:])
    cheer = path + ".wav"
    _cheer(cheer)
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{width}x{height}", "-r", "24", "-i", "-", "-i", cheer,
         "-vf",
         f"drawtext=fontfile='{font}':text='GOAL':fontsize=120:fontcolor=0xFFE9A2:"
         "borderw=8:bordercolor=black@0.88:x=(w-tw)/2:y=70",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", "-movflags", "+faststart", path],
        stdin=subprocess.PIPE,
    )
    try:
        for n in range(24 * 2):
            buf = bytearray(base)
            pulse = 0.08 + 0.05 * math.sin(n / 4.5)
            _lift(buf, pulse, (255, 220, 150))
            _blend_disk(buf, width, height, int(width * 0.46), int(height * 0.32), 170, (255, 246, 210), 0.14 + 0.05 * math.sin(n / 3.0))
            _confetti(buf, width, height, n / 24.0, 80)
            proc.stdin.write(buf)
    finally:
        proc.stdin.close()
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"celebration encode failed ({code})")


def _cheer(path):
    graph = (
        "[0:a]volume=0.9[a];[1:a]volume=0.7[b];[2:a]volume=0.55[c];[3:a]volume=0.35[d];"
        "[4:a]lowpass=f=900,volume=0.35[e];"
        "[a][b][c][d][e]amix=inputs=5:duration=longest:normalize=0,afade=t=in:st=0:d=0.08,afade=t=out:st=1.55:d=0.45,volume=2.2"
    )
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "sine=frequency=523:duration=2:sample_rate=44100",
         "-f", "lavfi", "-i", "sine=frequency=659:duration=2:sample_rate=44100",
         "-f", "lavfi", "-i", "sine=frequency=784:duration=2:sample_rate=44100",
         "-f", "lavfi", "-i", "sine=frequency=1046:duration=1.4:sample_rate=44100",
         "-f", "lavfi", "-i", "anoisesrc=duration=2:color=pink:sample_rate=44100",
         "-filter_complex", graph, "-c:a", "pcm_s16le", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("cheer failed: " + (proc.stderr or "")[-400:])


def _sfx(kind, path):
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    if kind == "GOAL":
        graph = (
            "[0:a]volume=2.6,afade=t=out:st=0.05:d=0.35[a];"
            "[1:a]highpass=f=400,volume=0.8,afade=t=out:st=0.02:d=0.2[b];"
            "[2:a]volume=0.7,afade=t=in:st=0.02:d=0.04,afade=t=out:st=0.12:d=0.35[c];"
            "[3:a]volume=0.45,afade=t=out:st=0.08:d=0.4[d];"
            "[a][b][c][d]amix=inputs=4:duration=longest:normalize=0"
        )
        inputs = [
            "-f", "lavfi", "-i", "sine=frequency=62:duration=0.45:sample_rate=44100",
            "-f", "lavfi", "-i", "anoisesrc=duration=0.22:color=white:sample_rate=44100",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=0.5:sample_rate=44100",
            "-f", "lavfi", "-i", "sine=frequency=1318:duration=0.5:sample_rate=44100",
        ]
    elif kind == "SHOT":
        graph = (
            "[0:a]volume=2.4,afade=t=out:st=0.08:d=0.32[a];"
            "[1:a]highpass=f=500,volume=0.9,afade=t=out:st=0.02:d=0.16[b];"
            "[2:a]volume=0.55,afade=t=out:st=0.01:d=0.14[c];"
            "[a][b][c]amix=inputs=3:duration=longest:normalize=0"
        )
        inputs = [
            "-f", "lavfi", "-i", "sine=frequency=58:duration=0.42:sample_rate=44100",
            "-f", "lavfi", "-i", "anoisesrc=duration=0.2:color=white:sample_rate=44100",
            "-f", "lavfi", "-i", "sine=frequency=1280:duration=0.16:sample_rate=44100",
        ]
    elif kind == "KICK":
        graph = (
            "[0:a]volume=2.2,afade=t=out:st=0.03:d=0.1[a];"
            "[1:a]highpass=f=200,volume=0.7,afade=t=out:st=0.02:d=0.08[b];"
            "[a][b]amix=inputs=2:duration=longest:normalize=0"
        )
        inputs = [
            "-f", "lavfi", "-i", "sine=frequency=95:duration=0.14:sample_rate=44100",
            "-f", "lavfi", "-i", "anoisesrc=duration=0.1:color=pink:sample_rate=44100",
        ]
    else:
        graph = "[0:a]highpass=f=700,lowpass=f=4000,volume=1.3,afade=t=in:st=0:d=0.02,afade=t=out:st=0.05:d=0.12"
        inputs = ["-f", "lavfi", "-i", "anoisesrc=duration=0.18:color=white:sample_rate=44100"]
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-c:a", "pcm_s16le", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sfx {kind} failed: {(proc.stderr or '')[-400:]}")
    return path


def _publish(name, out, hits, pack):
    manifest_path = os.path.join(ROOT, "runs", name, "manifest.json")
    data = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as handle:
            data = json.load(handle)
    data["video"] = "samples/20261002_212835_23c4d10d.mp4"
    data["frame_track"] = os.path.relpath(out, ROOT)
    data["frame_hits"] = [{"t": hit["t"], "kind": hit["kind"]} for hit in hits]
    data["frame_note"] = (
        "The goal clip. The picture zooms in over the shot, the slow motion goes darker, "
        "and the net lights up. After the goal the frame holds with a gold glow, confetti, and a cheer."
    )
    tmp = manifest_path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, manifest_path)


if __name__ == "__main__":
    main()
