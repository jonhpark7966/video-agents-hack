"""Even steps — the Gen team.

  generate / draft   scene + one style from prompt_guide.md  -> overlay.json
  improve            previous overlay + critique             -> overlay.json
  render             video + overlay                         -> overlay.mp4

draft and improve call the claude binary (Opus 5.5). render draws the overlay
with ffmpeg: discs, rings, arrows, chips, and banners.
"""

import json
import os
import struct
import subprocess
import zlib

import claude_bin

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
]
COLORS = {"yellow", "white", "cyan", "red", "green", "magenta", "orange", "blue"}
KINDS = {"disc", "ring", "arrow", "chip", "banner"}
KIND_ALIAS = {
    "label": "disc", "marker": "disc", "ellipse": "disc", "circle": "disc",
    "box": "ring", "caption": "banner", "stat": "chip", "text": "banner",
}
DISC_W, DISC_H = 78, 28
RGBA = {
    "yellow": (255, 214, 0, 230),
    "white": (255, 255, 255, 230),
    "cyan": (0, 220, 220, 220),
    "red": (255, 64, 64, 220),
    "green": (40, 210, 90, 220),
    "magenta": (255, 70, 190, 220),
    "orange": (255, 150, 0, 230),
    "blue": (60, 140, 255, 220),
}


def load_guide(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "prompt_guide.md")
    intro, sections, current = [], {}, None
    buf = []
    for line in open(path):
        if line.startswith("## "):
            if current:
                sections[current] = "".join(buf).strip()
            current = line[3:].strip()
            buf = [line]
        elif current:
            buf.append(line)
        else:
            intro.append(line)
    if current:
        sections[current] = "".join(buf).strip()
    blurbs = {}
    for name, body in sections.items():
        lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
        blurbs[name] = lines[0] if lines else name
    return "".join(intro).strip(), sections, blurbs


def _ranks_text(ranks):
    if not ranks:
        return "No human ranks yet."
    lines = []
    if ranks.get("note"):
        lines.append("Human note for the next pass: " + str(ranks["note"]))
    for item in ranks.get("items") or []:
        lines.append(
            f"iter {item.get('iteration')} {item.get('variant')} ({item.get('style')}) "
            f"rank {item.get('rank')} (1 is best)"
        )
    return "\n".join(lines) if lines else "No human ranks yet."


def _overlay_prompt(scene, style, section, intro, ranks, reference_frame, parent, critique):
    tracks = [
        {"id": t["id"], "label": t["label"], "team": t.get("team", ""), "name": t.get("name", ""),
         "keys": t["keys"]}
        for t in scene["tracks"]
    ]
    duration = scene["duration"]
    ref = ""
    if reference_frame and style == "role-marker":
        ref = (
            "\nRead this still of the reference overlay before you answer. "
            "Copy the disc-and-short-label language, not the players:\n"
            f"- reference {reference_frame}\n"
        )
    parent_block = ""
    if parent is not None:
        parent_block = f"""
The previous picked attempt (style {parent.get("style")}) and the critique of it are below.
This new variant must still be style `{style}`, even if the human preferred something else.
Keep timing and track choices the critique said were right. Change the drawing to fit `{style}`.

Previous overlay:
{json.dumps({"style": parent.get("style"), "items": parent.get("items"), "explanation": parent.get("explanation")}, ensure_ascii=True)}

Critique:
{json.dumps({"summary": (critique or {}).get("summary"), "scores": (critique or {}).get("scores"), "issues": (critique or {}).get("issues")}, ensure_ascii=True)}
"""
    return f"""Build one overlay JSON for this soccer clip. Duration is {duration:.2f} seconds.
Every start and end must sit inside 0 to {duration:.2f}.
Use only these track ids: {", ".join(t["id"] for t in tracks)}.

Style for THIS variant only:
{section}

Shared rules:
{intro}

Scene summary: {scene.get("summary", "")}
Events: {json.dumps(scene.get("events", []), ensure_ascii=True)}
Tracks: {json.dumps(tracks, ensure_ascii=True)}
{ref}
Human ranks from the review page (use them as taste, do not switch style):
{_ranks_text(ranks)}
{parent_block}
Return JSON with this shape. Use "" for track, to, or text when that field does not apply. size 0 lets the renderer choose.
{{
  "items": [
    {{"id": "o1", "kind": "disc", "track": "carrier", "to": "", "start": 0.4, "end": 3.0, "text": "Striker", "size": 0, "color": "yellow"}}
  ],
  "explanation": [
    {{"id": "e1", "start": 0.4, "end": 3.0, "text": "Played wide", "place": "bottom", "size": 0}}
  ]
}}
2 to 5 items. explanation may be empty. kind is one of disc, ring, arrow, chip, banner.
place is top or bottom. Words in ASCII.
"""


def draft(scene, style, iteration, *, ranks=None, reference_frame=None, parent=None, critique=None):
    """Ask Claude for one overlay in `style`. Pass parent+critique to revise."""
    intro, sections, _ = load_guide()
    if style not in sections:
        raise KeyError(f"unknown style {style}")
    images = None
    if reference_frame and style == "role-marker" and os.path.exists(reference_frame):
        images = [("reference", reference_frame)]
    prompt = _overlay_prompt(
        scene, style, sections[style], intro, ranks, reference_frame, parent, critique,
    )
    label = f"draft {style}" if parent is None else f"improve {style}"
    data = claude_bin.call_claude(prompt, images=images, effort="low", budget=1.5, label=label)
    return sanitize(data, scene, style=style, iteration=iteration)


def generate(scene):
    """Step 2, single style. The loop calls draft() once per style instead."""
    return draft(scene, "role-marker", 0)


def improve(overlay, critique, scene, style, **kwargs):
    """Step 4. A new variant in `style`, informed by the picked overlay and its critique."""
    iteration = int(overlay.get("iteration", 0)) + 1
    return draft(scene, style, iteration, parent=overlay, critique=critique, **kwargs)


def sanitize(raw, scene, *, style, iteration):
    duration = float(scene["duration"])
    ids = {t["id"] for t in scene["tracks"]}
    items = []
    for i, raw_item in enumerate(raw.get("items") or []):
        if not isinstance(raw_item, dict):
            continue
        kind = str(raw_item.get("kind") or "").lower()
        kind = KIND_ALIAS.get(kind, kind)
        if kind not in KINDS:
            continue
        track = str(raw_item.get("track") or "")
        to = str(raw_item.get("to") or "")
        if kind in ("disc", "ring") and track not in ids:
            continue
        if kind == "arrow" and (track not in ids or to not in ids):
            continue
        start, end = _span(raw_item.get("start"), raw_item.get("end"), duration)
        color = str(raw_item.get("color") or "yellow").lower()
        if color not in COLORS:
            color = "yellow"
        try:
            size = int(raw_item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        items.append({
            "id": str(raw_item.get("id") or f"o{i + 1}"),
            "kind": kind,
            "track": track,
            "to": to,
            "start": start,
            "end": end,
            "text": _clean(raw_item.get("text") or ""),
            "size": max(0, min(size, 96)),
            "color": color,
        })
    lines = []
    for i, raw_line in enumerate(raw.get("explanation") or []):
        if not isinstance(raw_line, dict):
            continue
        text = _clean(raw_line.get("text") or "")
        if not text:
            continue
        start, end = _span(raw_line.get("start"), raw_line.get("end"), duration, min_len=1.2)
        place = "top" if str(raw_line.get("place") or "").lower() == "top" else "bottom"
        try:
            size = int(raw_line.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        lines.append({
            "id": str(raw_line.get("id") or f"e{i + 1}"),
            "start": start,
            "end": end,
            "text": text,
            "place": place,
            "size": max(0, min(size, 96)),
        })
    return {"iteration": iteration, "style": style, "items": items, "explanation": lines}


def _span(start, end, duration, min_len=0.4):
    try:
        start, end = float(start), float(end)
    except (TypeError, ValueError):
        start, end = 0.4, 2.0
    start = min(max(start, 0.0), max(0.0, duration - min_len))
    end = min(max(end, start + min_len), duration)
    return round(start, 2), round(end, 2)


def _clean(text):
    return " ".join(str(text).replace("\n", " ").split())


# --- render -----------------------------------------------------------------

def _font():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RuntimeError("no Arial font found")


def _write_png(path, w, h, rgba):
    r, g, b, a = rgba
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            nx = (x + 0.5 - w / 2) / (w / 2)
            ny = (y + 0.5 - h / 2) / (h / 2)
            if nx * nx + ny * ny <= 1:
                raw.extend((r, g, b, a))
            else:
                raw.extend((0, 0, 0, 0))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(png)


def _disc(cache, color):
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"disc_{color}.png")
    if not os.path.exists(path):
        _write_png(path, DISC_W, DISC_H, RGBA.get(color, RGBA["yellow"]))
    return path


def box_at(keys, t):
    keys = sorted(keys, key=lambda k: k["t"])
    if t <= keys[0]["t"]:
        return keys[0]["box"]
    for a, b in zip(keys, keys[1:]):
        if t <= b["t"]:
            u = (t - a["t"]) / (b["t"] - a["t"]) if b["t"] != a["t"] else 0
            return [va + (vb - va) * u for va, vb in zip(a["box"], b["box"])]
    return keys[-1]["box"]


def _piecewise(keys, fn, clock="t"):
    pts = sorted(keys, key=lambda k: k["t"])
    times = [p["t"] for p in pts]
    vals = [float(fn(p["box"])) for p in pts]
    if len(pts) == 1:
        return f"{vals[0]:.2f}"
    expr = f"{vals[-1]:.2f}"
    for i in range(len(pts) - 2, -1, -1):
        t0, t1 = times[i], times[i + 1]
        v0, v1 = vals[i], vals[i + 1]
        span = t1 - t0
        seg = f"{v0:.2f}" if span < 1e-3 else f"({v0:.2f}+({v1 - v0:.2f})*({clock}-{t0:.3f})/{span:.3f})"
        expr = f"if(lt({clock},{t1:.3f}),{seg},{expr})"
    return f"if(lt({clock},{times[0]:.3f}),{vals[0]:.2f},{expr})"


def _esc(expr):
    return expr.replace("\\", "\\\\").replace(",", r"\,")


def _enable(start, end):
    return _esc(f"between(t,{start:.2f},{end:.2f})")


def _textfile(folder, name, text):
    path = os.path.join(folder, f"{name}.txt")
    with open(path, "w") as handle:
        handle.write(text)
    return path


def render(video, overlay, scene, out):
    tracks = {t["id"]: t for t in scene["tracks"]}
    width, height = scene["size"]
    font = _font()
    work = os.path.join(os.path.dirname(os.path.abspath(out)), "render")
    os.makedirs(work, exist_ok=True)
    discs = []
    chains = []
    last = "0:v"
    step = 0

    def video_filter(body):
        nonlocal last, step
        dest = f"v{step}"
        chains.append(f"[{last}]{body}[{dest}]")
        last = dest
        step += 1

    def overlay_filter(body):
        nonlocal last, step
        dest = f"v{step}"
        chains.append(f"[{last}][{len(discs)}:v]{body}[{dest}]")
        last = dest
        step += 1

    for item in overlay.get("items", []):
        track = tracks.get(item.get("track"))
        enable = _enable(item["start"], item["end"])
        kind = item["kind"]
        color = item["color"]
        if kind == "disc" and track:
            discs.append(_disc(work, color))
            x = _piecewise(track["keys"], lambda b, w=width: (b[0] + b[2] / 2) * w - DISC_W / 2)
            y = _piecewise(track["keys"], lambda b, h=height: (b[1] + b[3]) * h - DISC_H / 2)
            overlay_filter(
                f"overlay=x='{_esc(x)}':y='{_esc(y)}':enable='{enable}':format=auto:eof_action=repeat"
            )
        elif kind == "ring" and track:
            # drawbox names its thickness option `t`, which hides the timestamp.
            # Step the box from key to key instead of writing a time expression.
            keys = sorted(track["keys"], key=lambda key: key["t"])
            spans = list(zip(keys, keys[1:])) or [(keys[0], {"t": item["end"], "box": keys[0]["box"]})]
            for a, b in spans:
                start = max(item["start"], a["t"])
                end = min(item["end"], b["t"])
                if end - start < 0.04:
                    continue
                box = a["box"]
                x = int(max(0, box[0] * width - 6))
                y = int(max(0, box[1] * height - 6))
                bw = int(min(max(36, box[2] * width + 12), width * 0.25))
                bh = int(min(max(56, box[3] * height + 12), height * 0.3))
                video_filter(
                    f"drawbox=x={x}:y={y}:w={bw}:h={bh}:color={color}@0.95:"
                    f"thickness=4:enable='{_enable(start, end)}'"
                )
        elif kind == "arrow" and track and tracks.get(item.get("to")):
            mid = (item["start"] + item["end"]) / 2
            x0, y0 = _feet(track, mid, width, height)
            x1, y1 = _feet(tracks[item["to"]], mid, width, height)
            for i in range(12):
                u = i / 11
                x = int(x0 + (x1 - x0) * u)
                y = int(y0 + (y1 - y0) * u)
                side = 14 if i >= 10 else 8
                video_filter(
                    f"drawbox=x={x - side // 2}:y={y - side // 2}:w={side}:h={side}:"
                    f"color={color}@0.95:thickness=fill:enable='{enable}'"
                )

    chip_i = 0
    banner_i = 0
    for item in overlay.get("items", []):
        if not item.get("text"):
            continue
        track = tracks.get(item.get("track"))
        enable = _enable(item["start"], item["end"])
        path = _textfile(work, item["id"], item["text"])
        size = item["size"] or (64 if item["kind"] == "banner" else 34 if item["kind"] == "chip" else 32)
        common = (
            f"drawtext=fontfile='{font}':textfile='{path}':fontsize={size}:fontcolor=white:"
            f"borderw=3:bordercolor=black@0.85:enable='{enable}'"
        )
        if item["kind"] in ("disc", "ring") and track:
            x = _piecewise(track["keys"], lambda b, w=width: (b[0] + b[2] / 2) * w)
            y = _piecewise(track["keys"], lambda b, h=height: max(8, b[1] * h - size - 6))
            video_filter(f"{common}:x='{_esc(x)}-tw/2':y='{_esc(y)}'")
        elif item["kind"] == "chip":
            y = 78 + chip_i * (size + 22)
            chip_i += 1
            video_filter(
                f"{common}:box=1:boxcolor=black@0.55:boxborderw=12:x=w-tw-48:y={y}"
            )
        elif item["kind"] == "banner":
            y = 36 + banner_i * (size + 16)
            banner_i += 1
            video_filter(f"{common}:x=(w-tw)/2:y={y}")

    for line in overlay.get("explanation", []):
        path = _textfile(work, line["id"], line["text"])
        size = line.get("size") or (58 if line.get("place") == "top" else 36)
        enable = _enable(line["start"], line["end"])
        y = "96" if line.get("place") == "top" else "h-th-56"
        video_filter(
            f"drawtext=fontfile='{font}':textfile='{path}':fontsize={size}:fontcolor=white:"
            f"box=1:boxcolor=black@0.55:boxborderw=14:borderw=2:bordercolor=black:"
            f"x=(w-tw)/2:y={y}:enable='{enable}'"
        )

    cmd = ["ffmpeg", "-y", "-i", video]
    for path in discs:
        cmd += ["-loop", "1", "-i", path]
    if chains:
        video_filter("format=yuv420p")
        cmd += ["-filter_complex", ";".join(chains), "-map", f"[{last}]"]
    else:
        cmd += ["-map", "0:v"]
    cmd += ["-map", "0:a?", "-shortest", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "")[-800:])
    return out


def _feet(track, t, width, height):
    bx, by, bw, bh = box_at(track["keys"], t)
    return (bx + bw / 2) * width, (by + bh) * height
