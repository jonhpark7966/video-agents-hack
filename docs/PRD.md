
# PRD: Pitch Overlay

Paste everything below the line into Cursor's agent as the opening prompt. It is written for the agent.

---

# Pitch Overlay

A browser app that plays a football clip with a live tracking overlay. Rings under every player, a ring on the ball, a dashed line from the ball carrier to the nearest opponent with an estimated distance, and a PRESSURE flag when that distance drops under a threshold. Every pressure event is logged with a timestamp in a side panel.

Built on the VAST Builders Stack. Use the skills in `.cursor/skills/` for every call to the stack. Do not hand-write API calls when a skill covers it. Read a skill once if you need to understand the API shape.

## Stack mapping

| Feature | Stack component | Skill |
|---|---|---|
| Get the clip into the system | VAST AI OS ingest pipeline (segment, detect, describe, embed, write VastDB) | `ingest/` upload or reingest skill, scenario `sports` |
| Player and ball positions | YOLO11 detections stored per segment in VastDB | `retrieval/videos` for detections, `vastdb-read` to query directly |
| Denser detections if stored ones are sparse | YOLO11 GPU endpoint, `$YOLO_URL`, no auth | `.cursor/skills/gpu/` |
| Find and play the clip | VSS search and videos API | `retrieval/search`, `retrieval/videos` |
| Health and index status | VSS dashboard | `retrieval/dashboard` |
| Commentary line per event (stretch) | W&B serverless inference, `WANDB_` keys in env | direct call per W&B docs |
| Trace LLM calls (stretch) | W&B Weave | `weave` Python package |
| Hosting | VAST k8s, team namespace, Ingress `/app` | `deployment/deploy-app-no-registry` |

Everything runs on this VM. Nothing on a laptop. Stay inside this team's credentials and namespace.

## Users

Jon and Brendan on build day. Judges at the demo. A coach is the imagined end user.

## Scope

In:
- One clip, 60 to 90 seconds, uploaded by us, metadata `location=sydney camera_id=pitch_cam-1 scenario=sports`.
- Single page web app. Video element with a canvas on top, same size, synced to `video.currentTime`.
- Rings: flat ellipse at the bottom centre of each `person` box, cyan. Ring on `sports ball` box, orange. Carrier ring white, red under pressure.
- Carrier = the person box whose bottom centre is nearest the ball. If no ball detected in a frame, keep the last carrier.
- Pressure line: dashed line from carrier to nearest person on the other side, labelled `X.Xm est.` Pixel to metre scale assumes the visible pitch width is 50m. Label it as estimated everywhere.
- Threshold 3m. Under threshold: carrier ring red, PRESSURE badge top right, event appended to the side panel with `mm:ss`, carrier id, closer id, distance.
- Team assignment: not detected. Treat the nearest other person as the opponent. Good enough for the demo.
- Deployed at `/app` in the team namespace.

Multi-camera (step 7.5, only after deploy works):
- Two clips of the same passage of play from two phones, synced on a clap at the start and trimmed to it. Uploaded as `camera_id=pitch_cam-1` (wide, main) and `camera_id=pitch_cam-2` (end or side).
- A camera toggle in the HUD. Switching swaps the video source and the detections file, keeps `currentTime`.
- Pressure line and distance only on `pitch_cam-1`. The 50m scale is only true on the wide shot. On `pitch_cam-2` draw rings only.
- If the clip has hard cuts between angles inside one file, hide the pressure line for one second whenever the box count or positions jump sharply between frames.

Out (do not build, even if easy):
- Speed, skeleton poses, zone labels, team colour classification, live streaming, player names, heatmaps, a moving or panning camera.

## Data flow

1. Upload clip. Wait for the pipeline. Confirm segment count on the dashboard.
2. Pull detections for the clip. Normalise to one JSON file: `[{t: seconds, boxes: [{cls, x1, y1, x2, y2, conf}]}]`. Save to `tools/overlay/detections.json`.
3. If detections are fewer than 2 per second, run the fallback: extract frames at 5 fps with ffmpeg, POST each to `$YOLO_URL` per the gpu skill, write the same JSON shape.
4. Frontend loads `detections.json`, finds the nearest `t` to `video.currentTime` on each animation frame, draws.
5. Stretch: on each pressure event, fetch the Cosmos caption for that segment via `retrieval/videos`, send caption plus event facts to W&B inference, ask for one sentence of commentary, show it under the event. Wrap the call in Weave so it is traced.

## Build order

Work in this order. Stop and show me the result after each step before starting the next.

1. Health check. `git pull`, then confirm login, dashboard, and the gpu endpoints respond.
2. Upload the clip. Tell me what you are about to run before you run it. Report when indexed.
3. Inspect detections. Report boxes per second, classes found, whether `sports ball` appears. Recommend stored or fallback.
4. `tools/overlay/index.html` with rings only. Run it on the VM, tell me how to open it.
5. Pressure line, badge, event log.
6. Fallback dense detections, only if step 3 said so.
7. Deploy to `/app`.
7.5. Multi-camera: upload `pitch_cam-2`, add the camera toggle, rings only on cam-2. Only start this if step 7 is done before 3pm.
8. Stretch: commentary via W&B plus Weave.
9. `help me submit our project`.

Commit after every step that works. Short conventional commit messages (`feat:`, `fix:`, `chore:`).

## Done means

- Clip plays at `/app` with rings tracking players and ball for the whole clip.
- At least one pressure event fires and appears in the log.
- Repo has the code, `detections.json`, and `SUBMISSION.md`.

## Guardrails

- Never commit the team config or anything with credentials. Check `.gitignore` before the first push.
- Do not redeploy or modify DataEngine functions.
- Do not ingest footage from the internet.
- Ask before any re-ingest over one video.
- If a skill fails twice, stop and show me the error. Do not work around it with a hand-written call unless I say so.

## Reference

Mockup of the target look: `docs/mockup.html`. Match the feel: dark HUD, glowing cyan rings, orange ball ring, dashed orange pressure line turning red, side panel event log.
