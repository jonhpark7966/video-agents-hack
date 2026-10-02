"""perceive -> generate -> render -> evaluate -> improve -> render -> evaluate ... until pass.

  python3 pipeline/loop.py samples/wz1r_VJaJZw_5836-5914.mp4
  python3 pipeline/loop.py samples/wz1r_VJaJZw_5836-5914.mp4 --no-render   # JSON only, instant

Writes runs/<clip>/scene.json and runs/<clip>/iter_N/{overlay.json, overlay.mp4, critique.json}.
"""

import argparse
import json
import os

import generate
import reason


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--max-iters", type=int, default=4)
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()

    run = os.path.join(args.out, os.path.splitext(os.path.basename(args.video))[0])
    os.makedirs(run, exist_ok=True)

    scene = reason.perceive(args.video)  # step 1 (Reason)
    save(os.path.join(run, "scene.json"), scene)
    overlay = generate.generate(scene)  # step 2 (Gen)

    for i in range(args.max_iters):
        it = os.path.join(run, f"iter_{i}")
        os.makedirs(it, exist_ok=True)
        save(os.path.join(it, "overlay.json"), overlay)
        rendered = os.path.join(it, "overlay.mp4")
        if not args.no_render:
            generate.render(args.video, overlay, scene, rendered)

        critique = reason.evaluate(rendered, overlay, scene)  # step 3 (Reason)
        save(os.path.join(it, "critique.json"), critique)
        print(f"iter {i}: score {critique['score']:.2f} {critique['scores']} issues={len(critique['issues'])}")
        for issue in critique["issues"]:
            print(f"  - [{issue['axis']}] {issue['item']}: {issue['detail']}")
        if critique["pass"]:
            print(f"pass -> {it}")
            break
        overlay = generate.improve(overlay, critique)  # step 4 (Gen)


if __name__ == "__main__":
    main()
