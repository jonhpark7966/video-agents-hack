# pipeline — mock gen/eval loop

```
            ┌──────────────── Reason team (odd steps) ────────────────┐
 video ──▶  1 perceive   Cosmos Reason + YOLO        ──▶ scene.json
            3 evaluate   Cosmos Reason on overlay.mp4 ──▶ critique.json
            └─────────────────────────────────────────────────────────┘
            ┌──────────────── Gen team (even steps) ──────────────────┐
            2 generate   scene.json                   ──▶ overlay.json
            4 improve    overlay.json + critique.json ──▶ overlay.json (next iter)
              render     video + overlay.json         ──▶ overlay.mp4
            └─────────────────────────────────────────────────────────┘

 1 → 2 → render → 3 → 4 → render → 3 → 4 … until critique.pass (or --max-iters)
```

Everything is mocked: no models, no Python deps, only `ffmpeg`. Each team replaces
the function bodies in its own file. The JSON files in `contracts/` are the only
thing the two teams share.

| file | owner | swap in |
|---|---|---|
| `reason.py` `perceive`, `evaluate` | Reason | YOLO tracks, Cosmos Reason shots/events/grading |
| `generate.py` `generate`, `improve`, `render` | Gen | LLM-drafted effects + script, richer renderer |
| `loop.py` | shared | — |

## Run

```sh
samples/fetch.sh                                            # optional; clips are committed
python3 pipeline/loop.py samples/wz1r_VJaJZw_5836-5914.mp4  # ~10s, renders each iteration
python3 pipeline/loop.py samples/wz1r_VJaJZw_5836-5914.mp4 --no-render  # JSON only
```

Output goes to `runs/<clip>/scene.json` and `runs/<clip>/iter_N/{overlay.json,overlay.mp4,critique.json}`.
The mock draft is rough on purpose, so it scores 0.56 → 0.94 → 0.94 → 1.00 and passes at iter 3.

## Contracts

Times are seconds from the clip start. Boxes are normalized `[x, y, w, h]` with a top-left origin.

**`scene.json`** (step 1): `size`, `fps`, `duration`, `shots[]`, `tracks[]` (`id`, `label`, `keys[{t, box}]`),
`events[]` (`start`, `end`, `type`, `actors[track ids]`, `caption`), `summary`.

**`overlay.json`** (steps 2, 4): `iteration`, `items[]` (`id`, `kind`, `track`, `start`, `end`, `text?`, `size?`, `color`),
`explanation[]` (`id`, `start`, `end`, `text`). Items point at scene tracks by `track` id.

**`critique.json`** (step 3): `iteration`, `score` (0–1), `pass`, `scores{accuracy, readability, timing, coverage}`,
`issues[]` (`item`, `type`, `axis`, `detail`, `fix`). `fix` is a machine-readable hint
(`{"end": 9.5}`, `{"size": 40}`, `{"drop": true}`, `{"add_line": {...}}`), so `improve` can act without parsing prose.
Real Cosmos critiques can leave `fix` empty and put the prose in `detail`.

See `contracts/*.json` for real examples from iteration 0.
