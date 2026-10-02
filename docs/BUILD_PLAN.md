
# VAST Builders Challenge: Player Tracking Overlay

One-day hackathon. Build a video agent on VAST's pre-built pipeline, driven from Cursor on a workshop VM.

## The idea

Broadcast-style overlay on football footage. Rings under players, a line and distance label between the ball carrier and the nearest opponent, a "pressure" flag when an opponent closes in. Playback in a browser with the overlay drawn live as the clip plays.

Organisers confirmed (2026-10-02) that teams can upload their own footage. Footage must be something we are allowed to use. Shoot it ourselves if in doubt.

## How the stack fits

| Layer | Who runs it | What we do with it |
|---|---|---|
| Upload + ingest pipeline (segment, YOLO detect, Cosmos describe, embed, write VastDB) | VAST, already running | Upload our clip. Wait for it to index. |
| YOLO bounding boxes per segment | Stored in VastDB. Open endpoint also available, no auth. | Read boxes for people and ball. Draw rings. Call YOLO directly on frames if stored boxes are too sparse. |
| Search / Q&A API | VAST | Find our clip. Pull captions for the stretch goal. |
| W&B serverless LLM | CoreWeave, keys in VM env | Stretch only: one-line commentary per pressure event. |
| Cursor agent + `.cursor/skills/` | On the VM | How we build. Plain-language prompts. |
| Deploy skill `deploy-app-no-registry` | VAST k8s, team namespace | Ship the page at `/app`. |

Nothing runs on our laptops. Max 2 VMs per team.

## Split

- Jon: drives Cursor and the VM. Upload, YOLO, deploy.
- Brendan: use case, footage, reading detections, demo story, submission writeup. Also prompts Cursor alongside.

## Before the day

- [ ] Join Cosmos community, sign up for Cursor (personal email), create wandb account. All three gate credits.
- [ ] Shoot 2 to 3 minutes of football footage with two phones. Phone 1: fixed wide angle, high vantage point (balcony, fence, stand). This is the main feed. Phone 2: behind one goal or on the sideline, also fixed. Clap once in view of both at the start so the clips can be synced. Export both as mp4, 1080p.
- [ ] Trim both to the same 60 to 90 seconds, starting at the clap. Keep the full clips as backup.
- [ ] Jon: sign in to `gh` on the VM in the first 15 minutes so pushes work. Check `.gitignore` covers the team config before the first push.
- [ ] Agree the working branch. Default branch currently shows as `jonhpark7966/hackathon-brainstorming`, not `main`.
- [ ] Bring personal laptop and charger.

## Build order

Steps 1 to 4 by lunch. Everything after is bonus.

### 1. Health check (15 min)

```
run a git pull
```
```
check that everything is working
```

### 2. Upload and index the clip (30 min, mostly waiting)

```
upload my football clip at <path> with scenario "sports" and metadata location=sydney camera_id=pitch_cam-1. Confirm what you are about to run before you start.
```
```
is it done yet?
```

Check the Dashboard tab in the VSS UI for segment counts.

### 3. Inspect detections (20 min). Decides the rest of the day.

```
show me the YOLO detections for the football clip. How many bounding boxes do I get per segment, and at what time granularity? List the object classes found.
```

Three outcomes:

- Many boxes per segment with timestamps: use stored boxes. Best case.
- One or few boxes per segment: overlay will jump every few seconds. Acceptable for a demo. Move on, revisit in step 6.
- No `sports ball` class or no people: run YOLO directly. See step 6.

### 4. Overlay page v1 (90 min)

```
build a single-page web app: a video element playing the football clip with a canvas on top. Read the YOLO detections for this clip and draw a flat ellipse (a ring) at the bottom centre of each person box, cyan. Draw an orange ring for the ball. Sync drawing to video currentTime. Save under tools/overlay/. Run it locally on the VM and show me how to open it.
```

If this works, we have a demo. Commit and push.

### 5. Pressure line (60 min)

```
extend the overlay: find the person box closest to the ball (the carrier). Draw a dashed line from the carrier to the nearest other person and label it with an estimated distance in metres. Assume the pitch width in frame is about 50m to scale pixels to metres, mark it "est." Turn the carrier ring red and show a PRESSURE badge when that distance drops under 3m. Log each pressure event with a timestamp to a side panel.
```

### 6. If detections are too sparse (fallback, 60 min)

```
the stored detections are too sparse. Extract frames from the clip at 5 fps and send each to the YOLO endpoint directly using the gpu skill. Save the results as a JSON file keyed by timestamp and point the overlay at that file instead.
```

### 7. Deploy (30 min)

```
deploy tools/overlay to Kubernetes in my team namespace at Ingress path /app using the deploy-app-no-registry skill. No Docker build or push.
```

### 7.5. Multi-camera (only if step 7 is done before 3pm, 60 min)

```
upload the second clip as camera_id=pitch_cam-2, same scenario and location. When indexed, pull its detections to tools/overlay/detections-cam2.json. Add a camera toggle to the HUD that swaps the video source and detections file and keeps currentTime. On cam-2 draw rings only, no pressure line.
```

### 8. Stretch: commentary (if time)

```
for each logged pressure event, pull the Cosmos caption for that segment and ask the W&B inference endpoint for a one-line commentator-style summary. Show it next to the event in the side panel.
```

### 9. Submit (30 min, start by 4pm)

```
help me submit our project
```

Writes `SUBMISSION.md`. Brendan owns the wording. Repo link must be in it.

## Do not build

Speed labels, skeleton poses, zone labels, team colour classification, multi-camera. Each is a half day. None improve the story.

## When it breaks

| Symptom | Likely cause | Try |
|---|---|---|
| Search returns nothing | Not indexed yet, or login expired | Dashboard tab. Then `retrieval/login`. Then `list-metadata` to check filter values exist. |
| Upload skill says not available | Upload may be gated | Ask on Cosmos. Fallback: SF or neighborhood street cams, same app, rings on cars and pedestrians. |
| YOLO finds no ball | Ball too small at this resolution | Rings on people only. Carrier = person nearest the ball's last known position, or drop the ball and do nearest-pair distance. |
| Overlay out of sync | Detections are per segment, not per frame | Interpolate ring position between segments. Or step 6. |
| Anything else | | `/ask-cosmos` in Cursor, post the snippet on Cosmos. |

## Demo story (60 seconds)

Problem: coaches review footage by eye. Show the clip raw. Show it with rings. Show a pressure event fire. Show the event log. Say what you would do with it next (training review, youth coaching). Stop.

## Links

- [[03 Projects/(C) Personal Projects]]
- Starter repo docs: BUILD_DAY.md, ARCHITECTURE_REFERENCE.md in the starter repo
- Reference image: trainmatricx.com World Cup 2026 CV article
