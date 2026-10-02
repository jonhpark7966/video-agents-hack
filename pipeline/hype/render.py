"""Render a hype edit of a soccer clip from an edit spec.

  python render.py edit.json out.mp4 [--preview T1,T2,...  sheet.jpg]

The spec (written by Claude after reading the frames) holds:

  timeline   source segments with speed (or a speed ramp), freezes, a replay
  points     named player tracks, [t, x, y] keys in source time (normalized)
  camera     zoom / focus keyframes; focus can be "ball", a point name or [x, y]
  shake      camera shake hits
  fx         overlays: ball_trail, ball_ring, spotlight, shockwave, tag, text,
             flash, speed_lines, letterbox, chroma, zoom_blur, confetti, tint, badge
  sfx        synthesized sounds (see sfx.py) and a beat bed
  grade      contrast / saturation / vignette

Times. A plain number is a source time inside the main pass. A dict
{"at": src, "tag": "replay", "plus": 0.2} picks a pass and adds output seconds.
{"out": 12.3} is an output time. Animated effects (text, shockwaves, flashes)
run on the output clock from that moment, so they keep their speed inside
slow motion; world effects (trails) follow the source clock.
"""

import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sfx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONTS = {
    "impact": ("/System/Library/Fonts/Supplemental/Futura.ttc", 4),   # Condensed ExtraBold
    "bold": ("/System/Library/Fonts/Supplemental/Futura.ttc", 2),     # Bold
    "heavy": ("/System/Library/Fonts/HelveticaNeue.ttc", 9),          # Condensed Black
    "plain": ("/System/Library/Fonts/Helvetica.ttc", 1),
}
COLORS = {
    "yellow": (255, 222, 0), "white": (255, 255, 255), "cyan": (0, 230, 255),
    "red": (255, 40, 60), "green": (60, 255, 120), "magenta": (255, 0, 200),
    "orange": (255, 140, 0), "blue": (40, 110, 255), "black": (0, 0, 0),
    "gold": (255, 196, 40), "pink": (255, 80, 170), "lime": (190, 255, 0),
}


def rgb(c):
    if isinstance(c, str):
        return COLORS[c]
    return tuple(int(v) for v in c)


def bgr(c):
    r, g, b = rgb(c)
    return (b, g, r)


def ease(u, kind="inout"):
    u = min(1.0, max(0.0, u))
    if kind == "in":
        return u * u * u
    if kind == "out":
        return 1 - (1 - u) ** 3
    if kind == "back":
        s = 1.70158 * 1.5
        u -= 1
        return u * u * ((s + 1) * u + s) + 1
    if kind == "elastic":
        if u in (0, 1):
            return u
        return 2 ** (-10 * u) * math.sin((u * 10 - 0.75) * (2 * math.pi) / 3) + 1
    if kind == "linear":
        return u
    return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


# ---------------------------------------------------------------- timeline

class Timeline:
    """Maps output time to source time across speed segments, ramps and freezes."""

    def __init__(self, segments, src_duration):
        self.segs = []
        t = 0.0
        for seg in segments:
            tag = seg.get("tag", "main")
            if "freeze" in seg:
                d = float(seg["dur"])
                self.segs.append({"kind": "freeze", "src": float(seg["freeze"]), "t0": t, "t1": t + d, "tag": tag})
                t += d
                continue
            a, b = float(seg["src"][0]), min(float(seg["src"][1]), src_duration)
            speed = seg.get("speed", 1.0)
            v0, v1 = (speed, speed) if not isinstance(speed, list) else speed
            d = 2 * (b - a) / (v0 + v1)
            self.segs.append({"kind": "play", "a": a, "b": b, "v0": v0, "v1": v1, "t0": t, "t1": t + d, "tag": tag,
                              "reverse": bool(seg.get("reverse"))})
            t += d
        self.duration = t

    def at(self, t):
        """(src_time, seg, local) for an output time."""
        for seg in self.segs:
            if t < seg["t1"] or seg is self.segs[-1]:
                local = min(max(0.0, t - seg["t0"]), seg["t1"] - seg["t0"])
                if seg["kind"] == "freeze":
                    return seg["src"], seg, local
                d = seg["t1"] - seg["t0"]
                prog = seg["v0"] * local + (seg["v1"] - seg["v0"]) * local * local / (2 * d)
                src = seg["b"] - prog if seg.get("reverse") else seg["a"] + prog
                return src, seg, local
        raise ValueError(t)

    def speed_at(self, t):
        _, seg, local = self.at(t)
        if seg["kind"] == "freeze":
            return 0.0
        d = seg["t1"] - seg["t0"]
        return seg["v0"] + (seg["v1"] - seg["v0"]) * local / d

    def to_out(self, src, tag="main"):
        """First output time where pass `tag` shows source time `src`."""
        for seg in self.segs:
            if seg["tag"] != tag:
                continue
            if seg["kind"] == "freeze":
                if abs(seg["src"] - src) < 1e-3:
                    return seg["t0"]
                continue
            if seg.get("reverse"):
                if seg["a"] <= src <= seg["b"]:
                    return seg["t0"] + (seg["b"] - src) / seg["v0"]
                continue
            if seg["a"] - 1e-6 <= src <= seg["b"] + 1e-6:
                d = seg["t1"] - seg["t0"]
                k = (seg["v1"] - seg["v0"]) / (2 * d)
                if abs(k) < 1e-9:
                    return seg["t0"] + (src - seg["a"]) / seg["v0"]
                # k*l^2 + v0*l - (src-a) = 0
                disc = seg["v0"] ** 2 + 4 * k * (src - seg["a"])
                local = (-seg["v0"] + math.sqrt(max(0.0, disc))) / (2 * k)
                return seg["t0"] + local
        return None

    def resolve(self, spec):
        if spec is None:
            return None
        if isinstance(spec, (int, float)):
            return self.to_out(float(spec))
        if "out" in spec:
            return float(spec["out"]) + float(spec.get("plus", 0))
        base = self.to_out(float(spec["at"]), spec.get("tag", "main"))
        if base is None:
            return None
        return base + float(spec.get("plus", 0))


# ---------------------------------------------------------------- source frames

class Source:
    def __init__(self, video, scale=1.0):
        cap = cv2.VideoCapture(video)
        self.fps = cap.get(cv2.CAP_PROP_FPS)
        self.frames = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if scale != 1.0:
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            self.frames.append(frame)
        cap.release()
        self.h, self.w = self.frames[0].shape[:2]
        self.duration = len(self.frames) / self.fps
        self._flow = {}
        self._dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)

    def _flows(self, i):
        if i not in self._flow:
            a = cv2.cvtColor(cv2.resize(self.frames[i], None, fx=0.5, fy=0.5), cv2.COLOR_BGR2GRAY)
            b = cv2.cvtColor(cv2.resize(self.frames[i + 1], None, fx=0.5, fy=0.5), cv2.COLOR_BGR2GRAY)
            fw = self._dis.calc(a, b, None)
            bw = self._dis.calc(b, a, None)
            fw = cv2.resize(fw, (self.w, self.h)) * 2
            bw = cv2.resize(bw, (self.w, self.h)) * 2
            self._flow[i] = (fw, bw)
            for k in list(self._flow):
                if k < i - 2:
                    del self._flow[k]
        return self._flow[i]

    def get(self, src_t, interp="flow"):
        pos = src_t * self.fps
        i = int(math.floor(pos))
        a = pos - i
        last = len(self.frames) - 1
        if i >= last:
            return self.frames[last].copy()
        i = max(0, i)
        if a < 0.04 or interp == "nearest":
            return self.frames[i].copy()
        if a > 0.96:
            return self.frames[i + 1].copy()
        if interp == "blend":
            return cv2.addWeighted(self.frames[i], 1 - a, self.frames[i + 1], a, 0)
        fw, bw = self._flows(i)
        gx, gy = np.meshgrid(np.arange(self.w, dtype=np.float32), np.arange(self.h, dtype=np.float32))
        w0 = cv2.remap(self.frames[i], gx - a * fw[..., 0], gy - a * fw[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        w1 = cv2.remap(self.frames[i + 1], gx - (1 - a) * bw[..., 0], gy - (1 - a) * bw[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return cv2.addWeighted(w0, 1 - a, w1, a, 0)


# ---------------------------------------------------------------- tracks

class Tracks:
    def __init__(self, ball_track, points):
        self.ball = ball_track["frames"]
        self.fps = ball_track["fps"]
        self.points = {name: sorted(keys) for name, keys in (points or {}).items()}

    def ball_at(self, t):
        f = t * self.fps
        i = int(math.floor(f))
        i = max(0, min(len(self.ball) - 2, i))
        a = min(1.0, max(0.0, f - i))
        p, q = self.ball[i], self.ball[i + 1]
        x = p["sx"] + (q["sx"] - p["sx"]) * a
        y = p["sy"] + (q["sy"] - p["sy"]) * a
        return (x, y), (p["visible"] and q["visible"])

    def point_at(self, name, t):
        if name == "ball":
            return self.ball_at(t)[0]
        keys = self.points[name]
        if t <= keys[0][0]:
            return keys[0][1], keys[0][2]
        for a, b in zip(keys, keys[1:]):
            if a[0] <= t <= b[0]:
                u = (t - a[0]) / max(1e-6, b[0] - a[0])
                return a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u
        return keys[-1][1], keys[-1][2]

    def span(self, name):
        if name == "ball":
            return 0, 1e9
        keys = self.points[name]
        return keys[0][0], keys[-1][0]

    def resolve(self, ref, t):
        if isinstance(ref, (list, tuple)):
            return float(ref[0]), float(ref[1])
        return self.point_at(ref, t)


# ---------------------------------------------------------------- text

_font_cache = {}
_text_cache = {}


def font(style, size):
    key = (style, size)
    if key not in _font_cache:
        path, index = FONTS.get(style, FONTS["impact"])
        _font_cache[key] = ImageFont.truetype(path, size, index=index)
    return _font_cache[key]


def text_sprite(text, size, fill, fill2=None, stroke="black", stroke_w=None, style="impact",
                shadow=True, italic=0.18, glow=None):
    """RGBA numpy sprite of a big stylized word."""
    key = (text, size, str(fill), str(fill2), str(stroke), stroke_w, style, shadow, italic, str(glow))
    if key in _text_cache:
        return _text_cache[key]
    f = font(style, size)
    sw = stroke_w if stroke_w is not None else max(3, size // 14)
    lines = text.split("\n")
    boxes = [f.getbbox(line, stroke_width=sw) for line in lines]
    lw = max(b[2] - b[0] for b in boxes)
    lh = [b[3] - b[1] for b in boxes]
    gap = int(size * 0.08)
    pad = sw * 2 + int(size * 0.35)
    W = lw + 2 * pad + int(abs(italic) * size * 1.2)
    H = sum(lh) + gap * (len(lines) - 1) + 2 * pad
    mask = Image.new("L", (W, H), 0)
    smask = Image.new("L", (W, H), 0)
    dm = ImageDraw.Draw(mask)
    ds = ImageDraw.Draw(smask)
    y = pad
    for line, box, h in zip(lines, boxes, lh):
        w = box[2] - box[0]
        x = (W - w) // 2 - box[0]
        ds.text((x, y - box[1]), line, font=f, fill=255, stroke_width=sw, stroke_fill=255)
        dm.text((x, y - box[1]), line, font=f, fill=255)
        y += h + gap
    fillm = np.array(mask, np.float32) / 255
    strokem = np.array(smask, np.float32) / 255
    top = np.array(rgb(fill), np.float32)
    bot = np.array(rgb(fill2 or fill), np.float32)
    grad = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    fillc = top * (1 - grad) + bot * grad
    fillc = np.broadcast_to(fillc, (H, W, 3))
    # highlight band for a glossy sports look
    band = np.clip(1 - np.abs(np.linspace(-1, 1, H) + 0.35) * 3.5, 0, 1)[:, None, None] * 0.25
    fillc = np.clip(fillc + band * 255, 0, 255)
    sc = np.array(rgb(stroke), np.float32)
    out = np.zeros((H, W, 4), np.float32)
    out[..., :3] = sc * (strokem[..., None] - fillm[..., None]).clip(0, 1) + fillc * fillm[..., None]
    out[..., 3] = np.maximum(strokem, fillm)
    if shadow:
        sh = cv2.GaussianBlur(strokem, (0, 0), size / 18)
        off = max(4, size // 14)
        sh = np.roll(np.roll(sh, off, 0), off, 1) * 0.75
        a = out[..., 3]
        comp_a = a + sh * (1 - a)
        rgbv = out[..., :3] * a[..., None] / np.maximum(comp_a[..., None], 1e-4)
        out[..., :3] = rgbv
        out[..., 3] = comp_a
    if glow:
        g = cv2.GaussianBlur(strokem, (0, 0), size / 7) * 0.9
        gc = np.array(rgb(glow), np.float32)
        a = out[..., 3]
        comp_a = a + g * (1 - a)
        out[..., :3] = (out[..., :3] * a[..., None] + gc * (g * (1 - a))[..., None]) / np.maximum(comp_a[..., None], 1e-4)
        out[..., 3] = comp_a
    if italic:
        M = np.float32([[1, -italic, italic * H / 2], [0, 1, 0]])
        out = cv2.warpAffine(out, M, (W, H), flags=cv2.INTER_LINEAR)
    _text_cache[key] = out
    return out


def paste_sprite(frame, sprite, cx, cy, scale=1.0, angle=0.0, alpha=1.0):
    """Alpha-composite an RGBA float sprite (RGB order) onto a BGR uint8 frame."""
    if alpha <= 0.01 or scale <= 0.01:
        return
    h, w = sprite.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    M[0, 2] += cx - w / 2
    M[1, 2] += cy - h / 2
    H, W = frame.shape[:2]
    corners = np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]], np.float32) @ M.T
    x0 = int(max(0, math.floor(corners[:, 0].min())))
    y0 = int(max(0, math.floor(corners[:, 1].min())))
    x1 = int(min(W, math.ceil(corners[:, 0].max())))
    y1 = int(min(H, math.ceil(corners[:, 1].max())))
    if x1 <= x0 or y1 <= y0:
        return
    M2 = M.copy()
    M2[0, 2] -= x0
    M2[1, 2] -= y0
    warped = cv2.warpAffine(sprite, M2, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    a = (warped[..., 3:4] * alpha).clip(0, 1)
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    col = warped[..., 2::-1]  # RGB -> BGR
    frame[y0:y1, x0:x1] = (roi * (1 - a) + col * a).clip(0, 255).astype(np.uint8)


# ---------------------------------------------------------------- renderer

class Renderer:
    def __init__(self, spec, base_dir):
        self.spec = spec
        self.base = base_dir
        video = spec["video"] if os.path.isabs(spec["video"]) else os.path.join(ROOT, spec["video"])
        self.video = video
        self.src = Source(video)
        with open(os.path.join(base_dir, spec.get("ball_track", "track.json"))) as handle:
            ball = json.load(handle)
        self.tracks = Tracks(ball, spec.get("points"))
        self.tl = Timeline(spec["timeline"], self.src.duration)
        out = spec.get("output", {})
        self.fps = float(out.get("fps", 30))
        self.W, self.H = out.get("size", [self.src.w, self.src.h])
        self.n_frames = int(round(self.tl.duration * self.fps))
        self.fx = []
        for fx in spec.get("fx", []):
            fx = dict(fx)
            for key in ("at", "start", "end"):
                if key in fx:
                    fx["_" + key] = self.tl.resolve(fx[key])
            self.fx.append(fx)
        self._prep_camera()
        yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
        r = np.sqrt(((xx - self.W / 2) / (self.W / 2)) ** 2 + ((yy - self.H / 2) / (self.H / 2)) ** 2)
        self.vig = np.clip(1 - (r - 0.55) * 0.9, 0, 1)[..., None].astype(np.float32)
        rng = np.random.default_rng(3)
        self.rng = rng
        self.lines = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.55, 1.0), rng.uniform(0.05, 0.22), rng.integers(1, 4)) for _ in range(90)]
        self.confetti = [
            (rng.uniform(0, 1), rng.uniform(-0.6, 0), rng.uniform(0.25, 0.6), rng.uniform(-0.08, 0.08),
             rng.uniform(0, 360), rng.uniform(-500, 500), rng.integers(0, 7), rng.uniform(8, 18))
            for _ in range(240)
        ]

    # ---- camera
    def _prep_camera(self):
        keys = []
        for k in self.spec.get("camera", []):
            t = self.tl.resolve(k["t"])
            if t is not None:
                keys.append((t, k))
        keys.sort(key=lambda kv: kv[0])
        if not keys:
            keys = [(0.0, {"zoom": 1.0, "focus": [0.5, 0.5]})]
        self.cam_keys = keys
        # per-frame focus, smoothed
        zooms, fxs, fys, cuts, rots = [], [], [], [], []
        prev = None
        for n in range(self.n_frames):
            t = n / self.fps
            src_t, seg, _ = self.tl.at(t)
            z, f = self._cam_raw(t, src_t)
            z *= self._bump(t)
            rots.append(self._rot)
            zooms.append(z)
            fxs.append(f[0])
            fys.append(f[1])
            cuts.append(prev is not None and abs(src_t - prev) > 0.25)
            prev = src_t
        alpha = self.spec.get("camera_smooth", 0.18)
        sx, sy = [fxs[0]], [fys[0]]
        for x, y, cut in zip(fxs[1:], fys[1:], cuts[1:]):
            k = 1.0 if cut else alpha
            sx.append(sx[-1] + (x - sx[-1]) * k)
            sy.append(sy[-1] + (y - sy[-1]) * k)
        self.cam = list(zip(zooms, sx, sy, rots))

    def _bump(self, t):
        """Zoom punches on the kick drum of the beat bed."""
        k = 1.0
        for b in self.spec.get("beat_bump", []):
            t0 = self.tl.resolve(b["start"])
            t1 = self.tl.resolve(b["end"])
            if t0 is None or t1 is None or not (t0 <= t <= t1 + 0.3):
                continue
            step = 60 / b.get("bpm", 140) / 4
            bar = step * 16
            rel = t - t0
            best = None
            for kick in (0, 7, 10):
                kt = math.floor((rel - kick * step) / bar) * bar + kick * step
                if kt < 0 or t0 + kt > t1:
                    continue
                dt = rel - kt
                if dt >= 0 and (best is None or dt < best):
                    best = dt
            if best is not None:
                k *= 1 + b.get("amount", 0.04) * math.exp(-best * 14)
        return k

    def _focus(self, ref, src_t):
        if ref is None:
            return 0.5, 0.5
        return self.tracks.resolve(ref, src_t)

    def _cam_raw(self, t, src_t):
        keys = self.cam_keys
        self._rot = keys[0][1].get("rot", 0.0) if t <= keys[0][0] else keys[-1][1].get("rot", 0.0)
        if t <= keys[0][0]:
            k = keys[0][1]
            return k.get("zoom", 1.0), self._focus(k.get("focus"), src_t)
        for (ta, a), (tb, b) in zip(keys, keys[1:]):
            if ta <= t <= tb:
                u = ease((t - ta) / max(1e-6, tb - ta), b.get("ease", "inout"))
                za, zb = a.get("zoom", 1.0), b.get("zoom", 1.0)
                fa = self._focus(a.get("focus"), src_t)
                fb = self._focus(b.get("focus"), src_t)
                self._rot = a.get("rot", 0.0) + (b.get("rot", 0.0) - a.get("rot", 0.0)) * u
                return za + (zb - za) * u, (fa[0] + (fb[0] - fa[0]) * u, fa[1] + (fb[1] - fa[1]) * u)
        k = keys[-1][1]
        return k.get("zoom", 1.0), self._focus(k.get("focus"), src_t)

    def _shake(self, t):
        dx = dy = rot = 0.0
        for s in self.spec.get("shake", []):
            t0 = self.tl.resolve(s["t"])
            if t0 is None:
                continue
            u = t - t0
            dur = s.get("dur", 0.5)
            if 0 <= u <= dur:
                k = (1 - u / dur) ** 2 * s.get("amp", 14)
                f = s.get("freq", 32)
                dx += k * math.sin(u * f * 2.1 + 1.3)
                dy += k * math.cos(u * f * 1.7 + 0.4)
                rot += k * 0.08 * math.sin(u * f * 1.3)
        return dx, dy, rot

    def _cam_matrix(self, n, t):
        z, fx, fy, crot = self.cam[n]
        z = max(1.0, z)
        sw, sh = self.src.w, self.src.h
        cx = min(max(fx * sw, sw / (2 * z)), sw - sw / (2 * z))
        cy = min(max(fy * sh, sh / (2 * z)), sh - sh / (2 * z))
        dx, dy, rot = self._shake(t)
        scale = z * self.W / sw
        M = cv2.getRotationMatrix2D((cx, cy), rot + crot, scale)
        M[0, 2] += self.W / 2 - cx + dx
        M[1, 2] += self.H / 2 - cy + dy
        return M, z

    # ---- helpers
    def active(self, fx, t, src_t, tag):
        tags = fx.get("tags", ["main"])
        if tags != "all" and tag not in tags:
            return None
        if "_at" in fx:
            t0 = fx["_at"]
            if t0 is None:
                return None
            dur = fx.get("dur", 1.0)
            if t0 <= t <= t0 + dur:
                return (t - t0) / dur
            return None
        if "src" in fx:
            a, b = fx["src"]
            if a <= src_t <= b:
                return (src_t - a) / max(1e-6, b - a)
            return None
        s, e = fx.get("_start"), fx.get("_end")
        if s is not None and e is not None and s <= t <= e:
            return (t - s) / max(1e-6, e - s)
        return None

    def _fade(self, fx, u):
        dur = fx.get("dur") or 1.0
        fi = fx.get("fade", 0.12) / dur
        return min(1.0, u / max(fi, 1e-4), (1 - u) / max(fi, 1e-4))

    # ---- world-space overlays (drawn on the source frame, then the camera moves them)
    def world(self, frame, t, src_t, tag):
        self._pending_labels = []
        h, w = frame.shape[:2]
        glow = np.zeros((h // 2, w // 2, 3), np.float32)
        core = np.zeros_like(frame)
        core_mask = np.zeros((h, w), np.uint8)
        dim = None
        for fx in self.fx:
            u = self.active(fx, t, src_t, tag)
            if u is None:
                continue
            kind = fx["kind"]
            if kind == "spotlight":
                cx, cy = self.tracks.resolve(fx.get("target", "ball"), src_t)
                if fx.get("offset"):
                    cx += fx["offset"][0]
                    cy += fx["offset"][1]
                r = fx.get("radius", 0.09)
                amt = fx.get("amount", 0.55) * min(1.0, self._fade(fx, u) if "_at" in fx else 1.0)
                if "src" in fx:
                    a, b = fx["src"]
                    span = max(1e-6, b - a)
                    edge = fx.get("fade_src", 0.25) / span
                    amt *= min(1.0, u / max(edge, 1e-4), (1 - u) / max(edge, 1e-4))
                small = (w // 8, h // 8)
                yy, xx = np.mgrid[0:small[1], 0:small[0]].astype(np.float32)
                d = np.sqrt(((xx / small[0] - cx)) ** 2 + ((yy / small[1] - cy) * h / w) ** 2)
                m = np.clip((d - r) / (r * 1.2), 0, 1)
                m = cv2.resize(m, (w, h))[..., None]
                dim = (1 - amt * m) if dim is None else dim * (1 - amt * m)
            elif kind == "ball_trail":
                self._trail(fx, glow, core, core_mask, src_t, w, h)
            elif kind == "ball_ring":
                (bx, by), vis = self.tracks.ball_at(src_t)
                if not vis and not fx.get("always"):
                    continue
                pulse = 1 + 0.18 * math.sin(t * 2 * math.pi * fx.get("hz", 2.5))
                r = int(fx.get("radius", 20) * pulse)
                c = bgr(fx.get("color", "yellow"))
                p = (int(bx * w), int(by * h))
                cv2.circle(core, p, r, c, 3, cv2.LINE_AA)
                cv2.circle(core_mask, p, r, 255, 3, cv2.LINE_AA)
                cv2.circle(glow, (p[0] // 2, p[1] // 2), r // 2, tuple(v / 255 * fx.get("glow", 0.6) for v in c), 2, cv2.LINE_AA)
            elif kind == "tag":
                self._tag(fx, frame, core, core_mask, glow, t, src_t, u, w, h)
        if dim is not None:
            frame[:] = (frame.astype(np.float32) * dim).astype(np.uint8)
        g = cv2.GaussianBlur(glow, (0, 0), 7)
        g = cv2.resize(g, (w, h))
        out = frame.astype(np.float32) + g * 255 * 1.4
        m = core_mask.astype(np.float32)[..., None] / 255
        out = out * (1 - m) + core.astype(np.float32) * m
        frame[:] = out.clip(0, 255).astype(np.uint8)

    def _trail(self, fx, glow, core, core_mask, src_t, w, h):
        length = fx.get("length", 0.5)
        steps = 28
        pts = []
        for k in range(steps + 1):
            ts = src_t - length * (1 - k / steps)
            (x, y), vis = self.tracks.ball_at(max(0.0, ts))
            if "src" in fx and ts < fx["src"][0]:
                continue
            if vis:
                pts.append((x * w, y * h, k / steps))
            else:
                pts = []
        if len(pts) < 2:
            return
        palette = fx.get("palette", "fire")
        width = fx.get("width", 14)
        for (x0, y0, a0), (x1, y1, a1) in zip(pts, pts[1:]):
            c = self._trail_color(palette, a1)
            th = max(1, int(width * a1 ** 1.3))
            cv2.line(glow, (int(x0 / 2), int(y0 / 2)), (int(x1 / 2), int(y1 / 2)), tuple(v / 255 for v in c), max(1, th), cv2.LINE_AA)
            core_th = max(1, int(th * 0.45))
            cv2.line(core, (int(x0), int(y0)), (int(x1), int(y1)), self._trail_color(palette, min(1, a1 + 0.3), core=True), core_th, cv2.LINE_AA)
            cv2.line(core_mask, (int(x0), int(y0)), (int(x1), int(y1)), int(255 * min(1, a1 * 1.5)), core_th, cv2.LINE_AA)
        hx, hy, _ = pts[-1]
        head = fx.get("head", 9)
        if head > 0:
            cv2.circle(glow, (int(hx / 2), int(hy / 2)), head, tuple(v / 255 for v in self._trail_color(palette, 1)), -1, cv2.LINE_AA)
        sparks = fx.get("sparks", 0)
        if sparks:
            rng = np.random.default_rng(int(src_t * 1000))
            for _ in range(sparks):
                x0, y0, a0 = pts[int(rng.integers(0, len(pts)))]
                ang = rng.uniform(0, 2 * math.pi)
                dist = rng.uniform(4, 40) * (1.2 - a0)
                px, py = x0 + math.cos(ang) * dist, y0 + math.sin(ang) * dist * 0.7
                c = self._trail_color(palette, rng.uniform(0.5, 1.0), core=True)
                r = int(rng.integers(1, 4))
                cv2.circle(core, (int(px), int(py)), r, c, -1, cv2.LINE_AA)
                cv2.circle(core_mask, (int(px), int(py)), r, 255, -1, cv2.LINE_AA)
                cv2.circle(glow, (int(px / 2), int(py / 2)), r + 1, tuple(v / 255 for v in c), -1, cv2.LINE_AA)

    @staticmethod
    def _trail_color(palette, a, core=False):
        # returns BGR
        if palette == "fire":
            stops = [(0.0, (60, 0, 160)), (0.4, (0, 60, 255)), (0.75, (0, 170, 255)), (1.0, (180, 245, 255))]
        elif palette == "ice":
            stops = [(0.0, (120, 30, 20)), (0.5, (255, 160, 0)), (1.0, (255, 255, 220))]
        elif palette == "neon":
            stops = [(0.0, (200, 0, 160)), (0.5, (255, 60, 255)), (1.0, (255, 230, 255))]
        else:
            stops = [(0.0, (0, 140, 255)), (1.0, (0, 230, 255))]
        if core:
            a = min(1.0, a + 0.2)
        for (pa, ca), (pb, cb) in zip(stops, stops[1:]):
            if pa <= a <= pb:
                u = (a - pa) / (pb - pa)
                return tuple(int(ca[i] + (cb[i] - ca[i]) * u) for i in range(3))
        return stops[-1][1]

    def _tag(self, fx, frame, core, core_mask, glow, t, src_t, u, w, h):
        """A ring under a player plus a floating label chip."""
        x, y = self.tracks.resolve(fx["target"], src_t)
        if fx.get("offset"):
            x += fx["offset"][0]
            y += fx["offset"][1]
        c = bgr(fx.get("color", "yellow"))
        grow = ease(min(1.0, u * 6), "back") if "_at" in fx else 1.0
        rx = int(fx.get("rx", 34) * grow)
        ry = int(fx.get("ry", 12) * grow)
        p = (int(x * w), int(y * h))
        spin = t * 180
        if rx > 1 and ry > 0:
            cv2.ellipse(core, p, (rx, ry), 0, spin, spin + 300, c, 3, cv2.LINE_AA)
            cv2.ellipse(core_mask, p, (rx, ry), 0, spin, spin + 300, 255, 3, cv2.LINE_AA)
            cv2.ellipse(glow, (p[0] // 2, p[1] // 2), (rx // 2, ry // 2), 0, 0, 360, tuple(v / 255 for v in c), 3, cv2.LINE_AA)
        if fx.get("chevron", True):
            bob = int(6 * math.sin(t * 6))
            top = p[1] - int(fx.get("height", 0.085) * h) - 26 + bob
            pts = np.array([[p[0] - 13, top], [p[0] + 13, top], [p[0], top + 16]], np.int32)
            cv2.fillPoly(core, [pts], c, cv2.LINE_AA)
            cv2.fillPoly(core_mask, [pts], 255, cv2.LINE_AA)
            if fx.get("label"):
                self._pending_labels.append((fx, p[0], top - 10))

    # ---- screen-space overlays
    def screen(self, frame, t, src_t, tag, zoom):
        H, W = frame.shape[:2]
        M = self._cur_M
        for fx, wx, wy in self._pending_labels:
            px = M[0, 0] * wx + M[0, 1] * wy + M[0, 2]
            py = M[1, 0] * wx + M[1, 1] * wy + M[1, 2]
            spr = text_sprite(fx["label"], fx.get("label_size", 54), fx.get("label_color", "white"),
                              None, "black", None, "impact", True, 0.12, fx.get("color", "yellow"))
            paste_sprite(frame, spr, px, py - spr.shape[0] * 0.3, 1.0, 0, 1.0)
        for fx in self.fx:
            u = self.active(fx, t, src_t, tag)
            if u is None:
                continue
            kind = fx["kind"]
            if kind == "shockwave":
                self._shockwave(frame, fx, u, t)
            elif kind == "flash":
                a = fx.get("amount", 0.85) * (1 - u) ** 2
                col = np.array(bgr(fx.get("color", "white")), np.float32)
                frame[:] = (frame.astype(np.float32) * (1 - a) + col * a).astype(np.uint8)
            elif kind == "speed_lines":
                self._speed_lines(frame, fx, t, u)
            elif kind == "letterbox":
                k = fx.get("ratio", 0.11)
                fade = fx.get("ease", 0.08)
                dur = fx.get("_end", 0) - fx.get("_start", 0) if "_start" in fx else fx.get("dur", 1)
                e = min(1.0, u * dur / fade, (1 - u) * dur / fade)
                bar = int(H * k * ease(e))
                if bar > 0:
                    frame[:bar] = (frame[:bar] * 0.05).astype(np.uint8)
                    frame[H - bar:] = (frame[H - bar:] * 0.05).astype(np.uint8)
            elif kind == "chroma":
                k = int(fx.get("px", 12) * (1 - u) ** 1.5)
                if k > 0:
                    b, g, r = cv2.split(frame)
                    frame[:] = cv2.merge([np.roll(b, -k, 1), g, np.roll(r, k, 1)])
            elif kind == "zoom_blur":
                amt = fx.get("amount", 0.06) * (1 - u) ** 1.5
                if amt > 0.003:
                    acc = frame.astype(np.float32)
                    cx, cy = fx.get("center", [0.5, 0.5])
                    for k in range(1, 6):
                        s = 1 + amt * k / 5
                        M = cv2.getRotationMatrix2D((cx * W, cy * H), 0, s)
                        acc += cv2.warpAffine(frame, M, (W, H), borderMode=cv2.BORDER_REFLECT).astype(np.float32)
                    frame[:] = (acc / 6).astype(np.uint8)
            elif kind == "tint":
                amt = fx.get("amount", 0.5)
                if "_start" in fx and "_end" in fx:
                    dur = fx["_end"] - fx["_start"]
                    e = fx.get("fade", 0.1)
                    amt *= min(1.0, u * dur / e, (1 - u) * dur / e)
                g = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR).astype(np.float32)
                lo = np.array(bgr(fx.get("shadow", "blue")), np.float32)
                hi = np.array(bgr(fx.get("highlight", "gold")), np.float32)
                l = g / 255
                duo = lo * (1 - l) + hi * l
                duo = duo * 0.6 + g * 0.6
                frame[:] = (frame.astype(np.float32) * (1 - amt) + duo.clip(0, 255) * amt).astype(np.uint8)
            elif kind == "confetti":
                self._confetti(frame, fx, t)
            elif kind == "vhs":
                rng = np.random.default_rng(int(t * 100))
                band_h = 6
                out = frame.copy()
                for y in range(0, H, band_h):
                    shift = int(rng.normal(0, fx.get("jitter", 10)))
                    out[y:y + band_h] = np.roll(frame[y:y + band_h], shift, axis=1)
                for _ in range(3):
                    y = int(rng.uniform(0, H))
                    out[y:y + 14] = (out[y:y + 14].astype(np.int16) + 70).clip(0, 255).astype(np.uint8)
                b, g, r = cv2.split(out)
                out = cv2.merge([np.roll(b, -6, 1), g, np.roll(r, 6, 1)])
                noise = rng.integers(0, 40, (H // 4, W // 4), dtype=np.uint8)
                noise = cv2.resize(noise, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]
                frame[:] = cv2.add(out, np.repeat(noise, 3, axis=2))
            elif kind == "text":
                self._text(frame, fx, u, t)
            elif kind == "badge":
                self._badge(frame, fx, u, t)
            elif kind == "card":
                self._card(frame, fx, u, t)

    def _shockwave(self, frame, fx, u, t):
        H, W = frame.shape[:2]
        # The anchor is a world point; map it through the camera so the ring sits on the contact.
        src_t = self.tl.at(fx["_at"])[0]
        x, y = self.tracks.resolve(fx.get("target", "ball"), src_t)
        if fx.get("offset"):
            x += fx["offset"][0]
            y += fx["offset"][1]
        M = self._cur_M
        px = M[0, 0] * x * self.src.w + M[0, 1] * y * self.src.h + M[0, 2]
        py = M[1, 0] * x * self.src.w + M[1, 1] * y * self.src.h + M[1, 2]
        layer = np.zeros_like(frame)
        c = bgr(fx.get("color", "white"))
        c2 = bgr(fx.get("color2", "yellow"))
        rmax = fx.get("radius", 260)
        squash = fx.get("squash", 0.55)
        for k, delay in enumerate((0.0, 0.12, 0.24)):
            v = (u - delay) / (1 - delay)
            if v <= 0:
                continue
            r = int(rmax * ease(v, "out"))
            th = max(1, int(14 * (1 - v)))
            cv2.ellipse(layer, (int(px), int(py)), (r, int(r * squash)), 0, 0, 360, c if k % 2 == 0 else c2, th, cv2.LINE_AA)
        # burst spikes
        if u < 0.6:
            v = u / 0.6
            for i in range(16):
                ang = i * 2 * math.pi / 16 + 0.2
                r0 = rmax * (0.15 + 0.6 * ease(v, "out"))
                r1 = r0 + rmax * 0.35 * (1 - v)
                p0 = (int(px + math.cos(ang) * r0), int(py + math.sin(ang) * r0 * squash))
                p1 = (int(px + math.cos(ang) * r1), int(py + math.sin(ang) * r1 * squash))
                cv2.line(layer, p0, p1, c2, max(1, int(6 * (1 - v))), cv2.LINE_AA)
        g = cv2.GaussianBlur(layer, (0, 0), 6)
        frame[:] = cv2.add(cv2.add(frame, layer), g)

    def _speed_lines(self, frame, fx, t, u):
        H, W = frame.shape[:2]
        cx, cy = fx.get("center", [0.5, 0.5])
        cx, cy = cx * W, cy * H
        layer = np.zeros((H, W), np.uint8)
        seed = int(t * 30)
        rng = np.random.default_rng(seed)
        amt = fx.get("amount", 1.0)
        if "_start" in fx and "_end" in fx:
            dur = fx["_end"] - fx["_start"]
            e = 0.15
            amt *= min(1.0, u * dur / e, (1 - u) * dur / e)
        for ang, r0, ln, th in self.lines:
            if rng.random() > 0.65:
                continue
            ang2 = ang + rng.uniform(-0.02, 0.02)
            R = math.hypot(W, H) / 2
            a = R * (r0 + rng.uniform(-0.05, 0.05))
            b = a + R * ln
            p0 = (int(cx + math.cos(ang2) * a), int(cy + math.sin(ang2) * a))
            p1 = (int(cx + math.cos(ang2) * b), int(cy + math.sin(ang2) * b))
            cv2.line(layer, p0, p1, 255, int(th) * 2, cv2.LINE_AA)
        a = (layer.astype(np.float32) / 255 * 0.55 * amt)[..., None]
        col = np.array(bgr(fx.get("color", "white")), np.float32)
        frame[:] = (frame * (1 - a) + col * a).astype(np.uint8)

    def _confetti(self, frame, fx, t):
        H, W = frame.shape[:2]
        t0 = fx["_at"]
        el = t - t0
        cols = [bgr(c) for c in ("yellow", "cyan", "magenta", "white", "blue", "lime", "orange")]
        for x0, y0, vy, vx, rot0, vr, ci, size in self.confetti:
            x = (x0 + vx * el + 0.02 * math.sin(el * 3 + x0 * 20)) * W
            y = (y0 + vy * el + 0.25 * el * el) * H
            if y < -20 or y > H + 20:
                continue
            ang = math.radians(rot0 + vr * el)
            sx = size * abs(math.cos(ang * 1.3)) + 2
            sy = size * 0.55
            box = cv2.boxPoints(((x, y), (sx, sy), math.degrees(ang)))
            cv2.fillPoly(frame, [box.astype(np.int32)], cols[int(ci)], cv2.LINE_AA)

    def _text(self, frame, fx, u, t):
        H, W = frame.shape[:2]
        dur = fx.get("dur", 1.2)
        el = u * dur
        size = int(fx.get("size", 160))
        sprite = text_sprite(
            fx["text"], size, fx.get("color", "white"), fx.get("color2"),
            fx.get("stroke", "black"), fx.get("stroke_w"), fx.get("font", "impact"),
            fx.get("shadow", True), fx.get("italic", 0.18), fx.get("glow"),
        )
        x, y = fx.get("pos", [0.5, 0.42])
        x, y = x * W, y * H
        anim = fx.get("anim", "slam")
        out_t = fx.get("out", 0.12)
        scale, angle, alpha = 1.0, fx.get("angle", 0.0), 1.0
        if anim == "slam":
            k = min(1.0, el / 0.14)
            scale = 2.6 - 1.6 * ease(k, "out")
            if 0.14 <= el < 0.4:
                scale = 1 + 0.06 * math.sin((el - 0.14) * 40) * (1 - (el - 0.14) / 0.26)
            alpha = min(1.0, el / 0.06)
        elif anim == "pop":
            scale = ease(min(1.0, el / 0.35), "elastic")
            alpha = min(1.0, el / 0.05)
        elif anim == "slide":
            k = ease(min(1.0, el / 0.22), "out")
            x += (1 - k) * -W * 0.6
            alpha = k
        elif anim == "rise":
            k = ease(min(1.0, el / 0.3), "out")
            y += (1 - k) * H * 0.08
            alpha = k
        elif anim == "stomp":
            k = min(1.0, el / 0.1)
            scale = 0.3 + 0.7 * ease(k, "back")
            alpha = k
        scale *= 1 + fx.get("drift", 0.05) * u
        if el > dur - out_t:
            k = (el - (dur - out_t)) / out_t
            if fx.get("exit", "zoom") == "zoom":
                scale *= 1 + 0.25 * ease(k, "in")
            else:
                x += ease(k, "in") * W * 0.7
            alpha *= (1 - k) ** 2
        if fx.get("wobble"):
            angle += fx["wobble"] * math.sin(el * 9)
        paste_sprite(frame, sprite, x, y, scale, angle, alpha)

    def _card(self, frame, fx, u, t):
        """A FIFA-style player card that slides in from the left edge."""
        H, W = frame.shape[:2]
        key = ("card", fx["big"], fx.get("small", ""), str(fx.get("color", "blue")))
        if key not in _text_cache:
            cw, ch = fx.get("w", 330), fx.get("h", 420)
            img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            top = np.array(rgb(fx.get("color", "blue")), float)
            bot = np.array(rgb(fx.get("color2", "black")), float)
            for y in range(ch):
                c = top * (1 - y / ch) + bot * (y / ch)
                d.line([(0, y), (cw, y)], fill=tuple(int(v) for v in c) + (235,))
            mask = Image.new("L", (cw, ch), 0)
            ImageDraw.Draw(mask).polygon([(0, 30), (30, 0), (cw, 0), (cw, ch - 30), (cw - 30, ch), (0, ch)], fill=255)
            img.putalpha(Image.fromarray(np.minimum(np.array(img)[..., 3], np.array(mask))))
            d = ImageDraw.Draw(img)
            d.polygon([(0, 30), (30, 0), (cw - 1, 0), (cw - 1, ch - 30), (cw - 30, ch - 1), (0, ch - 1)], outline=rgb(fx.get("edge", "gold")), width=6)
            fb = font("impact", fx.get("big_size", 210))
            bb = fb.getbbox(fx["big"], stroke_width=6)
            d.text(((cw - (bb[2] - bb[0])) / 2 - bb[0], 40 - bb[1]), fx["big"], font=fb, fill=rgb(fx.get("big_color", "white")),
                   stroke_width=6, stroke_fill=(0, 0, 0))
            fs = font("impact", fx.get("small_size", 64))
            sb = fs.getbbox(fx.get("small", ""))
            d.rectangle([0, ch - 120, cw, ch - 40], fill=rgb(fx.get("edge", "gold")) + (255,))
            d.text(((cw - (sb[2] - sb[0])) / 2 - sb[0], ch - 80 - (sb[3] - sb[1]) / 2 - sb[1]), fx.get("small", ""), font=fs, fill=(10, 10, 30))
            spr = np.array(img, np.float32)
            spr[..., 3] /= 255
            _text_cache[key] = spr
        spr = _text_cache[key]
        dur = fx.get("dur", 1.0)
        el = u * dur
        k_in = ease(min(1.0, el / 0.25), "back")
        k_out = ease(max(0.0, (el - (dur - 0.15)) / 0.15), "in")
        x0, y0 = fx.get("pos", [0.14, 0.55])
        x = x0 * W - (1 - k_in) * W * 0.4 - k_out * W * 0.4
        paste_sprite(frame, spr, x, y0 * H, fx.get("scale", 1.0), fx.get("angle", -4), 1.0)

    def _badge(self, frame, fx, u, t):
        H, W = frame.shape[:2]
        text = fx["text"]
        f = font(fx.get("font", "bold"), fx.get("size", 34))
        x, y = fx.get("pos", [0.83, 0.07])
        x, y = int(x * W), int(y * H)
        box = f.getbbox(text)
        tw, th = box[2] - box[0], box[3] - box[1]
        pad = 14
        dot = fx.get("dot", True)
        bw = tw + 2 * pad + (26 if dot else 0)
        bh = th + 2 * pad
        img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        bg = rgb(fx.get("bg", "red"))
        d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=bh // 2, fill=bg + (230,))
        tx = pad + (26 if dot else 0)
        d.text((tx, pad - box[1]), text, font=f, fill=rgb(fx.get("color", "white")))
        if dot and int(t * 3) % 2 == 0:
            d.ellipse([pad, bh / 2 - 7, pad + 14, bh / 2 + 7], fill=(255, 255, 255))
        spr = np.array(img, np.float32)
        spr[..., 3] /= 255
        if "_start" in fx and "_end" in fx:
            dur = fx["_end"] - fx["_start"]
            k = min(1.0, u * dur / 0.2, (1 - u) * dur / 0.2)
        else:
            k = min(1.0, u * fx.get("dur", 1) / 0.2, (1 - u) * fx.get("dur", 1) / 0.2)
        paste_sprite(frame, spr, x + (1 - ease(k)) * 300, y, 1.0, 0, k)

    # ---- grade
    def grade(self, frame, t, tag):
        g = self.spec.get("grade", {})
        f = frame.astype(np.float32) / 255
        c = g.get("contrast", 1.12)
        s = g.get("saturation", 1.3)
        gray = f.mean(axis=2, keepdims=True)
        f = gray + (f - gray) * s
        f = (f - 0.5) * c + 0.5 + g.get("lift", 0.0)
        if g.get("warm"):
            f[..., 2] *= 1 + g["warm"]
            f[..., 0] *= 1 - g["warm"] * 0.6
        v = g.get("vignette", 0.35)
        f = f * (1 - v + v * self.vig)
        return (f.clip(0, 1) * 255).astype(np.uint8)

    # ---- one frame
    def frame(self, n):
        t = n / self.fps
        src_t, seg, _ = self.tl.at(t)
        tag = seg["tag"]
        interp = self.spec.get("interp", "flow")
        img = self.src.get(src_t, interp if seg["kind"] == "play" else "nearest")
        self.world(img, t, src_t, tag)
        M, z = self._cam_matrix(n, t)
        self._cur_M = M
        out = cv2.warpAffine(img, M, (self.W, self.H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        out = self.grade(out, t, tag)
        self.screen(out, t, src_t, tag, z)
        return out

    # ---- audio
    def audio(self, path):
        sr = sfx.SR
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", self.video, "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"],
            capture_output=True, check=True,
        ).stdout
        orig = np.frombuffer(raw, np.float32).reshape(-1, 2)
        n = int(self.tl.duration * sr) + sr
        mix = np.zeros((n, 2), np.float32)
        a = self.spec.get("audio", {})
        times = np.arange(n) / sr
        src_pos = np.zeros(n)
        gain = np.zeros(n, np.float32)
        for seg in self.tl.segs:
            i0, i1 = int(seg["t0"] * sr), min(n, int(seg["t1"] * sr))
            if i1 <= i0:
                continue
            loc = times[i0:i1] - seg["t0"]
            if seg["kind"] == "freeze":
                src_pos[i0:i1] = seg["src"]
                gain[i0:i1] = 0.0
                continue
            d = seg["t1"] - seg["t0"]
            prog = seg["v0"] * loc + (seg["v1"] - seg["v0"]) * loc * loc / (2 * d)
            src_pos[i0:i1] = seg["b"] - prog if seg.get("reverse") else seg["a"] + prog
            speed = seg["v0"] + (seg["v1"] - seg["v0"]) * loc / d
            g = np.where(speed < 0.95, a.get("slow_gain", 0.7), a.get("orig_gain", 1.0))
            if seg["tag"] != "main":
                g = g * a.get("replay_gain", 0.5)
            if seg.get("reverse"):
                g = g * a.get("reverse_gain", 0.0)
            gain[i0:i1] = g
        gain = np.convolve(gain, np.ones(2400) / 2400, mode="same").astype(np.float32)
        idx = src_pos * sr
        lo = np.clip(idx.astype(int), 0, len(orig) - 2)
        fr = (idx - lo)[:, None].astype(np.float32)
        orig_rs = orig[lo] * (1 - fr) + orig[lo + 1] * fr
        mix += orig_rs * gain[:, None]
        duck = np.ones(n, np.float32)
        for item in self.spec.get("sfx", []):
            t0 = self.tl.resolve(item["t"])
            if t0 is None:
                continue
            kind = item["kind"]
            if kind == "beat":
                t1 = self.tl.resolve(item["until"]) if "until" in item else self.tl.duration
                clip = sfx.beat(t1 - t0 + 0.4, bpm=item.get("bpm", 140), intensity=1.0)
                fade = int(0.25 * sr)
                env = np.ones(len(clip), np.float32)
                env[-fade:] = np.linspace(1, 0, fade)
                env[: int(0.05 * sr)] = np.linspace(0, 1, int(0.05 * sr))
                clip = clip * env[:, None]
            else:
                clip = sfx.make(kind, **item.get("params", {}))
            i0 = int((t0 - item.get("pre", 0)) * sr)
            g = item.get("gain", 0.8)
            seg = clip[: max(0, n - max(i0, 0))]
            if i0 < 0:
                seg = seg[-i0:]
                i0 = 0
            mix[i0:i0 + len(seg)] += seg * g
            if item.get("duck"):
                d0, d1 = i0, min(n, i0 + int(item["duck"] * sr))
                duck[d0:d1] = np.minimum(duck[d0:d1], 0.35)
        duck = np.convolve(duck, np.ones(4800) / 4800, mode="same").astype(np.float32)
        mix[:, :] *= 1.0
        mix = mix * np.minimum(1.0, duck[:, None] + 0.4)
        mix = np.tanh(mix * a.get("drive", 1.1)) * 0.95
        mix = mix[: int(self.tl.duration * sr)]
        pcm = (mix * 32767).astype("<i2").tobytes()
        import wave
        with wave.open(path, "wb") as wv:
            wv.setnchannels(2)
            wv.setsampwidth(2)
            wv.setframerate(sr)
            wv.writeframes(pcm)

    def render(self, out_path):
        wav = out_path.replace(".mp4", ".wav")
        self.audio(wav)
        tmp = out_path.replace(".mp4", ".video.mp4")
        proc = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{self.W}x{self.H}", "-r", str(self.fps), "-i", "-",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", tmp],
            stdin=subprocess.PIPE,
        )
        for n in range(self.n_frames):
            proc.stdin.write(self.frame(n).tobytes())
            if n % 60 == 0:
                print(f"  frame {n}/{self.n_frames}", flush=True)
        proc.stdin.close()
        proc.wait()
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", tmp, "-i", wav, "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_path],
            check=True,
        )
        os.remove(tmp)
        print(f"wrote {out_path} ({self.tl.duration:.2f}s, {self.n_frames} frames)")

    def timeline_report(self):
        rows = []
        for seg in self.tl.segs:
            if seg["kind"] == "freeze":
                rows.append(f"  out {seg['t0']:6.2f}-{seg['t1']:6.2f}  FREEZE src {seg['src']:.2f}  [{seg['tag']}]")
            else:
                rows.append(f"  out {seg['t0']:6.2f}-{seg['t1']:6.2f}  src {seg['a']:.2f}-{seg['b']:.2f}  speed {seg['v0']}->{seg['v1']}  [{seg['tag']}]")
        for fx in self.fx:
            if fx.get("_at") is not None and fx["kind"] in ("text", "shockwave", "flash", "confetti"):
                rows.append(f"  fx {fx['kind']:9s} @ {fx['_at']:6.2f}  {fx.get('text', '')!r}".replace("\n", " "))
        return "\n".join(rows)


def main():
    spec_path, out_path = sys.argv[1], sys.argv[2]
    with open(spec_path) as handle:
        spec = json.load(handle)
    base = os.path.dirname(os.path.dirname(os.path.abspath(spec_path)))
    if spec.get("ball_track_dir"):
        base = spec["ball_track_dir"]
    r = Renderer(spec, base)
    print(r.timeline_report())
    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1].split(",")]
        sheet = sys.argv[sys.argv.index("--preview") + 2]
        tiles = []
        for t in times:
            n = min(r.n_frames - 1, int(round(t * r.fps)))
            img = r.frame(n)
            img = cv2.resize(img, (640, 360))
            cv2.putText(img, f"out {t:.2f}s", (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            tiles.append(img)
        cols = 3
        rows = (len(tiles) + cols - 1) // cols
        canvas = np.zeros((rows * 360, cols * 640, 3), np.uint8)
        for i, tile in enumerate(tiles):
            rr, cc = divmod(i, cols)
            canvas[rr * 360:(rr + 1) * 360, cc * 640:(cc + 1) * 640] = tile
        cv2.imwrite(sheet, canvas)
        return
    r.render(out_path)


if __name__ == "__main__":
    main()
