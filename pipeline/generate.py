"""Even steps — the Gen team (overlay visual effects + explanation).

  step 2  generate(scene)            -> overlay.json
  step 4  improve(overlay, critique) -> overlay.json (next iteration)
          render(video, overlay)     -> overlay.mp4 (what step 3 watches)

Both generate and improve are mocks. Replace the bodies, keep the JSON shapes in contracts/.
"""

import copy
import os
import subprocess
import tempfile

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def generate(scene):
    """Step 2. TODO: LLM/agent drafts effects + script from the scene.

    The mock draft is deliberately rough (short, small labels; one rushed line;
    a label on an untracked player) so the loop has something to fix.
    """
    return {
        "iteration": 0,
        "items": [
            {"id": "o1", "kind": "ring", "track": "p_cross", "start": 5.0, "end": 8.0,
             "text": "Crosser", "size": 28, "color": "cyan"},
            {"id": "o2", "kind": "ring", "track": "p19", "start": 8.0, "end": 8.8,
             "text": "Muniz", "size": 28, "color": "yellow"},
            {"id": "o3", "kind": "ring", "track": "p_def", "start": 8.0, "end": 11.0,
             "text": "Defender", "size": 28, "color": "red"},
            {"id": "o4", "kind": "ring", "track": "ball", "start": 4.0, "end": 11.0,
             "color": "white"},
        ],
        "explanation": [
            {"id": "e1", "start": 5.0, "end": 7.0,
             "text": "Fulham switch it wide and the full-back whips an early cross toward the near post"},
        ],
    }


def improve(overlay, critique):
    """Step 4. TODO: LLM/agent revises the overlay from Cosmos's critique.

    The mock just applies each issue's `fix` hint.
    """
    nxt = copy.deepcopy(overlay)
    nxt["iteration"] = overlay["iteration"] + 1
    by_id = {x["id"]: x for x in nxt["items"] + nxt["explanation"]}
    for issue in critique["issues"]:
        fix = issue.get("fix", {})
        if "add_line" in fix:
            nxt["explanation"].append({"id": f"e{len(nxt['explanation']) + 1}", **fix["add_line"]})
            continue
        target = by_id.get(issue["item"])
        if target is None:
            continue
        if fix.get("drop"):
            nxt["items"] = [i for i in nxt["items"] if i["id"] != target["id"]]
        for key in ("start", "end", "size"):
            if key in fix:
                target[key] = max(target.get(key, 0), fix[key])
    return nxt


# --- render (ffmpeg, no Python deps) ---------------------------------------

STEP = 0.1  # seconds; drawbox has no time variable, so moving boxes are drawn as short static steps


def box_at(keys, t):
    """Linear interpolation of a track's normalized box at time t (held outside the keys)."""
    keys = sorted(keys, key=lambda k: k["t"])
    if t <= keys[0]["t"]:
        return keys[0]["box"]
    for a, b in zip(keys, keys[1:]):
        if t <= b["t"]:
            u = (t - a["t"]) / (b["t"] - a["t"])
            return [va + (vb - va) * u for va, vb in zip(a["box"], b["box"])]
    return keys[-1]["box"]


def render(video, overlay, scene, out):
    tracks = {t["id"]: t for t in scene["tracks"]}
    W, H = scene["size"]
    tmp = tempfile.mkdtemp(prefix="overlay-")
    filters = []

    def textfile(name, text):
        path = os.path.join(tmp, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    for item in overlay["items"]:
        track = tracks.get(item.get("track"))
        if track is None:
            continue  # untracked targets can't be drawn; the critique flags them
        label = textfile(f"{item['id']}.txt", item["text"]) if item.get("text") else None
        t = item["start"]
        while t < item["end"]:
            a, b = t, min(t + STEP, item["end"])
            bx, by, bw, bh = box_at(track["keys"], a)
            x, y, w, h = int((bx - bw * 0.3) * W), int((by - bh * 0.15) * H), int(bw * 1.6 * W), int(bh * 1.3 * H)
            on = f"gte(t,{a:.2f})*lt(t,{b:.2f})"
            filters.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={item['color']}@0.9:t=4:enable='{on}'")
            if label:
                filters.append(f"drawtext=fontfile='{FONT}':textfile='{label}':fontsize={item['size']}:fontcolor={item['color']}"
                               f":borderw=3:bordercolor=black@0.8:x={x + w // 2}-tw/2:y={y}-th-12:enable='{on}'")
            t = b

    for line in overlay["explanation"]:
        path = textfile(f"{line['id']}.txt", line["text"])
        filters.append(f"drawtext=fontfile='{FONT}':textfile='{path}':fontsize=40:fontcolor=white"
                       f":box=1:boxcolor=black@0.6:boxborderw=18:x=(w-tw)/2:y=h-th-70"
                       f":enable='between(t,{line['start']},{line['end']})'")

    cmd = ["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", ",".join(filters) or "null",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "copy", out]
    subprocess.run(cmd, check=True)
    return out
