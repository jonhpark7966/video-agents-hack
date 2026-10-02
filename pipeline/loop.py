"""perceive -> several styled drafts -> render -> evaluate, for 5 iterations.

Each iteration draws a few styles from the prompt guide, grades every one, and
carries the highest-scoring variant forward. The others stay in the history.
Ranks saved from the review page are read at the start of each iteration and
passed into the next draft. They do not choose the parent.

  python3 pipeline/web/server.py
  python3 pipeline/loop.py samples/wz1r_VJaJZw_0-8.mp4

Writes runs/<clip>/manifest.json and runs/<clip>/iter_N/<variant>/.
"""

import argparse
import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor

import generate
import reason

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Three styles per pass, rotating so the history shows all five families.
SCHEDULE = [
    ["role-marker", "telestrator", "social-hook"],
    ["broadcast-strap", "data-chip", "role-marker"],
    ["telestrator", "social-hook", "broadcast-strap"],
    ["data-chip", "role-marker", "telestrator"],
    ["social-hook", "broadcast-strap", "data-chip"],
]


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def rel(path):
    return os.path.relpath(path, ROOT)


def load_ranks(run):
    path = os.path.join(run, "ranks.json")
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return json.load(handle)


def labels_of(overlay):
    found = []
    if not overlay:
        return found
    for item in overlay.get("items", []):
        if item.get("text"):
            found.append(item["text"])
    for line in overlay.get("explanation", []):
        if line.get("text"):
            found.append(line["text"])
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--reference", default=os.path.join(ROOT, "samples", "g1nYknl92wI_0842-0852.mp4"))
    parser.add_argument("--out", default=os.path.join(ROOT, "runs"))
    parser.add_argument("--iters", type=int, default=5)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    video = args.video if os.path.isabs(args.video) else os.path.join(ROOT, args.video)
    name = os.path.splitext(os.path.basename(video))[0]
    run = os.path.join(args.out, name)
    os.makedirs(run, exist_ok=True)
    _, _, blurbs = generate.load_guide()

    ref_frame = os.path.join(run, "reference_role.jpg")
    if not os.path.exists(ref_frame):
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "2", "-i", args.reference, "-frames:v", "1",
             "-vf", "scale=960:-1", ref_frame, "-hide_banner", "-loglevel", "error"],
            check=True,
        )

    state = {
        "run": name,
        "video": rel(video),
        "reference": rel(args.reference) if os.path.exists(args.reference) else "",
        "status": "running",
        "phase": "reading the clip",
        "scene_summary": "",
        "scene_source": "",
        "iterations": [],
    }

    def publish():
        ranks = load_ranks(run)
        if ranks:
            state["ranks"] = ranks
        save(os.path.join(run, "manifest.json"), state)

    scene_path = os.path.join(run, "scene.json")
    if args.resume and os.path.exists(scene_path):
        with open(scene_path) as handle:
            scene = json.load(handle)
        print("reused scene.json", flush=True)
    else:
        state["phase"] = "perceiving the clip"
        publish()
        scene = reason.perceive(video, frame_dir=os.path.join(run, "input_frames"))
        save(scene_path, scene)
    state["scene_summary"] = scene.get("summary", "")
    state["scene_source"] = scene.get("source", "")
    publish()
    print(f"scene ({scene.get('source')}): {scene.get('summary')}", flush=True)
    print(f"tracks: {', '.join(t['id'] for t in scene['tracks'])}", flush=True)

    parent = None
    parent_critique = None
    for index in range(args.iters):
        styles = SCHEDULE[index % len(SCHEDULE)]
        it_dir = os.path.join(run, f"iter_{index}")
        os.makedirs(it_dir, exist_ok=True)
        ranks = load_ranks(run)
        state["phase"] = f"iteration {index + 1} of {args.iters}: drafting {', '.join(styles)}"
        state["iterations"] = state["iterations"][:index]
        publish()

        drafts = [None] * len(styles)
        errors = [None] * len(styles)

        def make_draft(slot):
            style = styles[slot]
            vid = f"v{slot}_{style}"
            folder = os.path.join(it_dir, vid)
            overlay_path = os.path.join(folder, "overlay.json")
            if args.resume and os.path.exists(overlay_path):
                with open(overlay_path) as handle:
                    return slot, json.load(handle), None
            try:
                if parent is None:
                    overlay = generate.draft(
                        scene, style, index, ranks=ranks, reference_frame=ref_frame,
                    )
                else:
                    overlay = generate.improve(
                        parent, parent_critique, scene, style,
                        ranks=ranks, reference_frame=ref_frame,
                    )
                return slot, overlay, None
            except Exception as exc:
                traceback.print_exc()
                return slot, None, f"{type(exc).__name__}: {exc}"

        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            for slot, overlay, error in pool.map(make_draft, range(len(styles))):
                drafts[slot] = overlay
                errors[slot] = error

        variants = []
        state["iterations"] = state["iterations"][:index]
        state["iterations"].append({"index": index, "picked": None, "variants": variants})
        for slot, style in enumerate(styles):
            vid = f"v{slot}_{style}"
            folder = os.path.join(it_dir, vid)
            os.makedirs(folder, exist_ok=True)
            overlay = drafts[slot]
            rendered = os.path.join(folder, "overlay.mp4")
            record = {
                "id": vid,
                "style": style,
                "blurb": blurbs.get(style, ""),
                "score": None,
                "scores": {},
                "summary": "",
                "issues": [],
                "labels": labels_of(overlay),
                "video": "",
                "error": errors[slot],
                "source": "",
            }
            if overlay is None:
                variants.append(record)
                publish()
                print(f"iter {index} {vid}: draft failed: {errors[slot]}", flush=True)
                continue
            save(os.path.join(folder, "overlay.json"), overlay)
            if not (args.resume and os.path.exists(rendered) and os.path.getsize(rendered) > 0):
                state["phase"] = f"iteration {index + 1} of {args.iters}: rendering {style}"
                publish()
                try:
                    generate.render(video, overlay, scene, rendered)
                except Exception as exc:
                    record["error"] = f"render: {exc}"
                    variants.append(record)
                    publish()
                    print(f"iter {index} {vid}: render failed", flush=True)
                    continue
            record["video"] = rel(rendered)
            record["labels"] = labels_of(overlay)
            variants.append(record)
            publish()

        pending = [i for i, record in enumerate(variants) if record["video"] and record["score"] is None]

        def grade(slot):
            record = variants[slot]
            folder = os.path.join(it_dir, record["id"])
            critique_path = os.path.join(folder, "critique.json")
            overlay = drafts[slot]
            if args.resume and os.path.exists(critique_path):
                with open(critique_path) as handle:
                    return slot, json.load(handle), None
            try:
                critique = reason.evaluate(os.path.join(folder, "overlay.mp4"), overlay, scene)
                return slot, critique, None
            except Exception as exc:
                traceback.print_exc()
                return slot, None, str(exc)

        if pending:
            state["phase"] = f"iteration {index + 1} of {args.iters}: grading"
            publish()
            with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
                for slot, critique, error in pool.map(grade, pending):
                    record = variants[slot]
                    if error or critique is None:
                        record["error"] = error or "no critique"
                        continue
                    save(os.path.join(it_dir, record["id"], "critique.json"), critique)
                    record["score"] = critique.get("score")
                    record["scores"] = critique.get("scores") or {}
                    record["summary"] = critique.get("summary") or ""
                    record["issues"] = critique.get("issues") or []
                    record["source"] = critique.get("source") or ""
                    print(
                        f"iter {index} {record['id']}: score {record['score']:.2f} "
                        f"({record['source']}) {record['summary']}",
                        flush=True,
                    )
                    publish()

        picked = choose(variants)
        state["iterations"][index]["picked"] = picked
        publish()
        print(f"iter {index} picked {picked}", flush=True)

        parent = None
        parent_critique = None
        for record in variants:
            if record["id"] != picked or not record["video"]:
                continue
            with open(os.path.join(it_dir, record["id"], "overlay.json")) as handle:
                parent = json.load(handle)
            critique_path = os.path.join(it_dir, record["id"], "critique.json")
            if os.path.exists(critique_path):
                with open(critique_path) as handle:
                    parent_critique = json.load(handle)
            break
        if parent is None:
            print(f"iter {index}: nothing rendered, next pass starts fresh", flush=True)

    state["status"] = "done"
    state["phase"] = f"finished {args.iters} iterations"
    publish()
    print(f"done -> {run}", flush=True)


def choose(variants):
    """Automatic parent for the next pass: highest score, else the first clip that rendered."""
    ranked = [v for v in variants if isinstance(v.get("score"), (int, float))]
    if ranked:
        ranked.sort(key=lambda v: (-v["score"], v["id"]))
        return ranked[0]["id"]
    rendered = [v for v in variants if v.get("video")]
    if rendered:
        return rendered[0]["id"]
    return variants[0]["id"] if variants else None


if __name__ == "__main__":
    main()
