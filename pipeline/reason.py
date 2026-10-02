"""Odd steps — the Reason team (Cosmos Reason + YOLO).

  step 1  perceive(video)                   -> scene.json
  step 3  evaluate(rendered, overlay, scene) -> critique.json

Both are mocks. Replace the bodies, keep the JSON shapes in contracts/.
"""

import json
import math
import subprocess

MIN_ON_SCREEN = 1.5  # seconds a label must stay up to be readable
MIN_FONT = 40  # px at 1080p
MAX_WPS = 3.0  # explanation words per second
PASS_SCORE = 0.95


def probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate:format=duration", "-of", "json", video],
        capture_output=True, text=True, check=True,
    ).stdout
    info = json.loads(out)
    s = info["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"size": [s["width"], s["height"]], "fps": round(int(num) / int(den), 3),
            "duration": float(info["format"]["duration"])}


def perceive(video):
    """Step 1. TODO: YOLO for boxes + tracks, Cosmos Reason for shots/events/summary."""
    # Hand-placed stand-ins for the sample clip (Muniz, Sheff Utd 3-3 Fulham).
    # Boxes are normalized [x, y, w, h], top-left origin.
    return {
        "video": video,
        "source": "mock",
        **probe(video),
        "shots": [
            {"start": 0.0, "end": 14.0, "kind": "wide-live"},
            {"start": 14.0, "end": 38.0, "kind": "replay"},
        ],
        "tracks": [
            {"id": "ball", "label": "ball", "keys": [
                {"t": 4.0, "box": [0.60, 0.50, 0.012, 0.02]},
                {"t": 8.0, "box": [0.30, 0.44, 0.012, 0.02]},
                {"t": 11.0, "box": [0.12, 0.38, 0.012, 0.02]}]},
            {"id": "p19", "label": "player", "team": "Fulham", "name": "Muniz", "keys": [
                {"t": 4.0, "box": [0.50, 0.40, 0.025, 0.09]},
                {"t": 8.0, "box": [0.26, 0.40, 0.025, 0.09]},
                {"t": 11.0, "box": [0.16, 0.36, 0.025, 0.09]}]},
            {"id": "p_cross", "label": "player", "team": "Fulham", "keys": [
                {"t": 4.0, "box": [0.70, 0.55, 0.025, 0.09]},
                {"t": 8.0, "box": [0.42, 0.52, 0.025, 0.09]}]},
        ],
        "events": [
            {"start": 6.0, "end": 8.5, "type": "cross", "actors": ["p_cross", "p19"],
             "caption": "Ball is worked wide and crossed into the box."},
            {"start": 9.0, "end": 12.0, "type": "goal", "actors": ["p19"],
             "caption": "Muniz finishes acrobatically at the near post."},
        ],
        "summary": "Late Fulham equaliser: wide build-up, cross, acrobatic finish, then replays.",
    }


def _words_per_sec(line):
    return len(line["text"].split()) / max(line["end"] - line["start"], 0.01)


def evaluate(rendered, overlay, scene):
    """Step 3. TODO: feed `rendered` to Cosmos Reason and ask it to grade the overlay.

    The mock never looks at pixels; it applies the rules Cosmos would be asked about.
    Each issue carries a machine-readable `fix` so the Gen team can act without parsing prose.
    """
    track_ids = {t["id"] for t in scene["tracks"]}
    issues = []

    for item in overlay["items"]:
        if item.get("track") and item["track"] not in track_ids:
            issues.append({"item": item["id"], "type": "wrong_target", "axis": "accuracy",
                           "detail": f"{item['track']} is not a tracked object", "fix": {"drop": True}})
        shown = item["end"] - item["start"]
        if item.get("text") and shown < MIN_ON_SCREEN:
            issues.append({"item": item["id"], "type": "too_short", "axis": "readability",
                           "detail": f"label up {shown:.1f}s, needs {MIN_ON_SCREEN}s",
                           "fix": {"end": round(item["start"] + MIN_ON_SCREEN, 2)}})
        if item.get("text") and item.get("size", 0) < MIN_FONT:
            issues.append({"item": item["id"], "type": "too_small", "axis": "readability",
                           "detail": f"font {item.get('size')}px, needs {MIN_FONT}px", "fix": {"size": MIN_FONT}})

    for line in overlay["explanation"]:
        wps = _words_per_sec(line)
        if wps > MAX_WPS:
            need = len(line["text"].split()) / MAX_WPS
            issues.append({"item": line["id"], "type": "too_fast", "axis": "timing",
                           "detail": f"{wps:.1f} words/s, max {MAX_WPS}",
                           "fix": {"end": math.ceil((line["start"] + need) * 100) / 100}})

    lines = sorted(overlay["explanation"], key=lambda l: l["start"])
    for prev, line in zip(lines, lines[1:]):
        if line["start"] < prev["end"]:
            issues.append({"item": line["id"], "type": "overlap", "axis": "timing",
                           "detail": f"starts {line['start']}s while {prev['id']} is up until {prev['end']}s",
                           "fix": {"start": prev["end"]}})

    for event in scene["events"]:
        covered = any(l["start"] < event["end"] and l["end"] > event["start"] for l in overlay["explanation"])
        if not covered:
            issues.append({"item": None, "type": "missed_event", "axis": "coverage",
                           "detail": f"{event['type']} at {event['start']}s is not explained",
                           "fix": {"add_line": {"start": event["start"], "end": event["end"], "text": event["caption"]}}})

    axes = ["accuracy", "readability", "timing", "coverage"]
    scores = {a: max(0.0, 1.0 - 0.25 * sum(i["axis"] == a for i in issues)) for a in axes}
    score = round(sum(scores.values()) / len(axes), 3)
    return {"iteration": overlay["iteration"], "video": rendered, "source": "mock",
            "score": score, "pass": score >= PASS_SCORE, "scores": scores, "issues": issues}
