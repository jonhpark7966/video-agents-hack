# Pitch Overlay

**Team:** Jon Park, Brendan Rong
**Repo:** https://github.com/jonhpark7966/video-agents-hack
**Live demo:** `<team ingress URL>/app` _(fill in after deploy)_

## One line

A browser tool that plays football footage with live tracking rings and flags the moments a player on the ball comes under pressure.

## The problem

Coaches review match footage by eye. Spotting when and how often a player gets closed down means scrubbing back and forth through the clip. Grassroots and youth teams don't have the analysts or tracking systems the pros use.

## What it does

- Plays a clip with an overlay synced to the video:
  - a cyan ring under each player;
  - an orange ring on the ball;
  - a white ring on the player with the ball.
- Draws a dashed line from the player with the ball to the nearest opponent, labelled with an estimated distance in metres.
- When that distance drops under 3m, the ring turns red, a PRESSURE badge appears, and the event is logged with a timestamp.
- The side panel lists every pressure event, so a coach can jump straight to the moments that matter.

## How we built it

| Step | Stack component |
|---|---|
| Upload and index the clip | VAST AI OS ingest pipeline (segment, detect, describe, embed, VastDB), scenario `sports` |
| Player and ball positions | YOLO11 detections stored in VastDB _(or: direct YOLO11 GPU endpoint at 5 fps, if we used the fallback)_ |
| Find and play the clip | VSS search and videos API |
| Overlay | Single-page app: `<video>` with a `<canvas>` on top, drawn on each animation frame from `detections.json` |
| Hosting | VAST k8s, team namespace, Ingress `/app` |
| _(Stretch, if done)_ Commentary | Cosmos segment caption + W&B serverless inference, traced with Weave |

All built by prompting Cursor's agent on the workshop VM, using the stack skills in `.cursor/skills/`.

## Results

_(Fill in on the day.)_

- Clip: `<length>` seconds, filmed by us `<where>`, fixed wide angle.
- Detections: `<N>` boxes per second on average. Ball detected in `<N>%` of frames.
- Source: `<stored VastDB detections | direct YOLO at 5 fps>`, because `<reason>`.
- Pressure events logged: `<N>`.

## Limitations

- Distance is an **estimate**. It assumes about 50m of pitch is visible on the wide shot, and only holds for a fixed camera.
- Teams aren't detected. The "opponent" is the nearest other player.
- The player with the ball is whoever stands nearest it. If the ball is missed in a frame, we keep the last player with the ball.
- `<anything else we hit on the day>`

## What's next

- Team colour detection, so pressure only counts from real opponents.
- Pitch calibration from line markings for true distances.
- Session summaries for coaches: pressure events per player, per half.
- Youth and grassroots training review from a single phone on a fence.

## Run it

```sh
# open the deployed page
<team ingress URL>/app
```

Code is in `tools/overlay/`, with detections in `tools/overlay/detections.json`.
