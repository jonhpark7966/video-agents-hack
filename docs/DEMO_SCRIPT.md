# Demo script (60 seconds)

Brendan talks, Jon drives the screen. Rehearse it twice with a timer.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:10 | Raw clip playing, no overlay | "Coaches review footage like this by eye. Finding the moments a player gets closed down means scrubbing back and forth." |
| 0:10–0:20 | Turn the overlay on: rings on players and ball | "We uploaded our own footage to VAST's pipeline. YOLO finds every player and the ball, and we draw it live in the browser." |
| 0:20–0:35 | Let play run up to a pressure moment. The line shrinks, the ring turns red, the PRESSURE badge appears | "The white ring is the player with the ball. The line is the distance to the nearest opponent. Under three metres, it flags pressure." |
| 0:35–0:45 | Point at the side panel log | "Every pressure event is logged with a timestamp, so a coach jumps straight to the moments that matter." |
| 0:45–0:60 | Stay on the overlay | "It runs end to end on the VAST stack, built in a day with Cursor. Next: team colours, real pitch distances, and session summaries for youth coaches." Stop. |

## Before you go up

- [ ] `/app` loads on the demo laptop, and the clip plays with sound off.
- [ ] Note the timestamp of the best pressure event: `__:__`. Start the clip about 10s before it.
- [ ] Backup: a screen recording of the overlay running, open in another tab.
- [ ] Phrase the distance as "estimated". Don't claim exact metres.

## If a judge asks

- **"Is the distance accurate?"** "It's an estimate from an assumed 50m of visible pitch on a fixed wide shot. Calibrating from the pitch markings is the next step."
- **"How do you know who's an opponent?"** "We don't yet. It's the nearest other player. Team colour detection is on our list."
- **"Why not live?"** "The pipeline indexes uploaded clips. Streaming would be next once tracking holds up."
- **"What did VAST give you?"** "Ingest, YOLO detections stored per segment, search, and hosting. We wrote the overlay on top."
