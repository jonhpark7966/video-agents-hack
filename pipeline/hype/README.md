# hype — Claude-in-the-loop motion graphics edit

No Cosmos/VAST and no python harness calling a model: Claude (Opus 5.5, in the session)
is the perceiver and the critic. It reads frames, writes an edit spec, renders, re-reads
the render, and revises. Five passes per clip.

```
sheet.py   VIDEO OUT.jpg --start --end --fps [--grid] [--crop]   frames Claude reads
track.py   VIDEO track_keys.json track.json [--debug sheet.jpg]   per-frame ball, snapped to the blob
render.py  iter_N/edit.json iter_N/hype.mp4 [--preview T,.. sheet] the edit
sfx.py     synthesized whoosh / kick / boom / riser / roar / horn / heartbeat / beat bed
review.sh  iter_N  [python]                                       5 fps sheets + waveform of the render
```

Edit spec: `timeline` (speed, ramps `[v0,v1]`, `freeze`, `reverse`, tagged `intro`/`replay`/`end`
passes), `points` (player tracks), `camera` (zoom / focus / rot keys), `shake`, `beat_bump`,
`fx` (ball_trail, ball_ring, tag, spotlight, shockwave, text, card, badge, flash, chroma,
zoom_blur, speed_lines, letterbox, tint, vhs, confetti), `sfx`, `grade`, `audio`.
Times are source seconds; `{"at": s, "tag": "replay", "plus": 0.3}` targets another pass.

Needs numpy, opencv-python-headless, pillow, ffmpeg. Example run: `runs/20261002_212835_23c4d10d/hype/`.
