# pipeline — generate, then reason, on a loop

```
video ──▶  reason.perceive     Claude Opus 5.5 on frames     ──▶ scene.json
           generate.draft      one style from the prompt guide ──▶ overlay.json
           generate.render     ffmpeg discs / rings / arrows     ──▶ overlay.mp4
           reason.evaluate     Claude Opus 5.5 on the result     ──▶ critique.json
           generate.improve    next style, using that critique   ──▶ overlay.json
```

`reason.py` keeps the mock's two calls, `perceive(video)` and `evaluate(rendered, overlay, scene)`.
Both call the `claude` binary (`claude-opus-5-5`). The old rule checker is only a fallback
if a grade call fails. `generate.py` asks the same model for the overlay, then ffmpeg draws it.

The reference clip is one style (a yellow disc and a one-word role). `prompt_guide.md` is the
wider set: role-marker, telestrator, social-hook, broadcast-strap, data-chip. Each iteration
drafts three of those, renders and grades all three, and carries the highest score forward.
The other versions stay in the history. Rank them on the review page; the next iteration
reads `ranks.json` and treats that as taste. Ranks do not pick the parent.

## Run

```sh
# optional if the clips are not already in samples/
samples/fetch.sh

python3 pipeline/web/server.py          # http://127.0.0.1:8765
python3 pipeline/loop.py samples/wz1r_VJaJZw_0-8.mp4
```

`samples/wz1r_VJaJZw_0-8.mp4` is the first 8 seconds of the Muniz clip, cut for a fast test.
`samples/g1nYknl92wI_0842-0852.mp4` is the reference the role-marker style is aiming at.

Five iterations, three variants each. Output:

```
runs/<clip>/scene.json
runs/<clip>/manifest.json          # what the review page polls
runs/<clip>/ranks.json             # written by the page
runs/<clip>/iter_N/<variant>/{overlay.json,overlay.mp4,critique.json}
```

Add `--resume` to reuse a scene and any variant that already has a critique. `--jobs 2`
is how many Claude calls run at once.

## Review page

The page shows the input, the reference, the variant that was carried forward, and every
version in the iteration. Under each clip, rank 1–3 (1 is the one to learn from) and write
a note. Save writes `runs/<clip>/ranks.json`. A loop that is still going reads that file
at the start of the next iteration.

## Overlay

Times are seconds from the clip start. Boxes in `scene.json` are normalized `[x, y, w, h]`,
top-left origin. An item's `kind` is `disc`, `ring`, `arrow`, `chip`, or `banner`.
`track` / `to` are scene track ids. `critique.json` has `score`, `scores` (accuracy,
readability, timing, coverage, style), `summary`, and `issues[]` (`item`, `type`, `axis`,
`detail`, `fix`).

`contracts/` is the earlier mock pass, before styles. The live files are under `runs/`.
