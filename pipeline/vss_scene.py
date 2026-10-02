"""Build scene.json from a clip that is already indexed on this VAST instance.

The 10-second sample is live in VSS: Cosmos wrote the caption, YOLO wrote
per-frame boxes. This module reads those rows and turns the boxes into the
tracks the overlay renderer follows.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import claude_bin


def from_indexed(video):
    """Return a scene dict, or None when this file is not the indexed upload."""
    meta = _probe_local(video)
    if meta is None:
        return None
    chunk = _find_chunk(meta["duration"])
    if chunk is None:
        return None
    tracks, fps, size = _tracks_from_chunk(chunk)
    if len(tracks) < 2:
        return None
    summary, events = _events(chunk, tracks, meta["duration"])
    return {
        "video": video,
        "source": "vast-yolo",
        "vast_video": chunk.get("filename") or "",
        "size": size,
        "fps": fps,
        "duration": meta["duration"],
        "summary": summary,
        "shots": [{"start": 0.0, "end": meta["duration"], "kind": "wide-live"}],
        "tracks": tracks,
        "events": events,
    }


def _probe_local(video):
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration", "-of", "json", video],
            capture_output=True, text=True, check=True,
        ).stdout
        info = json.loads(out)
        stream = info["streams"][0]
        return {
            "duration": float(info["format"]["duration"]),
            "size": [stream["width"], stream["height"]],
        }
    except (OSError, subprocess.CalledProcessError, KeyError, ValueError):
        return None


def _backend():
    claude_bin.ensure_env()
    backend = os.environ.get("INGRESS_URL", "").rstrip("/")
    if not backend:
        raise RuntimeError("INGRESS_URL is not set")
    return backend


def _token(backend):
    body = json.dumps({
        "username": os.environ["USERNAME"],
        "password": os.environ["PASSWORD"],
    }).encode()
    req = urllib.request.Request(
        backend + "/api/v1/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)["access_token"]


def _get(backend, token, path):
    req = urllib.request.Request(
        backend + path,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:240]
        raise RuntimeError(f"VSS {exc.code} {path.split('?')[0]}: {detail}") from exc


def _find_chunk(duration, filename=None):
    backend = _backend()
    token = _token(backend)
    offset = 0
    best = None
    exact = None
    while offset < 240:
        data = _get(backend, token, f"/api/v1/videos/explore?scope=all&limit=48&offset={offset}")
        chunks = data.get("chunks") or []
        if not chunks:
            break
        for chunk in chunks:
            name = chunk.get("filename") or ""
            if filename and name == filename:
                exact = chunk
            if "_chunk_" in name:
                continue
            try:
                span = float(chunk.get("chunk_duration_sec") or 0)
            except (TypeError, ValueError):
                continue
            if abs(span - duration) > 0.3:
                continue
            if best is None or (chunk.get("upload_timestamp") or "") > (best.get("upload_timestamp") or ""):
                best = chunk
        offset += 48
        if offset >= int(data.get("total") or 0):
            break
    return exact or best


def _tracks_from_chunk(chunk):
    backend = _backend()
    token = _token(backend)
    samples = []
    fps = 24.0
    size = [1920, 1080]
    for segment in chunk.get("timeline") or []:
        source = segment.get("source")
        if not source:
            continue
        start = float(segment.get("segment_start_sec") or 0)
        query = urllib.parse.urlencode({"source": source})
        detections = _get(backend, token, "/api/v1/videos/detections?" + query)
        shape = detections.get("video_shape") or [1080, 1920]
        height, width = int(shape[0]), int(shape[1])
        size = [width, height]
        fps = float(detections.get("fps") or fps)
        frames = detections.get("frames") or []
        step = max(1, int(round(fps / 4)))
        for index, frame in enumerate(frames):
            dets = frame.get("detections") or []
            has_ball = any(det.get("label") == "sports ball" for det in dets)
            if index % step and not has_ball:
                continue
            t = start + float(frame.get("time_sec") or 0)
            people = []
            ball = None
            for det in frame.get("detections") or []:
                box = _norm_box(det.get("bbox"), width, height)
                if box is None:
                    continue
                try:
                    conf = float(det.get("confidence") or 0)
                except (TypeError, ValueError):
                    conf = 0
                label = det.get("label") or ""
                if label == "sports ball" and conf >= 0.2:
                    if ball is None or conf > ball["conf"]:
                        ball = {"box": box, "conf": conf}
                elif label == "person" and conf >= 0.45:
                    people.append({"box": box, "conf": conf})
            samples.append({"t": round(t, 2), "people": people, "ball": ball})
    samples.sort(key=lambda row: row["t"])
    ball_keys = _ball_keys(samples)
    chosen = _follow_ball(samples, ball_keys)
    tracks = []
    if ball_keys:
        tracks.append({"id": "ball", "label": "ball", "team": "", "name": "", "keys": _thin(ball_keys)})
    tracks.extend(chosen)
    return tracks, round(fps, 3), size


def _norm_box(bbox, width, height):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    x = min(max(x1 / width, 0.0), 0.98)
    y = min(max(y1 / height, 0.0), 0.98)
    w = min(max((x2 - x1) / width, 0.008), 0.4)
    h = min(max((y2 - y1) / height, 0.012), 0.5)
    return [round(x, 3), round(y, 3), round(w, 3), round(h, 3)]


def _center(box):
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _ball_keys(samples):
    keys = []
    for row in samples:
        ball = row["ball"]
        if ball is None:
            continue
        box = ball["box"]
        # A real ball is a few pixels. A big box is a false detect (a logo, a foot).
        if box[2] * box[3] > 0.001:
            continue
        keys.append({"t": row["t"], "box": box})
    return _drop_ball_spikes(keys)


def _drop_ball_spikes(keys):
    """Drop a detect that jumps away and comes back. A real shot stays gone."""
    if len(keys) < 3:
        return keys
    kept = [keys[0]]
    for prev, cur, nxt in zip(keys, keys[1:], keys[2:]):
        jump_away = _dist(_center(prev["box"]), _center(cur["box"]))
        jump_back = _dist(_center(cur["box"]), _center(nxt["box"]))
        span = _dist(_center(prev["box"]), _center(nxt["box"]))
        if jump_away > 0.28 and jump_back > 0.28 and span < 0.35:
            continue
        kept.append(cur)
    kept.append(keys[-1])
    return kept


def _ball_at(keys, t):
    if not keys:
        return None
    if t <= keys[0]["t"]:
        return keys[0]["box"]
    for a, b in zip(keys, keys[1:]):
        if t <= b["t"]:
            return a["box"]
    return keys[-1]["box"]


def _follow_ball(samples, ball_keys):
    """The overlay disc sits on whoever is nearest the ball at that moment."""
    buckets = {"carrier": [], "marker": [], "support": []}
    for row in samples:
        ball_box = row["ball"]["box"] if row["ball"] else _ball_at(ball_keys, row["t"])
        if ball_box is None or not row["people"]:
            continue
        ordered = sorted(
            row["people"],
            key=lambda det: _dist(_center(det["box"]), _center(ball_box)),
        )
        limits = (("carrier", 0.22), ("marker", 0.32), ("support", 0.42))
        for (track_id, limit), det in zip(limits, ordered):
            if _dist(_center(det["box"]), _center(ball_box)) > limit:
                break
            buckets[track_id].append({"t": row["t"], "box": det["box"]})
    labels = {
        "carrier": "ball carrier",
        "marker": "nearest defender",
        "support": "supporting runner",
    }
    chosen = []
    for track_id in ("carrier", "marker", "support"):
        keys = _thin(buckets[track_id])
        if len(keys) < 2:
            continue
        chosen.append({
            "id": track_id,
            "label": labels[track_id],
            "team": "",
            "name": "",
            "keys": _hold_jumps(keys),
        })
    return chosen


def _hold_jumps(keys, limit=0.12):
    """Cut to a new body instead of sliding the box across empty grass."""
    if len(keys) < 2:
        return keys
    held = [keys[0]]
    for prev, cur in zip(keys, keys[1:]):
        moved = _dist(_center(prev["box"]), _center(cur["box"]))
        if moved > limit and cur["t"] > prev["t"]:
            cut = round(max(prev["t"], cur["t"] - 0.04), 2)
            if cut > held[-1]["t"]:
                held.append({"t": cut, "box": prev["box"]})
        held.append(cur)
    return held


def _thin(keys):
    """Keep about one box per second so the renderer expression stays short."""
    if len(keys) <= 2:
        return keys
    kept = [keys[0]]
    for key in keys[1:]:
        if key["t"] - kept[-1]["t"] >= 0.9:
            kept.append(key)
    if kept[-1]["t"] != keys[-1]["t"]:
        kept.append(keys[-1])
    return kept


def _events(chunk, tracks, duration):
    ids = [track["id"] for track in tracks]
    caption = (chunk.get("reasoning_content") or "").strip()
    if len(caption) > 1800:
        caption = caption[:1800]
    summary = caption.split(". ")[0].strip()
    if summary and not summary.endswith("."):
        summary += "."
    prompt = f"""Turn this indexed soccer caption into overlay events.
Duration is {duration:.2f} seconds. Use only these track ids: {", ".join(ids)}.

Caption:
{caption or "A soccer play."}

Return JSON:
{{
  "summary": "one sentence",
  "events": [
    {{"start": 0.4, "end": 3.0, "type": "dribble", "actors": ["carrier", "ball"], "caption": "short"}}
  ]
}}
Two to four events. Times must sit inside 0 to {duration:.2f}.
Only describe what the caption supports. If the keeper saves the shot, do not add a goal.
"""
    try:
        data = claude_bin.call_claude(prompt, effort="low", label="vast events")
        events = []
        for raw in data.get("events") or []:
            if not isinstance(raw, dict):
                continue
            try:
                start, end = float(raw.get("start", 0)), float(raw.get("end", 0))
            except (TypeError, ValueError):
                continue
            actors = [a for a in (raw.get("actors") or []) if a in ids]
            events.append({
                "start": round(min(max(start, 0.0), duration), 2),
                "end": round(min(max(end, 0.0), duration), 2),
                "type": str(raw.get("type") or "play"),
                "actors": actors,
                "caption": str(raw.get("caption") or ""),
            })
        text = str(data.get("summary") or summary or caption[:240])
        return text, events
    except Exception as exc:
        print(f"  vast events failed ({exc}); using the indexed caption", flush=True)
        events = [{
            "start": 0.4,
            "end": round(max(1.5, duration - 0.3), 2),
            "type": "play",
            "actors": [track_id for track_id in ("carrier", "ball") if track_id in ids],
            "caption": summary or "The move develops toward goal.",
        }]
        return summary or caption[:240], events
