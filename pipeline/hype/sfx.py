"""Synthesized sound effects, all numpy, 48 kHz stereo float32.

Every function returns an array shaped (n, 2). No sample files are needed, so
the edit renders the same on any machine.
"""

import numpy as np

SR = 48000
_rng = np.random.default_rng(7)


def _t(dur):
    return np.arange(int(dur * SR)) / SR


def _st(mono, pan=0.0):
    left = np.cos((pan + 1) * np.pi / 4)
    right = np.sin((pan + 1) * np.pi / 4)
    return np.stack([mono * left, mono * right], axis=1).astype(np.float32)


def _noise(n):
    return _rng.standard_normal(n)


def _lowpass(x, cutoff):
    """One-pole lowpass; cutoff may be an array (sweeps)."""
    cutoff = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def _fast_lp(x, cutoff):
    # fixed-cutoff lowpass via FFT, much faster than the sample loop
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / np.sqrt(1 + (freqs / cutoff) ** 4)
    return np.fft.irfft(spec, len(x))


def _band(x, lo, hi):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= ((freqs > lo) & (freqs < hi)).astype(float)
    return np.fft.irfft(spec, len(x))


def _env(n, attack, release, curve=3.0):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    r = np.clip(1 - (t - attack) / max(release, 1e-4), 0, 1) ** curve
    return np.where(t < attack, a, r)


def _norm(x, peak=0.9):
    m = np.max(np.abs(x)) or 1.0
    return x / m * peak


def whoosh(dur=0.55, rise=True, pan_sweep=True):
    n = int(dur * SR)
    t = _t(dur)
    sweep = 400 + 5000 * (t / dur if rise else 1 - t / dur) ** 1.6
    x = _lowpass(_noise(n), sweep)
    x -= _lowpass(x, 200)
    shape = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5
    x = _norm(x * shape, 0.8)
    if pan_sweep:
        pan = np.linspace(-0.8, 0.8, n)
        return np.stack([x * np.cos((pan + 1) * np.pi / 4), x * np.sin((pan + 1) * np.pi / 4)], 1).astype(np.float32)
    return _st(x)


def kick_thump(dur=0.35):
    """The foot on the ball: short body thump plus leather snap."""
    t = _t(dur)
    f = 55 + 140 * np.exp(-t * 40)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14)
    snap = _band(_noise(len(t)), 1500, 6000) * np.exp(-t * 90)
    return _st(_norm(body + 0.6 * _norm(snap), 0.95))


def boom(dur=1.8):
    """Cinematic sub drop for the big moment."""
    t = _t(dur)
    f = 30 + 90 * np.exp(-t * 6)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.2)
    crack = _fast_lp(_noise(len(t)), 2500) * np.exp(-t * 18)
    tail = _fast_lp(_noise(len(t)), 600) * np.exp(-t * 2.5) * 0.4
    x = np.tanh(2.2 * (sub + 0.5 * _norm(crack) + tail))
    return _st(_norm(x, 0.95))


def riser(dur=1.2):
    t = _t(dur)
    f = 180 * (2 ** (3 * t / dur))
    tone = np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)) * 0.25 + np.sin(2 * np.pi * np.cumsum(f * 1.01) / SR) * 0.5
    noise = _lowpass(_noise(len(t)), 300 + 9000 * (t / dur) ** 2)
    x = (tone * 0.5 + noise) * (t / dur) ** 2
    return _st(_norm(x, 0.7))


def reverse_cymbal(dur=0.9):
    t = _t(dur)
    x = _band(_noise(len(t)), 3000, 16000) * (t / dur) ** 3
    return _st(_norm(x, 0.6))


def shutter(dur=0.12):
    """Freeze-frame camera click."""
    t = _t(dur)
    a = _band(_noise(len(t)), 2000, 9000) * np.exp(-t * 120)
    b = np.roll(a, int(0.045 * SR)) * 0.7
    return _st(_norm(a + b, 0.7))


def swish(dur=0.22):
    """Short text-slide swoosh."""
    t = _t(dur)
    x = _lowpass(_noise(len(t)), 1200 + 7000 * t / dur) * np.sin(np.pi * t / dur) ** 2
    return _st(_norm(x, 0.55))


def slam(dur=0.5):
    """Text slam: punchy low hit with a metallic ring."""
    t = _t(dur)
    hit = np.sin(2 * np.pi * np.cumsum(70 + 200 * np.exp(-t * 30)) / SR) * np.exp(-t * 9)
    ring = (np.sin(2 * np.pi * 820 * t) + 0.6 * np.sin(2 * np.pi * 1290 * t)) * np.exp(-t * 11) * 0.25
    noise = _fast_lp(_noise(len(t)), 4000) * np.exp(-t * 35) * 0.5
    return _st(_norm(np.tanh(1.8 * (hit + ring + noise)), 0.9))


def air_horn(dur=1.3):
    t = _t(dur)
    chord = [233.08, 293.66, 349.23]
    x = sum(2 * (f * t % 1) - 1 for f in chord)
    wobble = 1 + 0.004 * np.sin(2 * np.pi * 6 * t)
    x = sum(2 * ((f * t * wobble) % 1) - 1 for f in chord)
    x = _fast_lp(x, 3200)
    env = _env(len(t), 0.03, dur - 0.03, 0.6)
    gaps = np.ones_like(t)
    gaps[(t > 0.28) & (t < 0.34)] = 0.15
    gaps[(t > 0.56) & (t < 0.62)] = 0.15
    return _st(_norm(np.tanh(1.5 * x) * env * _fast_lp(gaps, 60), 0.6))


def crowd_roar(dur=3.5, swell=0.4):
    """A stadium roar: band-limited noise with a swell and a slow decay."""
    t = _t(dur)
    base = _band(_noise(len(t)), 250, 3500)
    voices = sum(
        _band(_noise(len(t)), lo, lo * 1.6) * (0.5 + 0.5 * np.sin(2 * np.pi * r * t + p))
        for lo, r, p in [(400, 1.3, 0), (700, 2.1, 1), (1100, 1.7, 2), (1600, 2.7, 3)]
    )
    x = base + 0.7 * voices
    env = np.clip(t / swell, 0, 1) ** 0.7 * np.exp(-np.clip(t - swell - 0.8, 0, None) * 0.9)
    left = _norm(x * env, 0.8)
    right = _norm(np.roll(x, 911) * env, 0.8)
    return np.stack([left, right], 1).astype(np.float32)


def bass_drop(dur=1.0):
    t = _t(dur)
    f = 110 * np.exp(-t * 2.5) + 35
    x = np.tanh(3 * np.sin(2 * np.pi * np.cumsum(f) / SR)) * np.exp(-t * 2.0)
    return _st(_norm(x, 0.9))


def glitch(dur=0.25):
    t = _t(dur)
    blocks = np.repeat(_rng.choice([-1, 1], int(dur * 120) + 1), SR // 120)[: len(t)]
    tone = np.sign(np.sin(2 * np.pi * 1400 * t)) * blocks
    x = (tone * 0.4 + _band(_noise(len(t)), 3000, 12000) * 0.6) * _env(len(t), 0.005, dur, 1)
    return _st(_norm(x, 0.5))


def tick(dur=0.06, freq=2400):
    t = _t(dur)
    return _st(_norm(np.sin(2 * np.pi * freq * t) * np.exp(-t * 90), 0.4))


def beat(dur, bpm=140, swing=0.0, intensity=1.0):
    """A small trap-style bed: kick, snare, hats. Loops for `dur` seconds."""
    n = int(dur * SR)
    out = np.zeros(n)
    step = 60 / bpm / 4  # sixteenth
    kt = _t(0.4)
    kick = np.sin(2 * np.pi * np.cumsum(45 + 120 * np.exp(-kt * 35)) / SR) * np.exp(-kt * 8)
    st = _t(0.25)
    snare = (_band(_noise(len(st)), 1200, 8000) * 0.7 + np.sin(2 * np.pi * 190 * st) * 0.5) * np.exp(-st * 22)
    ht = _t(0.05)
    hat = _band(_noise(len(ht)), 7000, 16000) * np.exp(-ht * 120)
    kick_pat = [1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0]
    snare_pat = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0]
    i = 0
    while True:
        pos = int(i * step * SR)
        if pos >= n:
            break
        s = i % 16
        for pat, smp, gain in ((kick_pat, kick, 1.0), (snare_pat, snare, 0.7)):
            if pat[s]:
                seg = smp[: n - pos]
                out[pos:pos + len(seg)] += seg * gain
        hat_gain = 0.25 if s % 2 == 0 else 0.12
        seg = hat[: n - pos]
        out[pos:pos + len(seg)] += seg * hat_gain
        i += 1
    return _st(_norm(np.tanh(1.3 * out), 0.75 * intensity))


def heartbeat(dur=1.0, bpm=110):
    """Lub-dub thumps for a frozen moment."""
    t = _t(dur)
    out = np.zeros(len(t))
    period = 60 / bpm
    kt = _t(0.25)
    thump = np.sin(2 * np.pi * np.cumsum(40 + 50 * np.exp(-kt * 30)) / SR) * np.exp(-kt * 18)
    start = 0.0
    while start < dur:
        for off, g in ((0.0, 1.0), (0.16, 0.7)):
            i = int((start + off) * SR)
            seg = thump[: max(0, len(t) - i)]
            out[i:i + len(seg)] += seg * g
        start += period
    return _st(_norm(np.tanh(2 * out), 0.95))


def whizz(dur=0.8):
    """A ball flying past: doppler tone sliding down plus air."""
    t = _t(dur)
    f = 900 * np.exp(-t * 2.2) + 180
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.3
    air = _lowpass(_noise(len(t)), 2500 * np.exp(-t * 2) + 400)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 0.8
    pan = np.linspace(-0.9, 0.9, len(t))
    x = _norm((tone + air) * env, 0.8)
    return np.stack([x * np.cos((pan + 1) * np.pi / 4), x * np.sin((pan + 1) * np.pi / 4)], 1).astype(np.float32)


LIBRARY = {
    "heartbeat": heartbeat,
    "whizz": whizz,
    "whoosh": whoosh,
    "kick": kick_thump,
    "boom": boom,
    "riser": riser,
    "reverse_cymbal": reverse_cymbal,
    "shutter": shutter,
    "swish": swish,
    "slam": slam,
    "air_horn": air_horn,
    "crowd_roar": crowd_roar,
    "bass_drop": bass_drop,
    "glitch": glitch,
    "tick": tick,
}


def make(kind, **kw):
    return LIBRARY[kind](**kw)
