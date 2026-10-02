"""Odd steps — the Reason team.

Same two calls as the mock:

  perceive(video)                    -> scene.json
  evaluate(rendered, overlay, scene) -> critique.json

Both call the claude binary (Opus 5.5) on frames from the clip. If a call
fails, perceive uses a coarse scene for this sample and evaluate falls back
to the mock's rule checks, so a generate run can still finish.
"""

import json
import os
import subprocess
import tempfile

import claude_bin

MIN_ON_SCREEN = 1.5
MIN_FONT = 28
MAX_WPS = 3.0
PASS_SCORE = 0.85
MODEL = claude_bin.MODEL

AXES = ["accuracy", "readability", "timing", "coverage", "style"]


def probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate:format=duration", "-of", "json", video],
        capture_output=True, text=True, check=True,
    ).stdout
    info = json.loads(out)
    stream = info["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return {
        "size": [stream["width"], stream["height"]],
        "fps": round(int(num) / int(den), 3),
        "duration": float(info["format"]["duration"]),
    }


def extract_frames(video, times, dest):
    os.makedirs(dest, exist_ok=True)
    frames = []
    for t in times:
        path = os.path.join(dest, f"t{t:.2f}.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
             "-vf", "scale=960:-1", path, "-hide_banner", "-loglevel", "error"],
            check=True,
        )
        frames.append((t, os.path.abspath(path)))
    return frames


def sample_times(duration, n):
    hi = max(0.2, duration - 0.25)
    if n == 1:
        return [round(hi / 2, 2)]
    return [round(hi * i / (n - 1), 2) for i in range(n)]


def _frame_list(frames):
    return "\n".join(f"- t={t:.2f}s  {path}" for t, path in frames)


def _clamp01(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _norm_box(box):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        vals = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if max(abs(v) for v in vals) > 1.5:
        vals = [v / 100.0 for v in vals]
    x, y, w, h = vals
    w, h = abs(w), abs(h)
    x = min(max(x, 0.0), 0.98)
    y = min(max(y, 0.0), 0.98)
    w = min(max(w, 0.008), 0.4)
    h = min(max(h, 0.012), 0.5)
    return [round(x, 3), round(y, 3), round(w, 3), round(h, 3)]


def perceive(video, frame_dir=None):
    """Step 1. Claude looks at frames and writes the scene. Tracks are estimates."""
    meta = probe(video)
    duration = meta["duration"]
    times = sample_times(duration, 5)
    if frame_dir is None:
        frame_dir = tempfile.mkdtemp(prefix="perceive-")
    frames = extract_frames(video, times, frame_dir)
    w, h = meta["size"]
    prompt = f"""These frames are from one soccer clip of {duration:.2f}s at {w}x{h}.
Read every image, then return a scene JSON object.

Coordinates are normalized [x, y, w, h], origin top-left, 0 to 1 of the full frame.
A player in a wide broadcast shot is small. Example: a player near the middle might be
[0.48, 0.42, 0.03, 0.10]. The ball is about [0.50, 0.55, 0.012, 0.02].
Do not return pixel coordinates. Do not return 0-100 numbers.

Fulham wear white. Sheffield United wear red-and-white stripes. The goalkeeper is green.
The referee is yellow. The broadcast already shows a lower-third naming Rodrigo Muniz
at the bottom left; that graphic is not a player.

Include 4 to 6 tracks: the ball, the Fulham player nearest the ball, one Sheffield
defender who matters, the goalkeeper if visible, and Muniz if you can tell which
white-shirt player he is. Each track needs an id (ball, muniz, carrier, defender, keeper),
a label, and keys at the frame times below. Skip a key when the person is off screen.
Box x,y is the top-left of the body, not the center.

Events only for what these frames actually show. The goal finish may be after this
slice. Do not add a goal event unless the ball clearly enters the net here.
Shots cover the whole clip. summary is one sentence.

Frames:
{_frame_list(frames)}

JSON keys:
{{
  "summary": "...",
  "shots": [{{"start": 0, "end": {duration:.2f}, "kind": "wide-live"}}],
  "tracks": [{{"id": "ball", "label": "ball", "team": "", "name": "", "keys": [{{"t": 0.0, "box": [0.5, 0.5, 0.012, 0.02]}}]}}],
  "events": [{{"start": 0.0, "end": 2.0, "type": "carry", "actors": ["carrier"], "caption": "..."}}]
}}
"""
    try:
        data = claude_bin.call_claude(prompt, images=frames, effort="medium", budget=2.0, label="perceive")
        scene = _clean_scene(data, video, meta)
        if len(scene["tracks"]) < 2:
            raise RuntimeError("perceive returned too few tracks")
        return scene
    except Exception as exc:
        print(f"  perceive failed ({exc}); using the coarse sample scene", flush=True)
        scene = _fallback_scene(video, meta)
        scene["error"] = str(exc)
        return scene


def _clean_scene(data, video, meta):
    duration = meta["duration"]
    tracks = []
    for raw in data.get("tracks") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        keys = []
        for key in raw.get("keys") or []:
            if not isinstance(key, dict):
                continue
            box = _norm_box(key.get("box"))
            if box is None:
                continue
            try:
                t = float(key.get("t"))
            except (TypeError, ValueError):
                continue
            t = min(max(t, 0.0), duration)
            keys.append({"t": round(t, 2), "box": box})
        keys.sort(key=lambda k: k["t"])
        if not keys:
            continue
        tracks.append({
            "id": str(raw["id"]),
            "label": str(raw.get("label") or raw["id"]),
            "team": str(raw.get("team") or ""),
            "name": str(raw.get("name") or ""),
            "keys": keys,
        })
    ids = {t["id"] for t in tracks}
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
    shots = []
    for raw in data.get("shots") or []:
        if not isinstance(raw, dict):
            continue
        try:
            shots.append({
                "start": float(raw.get("start", 0)),
                "end": float(raw.get("end", duration)),
                "kind": str(raw.get("kind") or "wide-live"),
            })
        except (TypeError, ValueError):
            continue
    if not shots:
        shots = [{"start": 0.0, "end": duration, "kind": "wide-live"}]
    return {
        "video": video,
        "source": MODEL,
        **meta,
        "summary": str(data.get("summary") or ""),
        "shots": shots,
        "tracks": tracks,
        "events": events,
    }


def _fallback_scene(video, meta):
    """Coarse boxes for the 0–8s Muniz clip if Claude cannot see the frames."""
    duration = meta["duration"]
    return {
        "video": video,
        "source": "fallback",
        **meta,
        "summary": "Wide Premier League build-up: Fulham in white move the ball toward the left-hand goal, then it goes wide.",
        "shots": [{"start": 0.0, "end": duration, "kind": "wide-live"}],
        "tracks": [
            {"id": "ball", "label": "ball", "team": "", "name": "", "keys": [
                {"t": 0.4, "box": [0.40, 0.58, 0.012, 0.02]},
                {"t": 4.0, "box": [0.52, 0.46, 0.012, 0.02]},
                {"t": 7.5, "box": [0.76, 0.40, 0.012, 0.02]}]},
            {"id": "carrier", "label": "player", "team": "Fulham", "name": "", "keys": [
                {"t": 0.4, "box": [0.38, 0.52, 0.028, 0.09]},
                {"t": 4.0, "box": [0.50, 0.40, 0.028, 0.09]},
                {"t": 7.5, "box": [0.74, 0.34, 0.028, 0.09]}]},
            {"id": "muniz", "label": "player", "team": "Fulham", "name": "Muniz", "keys": [
                {"t": 0.4, "box": [0.34, 0.55, 0.028, 0.09]},
                {"t": 4.0, "box": [0.42, 0.42, 0.028, 0.09]},
                {"t": 7.5, "box": [0.46, 0.38, 0.028, 0.09]}]},
            {"id": "defender", "label": "player", "team": "Sheffield United", "name": "", "keys": [
                {"t": 0.4, "box": [0.46, 0.34, 0.026, 0.09]},
                {"t": 4.0, "box": [0.36, 0.36, 0.026, 0.09]},
                {"t": 7.5, "box": [0.40, 0.34, 0.026, 0.09]}]},
            {"id": "keeper", "label": "keeper", "team": "Sheffield United", "name": "", "keys": [
                {"t": 0.4, "box": [0.20, 0.22, 0.02, 0.07]},
                {"t": 4.0, "box": [0.16, 0.28, 0.02, 0.07]},
                {"t": 7.5, "box": [0.12, 0.30, 0.02, 0.07]}]},
        ],
        "events": [
            {"start": 0.4, "end": 4.0, "type": "carry", "actors": ["carrier", "ball"],
             "caption": "Fulham carry the ball toward the left-hand box."},
            {"start": 4.0, "end": min(7.8, duration), "type": "switch", "actors": ["carrier", "ball"],
             "caption": "The ball is played into the wide area."},
        ],
    }


def evaluate(rendered, overlay, scene):
    """Step 3. Claude grades frames of the rendered overlay. Rules run only if that call fails."""
    try:
        return _evaluate_claude(rendered, overlay, scene)
    except Exception as exc:
        print(f"  evaluate failed ({exc}); using rule checks", flush=True)
        critique = _evaluate_rules(rendered, overlay, scene)
        critique["error"] = str(exc)
        return critique


def _evaluate_claude(rendered, overlay, scene):
    duration = float(scene["duration"])
    times = sample_times(duration, 3)
    dest = os.path.join(os.path.dirname(os.path.abspath(rendered)), "frames")
    frames = extract_frames(rendered, times, dest)
    style = overlay.get("style") or "unspecified"
    guide = ""
    guide_path = os.path.join(os.path.dirname(__file__), "prompt_guide.md")
    if os.path.exists(guide_path):
        text = open(guide_path).read()
        marker = f"## {style}\n"
        if marker in text:
            guide = text.split(marker, 1)[1].split("\n## ", 1)[0].strip()
    brief = {
        "style": style,
        "items": [
            {k: item.get(k) for k in ("id", "kind", "track", "to", "start", "end", "text", "color")}
            for item in overlay.get("items", [])
        ],
        "explanation": overlay.get("explanation", []),
    }
    prompt = f"""Grade this soccer overlay. Read the three frames first. Trust what you see in the frames.
The JSON is only what the generator meant to draw.

Clip length {duration:.2f}s. Style that was requested: {style}.
{guide}

Scene summary: {scene.get("summary", "")}
Events: {json.dumps(scene.get("events", []), ensure_ascii=True)}
Intended overlay: {json.dumps(brief, ensure_ascii=True)}

Frames:
{_frame_list(frames)}

Score each axis from 0 to 1 (1 = nothing to fix): accuracy, readability, timing, coverage, style.
accuracy: marker sits on the player or ball it names, and the words match the scene.
readability: words are large enough, stay up long enough, and do not cover the ball or the bottom-left name bug.
timing: graphics are up while that action is happening.
coverage: the main action in the summary is marked or captioned.
style: the frames follow the requested style, not a different one.

Return JSON:
{{
  "summary": "two sentences a person can read",
  "scores": {{"accuracy": 0.5, "readability": 0.5, "timing": 0.5, "coverage": 0.5, "style": 0.5}},
  "issues": [{{"item": "o1", "type": "wrong_target", "axis": "accuracy", "detail": "what is wrong", "fix": "what to change"}}]
}}
Use 0 to 4 issues. Empty issues if it is actually good. item is an overlay id or "".
"""
    data = claude_bin.call_claude(prompt, images=frames, effort="low", budget=1.5, label="evaluate")
    scores = data.get("scores") or {}
    clean_scores = {axis: round(_clamp01(scores.get(axis, 0)), 3) for axis in AXES}
    score = round(sum(clean_scores.values()) / len(AXES), 3)
    issues = []
    for raw in data.get("issues") or []:
        if not isinstance(raw, dict):
            continue
        issues.append({
            "item": raw.get("item") or "",
            "type": str(raw.get("type") or "note"),
            "axis": str(raw.get("axis") or "style"),
            "detail": str(raw.get("detail") or ""),
            "fix": raw.get("fix") if isinstance(raw.get("fix"), str) else str(raw.get("fix") or ""),
        })
    return {
        "iteration": overlay.get("iteration", 0),
        "video": rendered,
        "source": MODEL,
        "style": style,
        "score": score,
        "pass": score >= PASS_SCORE,
        "scores": clean_scores,
        "summary": str(data.get("summary") or ""),
        "issues": issues,
    }


def _words_per_sec(line):
    return len(line["text"].split()) / max(line["end"] - line["start"], 0.01)


def _evaluate_rules(rendered, overlay, scene):
    """The mock checker. It does not look at pixels."""
    track_ids = {t["id"] for t in scene["tracks"]}
    issues = []
    for item in overlay.get("items", []):
        if item.get("track") and item["track"] not in track_ids:
            issues.append({"item": item["id"], "type": "wrong_target", "axis": "accuracy",
                           "detail": f"{item['track']} is not a tracked object", "fix": "drop this item"})
        shown = item["end"] - item["start"]
        if item.get("text") and shown < MIN_ON_SCREEN:
            issues.append({"item": item["id"], "type": "too_short", "axis": "readability",
                           "detail": f"label up {shown:.1f}s, needs {MIN_ON_SCREEN}s",
                           "fix": f"end at {item['start'] + MIN_ON_SCREEN:.2f}"})
        if item.get("text") and item.get("size", MIN_FONT) < MIN_FONT:
            issues.append({"item": item["id"], "type": "too_small", "axis": "readability",
                           "detail": f"font {item.get('size')}px, needs {MIN_FONT}px", "fix": f"size {MIN_FONT}"})
    for line in overlay.get("explanation", []):
        wps = _words_per_sec(line)
        if wps > MAX_WPS:
            issues.append({"item": line["id"], "type": "too_fast", "axis": "timing",
                           "detail": f"{wps:.1f} words/s, max {MAX_WPS}", "fix": "shorten the line or hold it longer"})
    lines = sorted(overlay.get("explanation", []), key=lambda line: line["start"])
    for prev, line in zip(lines, lines[1:]):
        if line["start"] < prev["end"]:
            issues.append({"item": line["id"], "type": "overlap", "axis": "timing",
                           "detail": f"starts {line['start']}s while {prev['id']} is up until {prev['end']}s",
                           "fix": f"start at {prev['end']}"})
    for event in scene.get("events", []):
        covered = any(line["start"] < event["end"] and line["end"] > event["start"]
                      for line in overlay.get("explanation", []))
        if not covered:
            issues.append({"item": "", "type": "missed_event", "axis": "coverage",
                           "detail": f"{event['type']} at {event['start']}s is not explained",
                           "fix": event.get("caption", "")})
    scores = {axis: max(0.0, 1.0 - 0.25 * sum(i["axis"] == axis for i in issues)) for axis in AXES}
    if not any(i["axis"] == "style" for i in issues):
        scores["style"] = 0.7
    score = round(sum(scores.values()) / len(AXES), 3)
    return {
        "iteration": overlay.get("iteration", 0),
        "video": rendered,
        "source": "rules",
        "style": overlay.get("style"),
        "score": score,
        "pass": score >= PASS_SCORE,
        "scores": scores,
        "summary": f"Rule check only ({len(issues)} issues). Claude did not grade the frames.",
        "issues": issues,
    }
