# Soccer overlay prompt guide

The reference clip `samples/g1nYknl92wI_0842-0852.mp4` is one good answer, not the only one. It is a YouTube tactics film (DK Falcon): a yellow disc under the ball carrier, a one-word role such as "Winger" in white, and sometimes a single arrow for the pass. Broadcasts, pundit shows, and social edits draw on the same footage for different jobs. Each variant follows exactly one style below. Do not mix styles in one variant.

This test clip is the first 8 seconds of a wide Premier League goal (Rodrigo Muniz, Sheffield United 3–3 Fulham). The camera stays wide, so players are small. Fulham are in white, Sheffield United are in red-and-white stripes, the goalkeeper is green, the referee is yellow. A broadcast lower-third already sits at the bottom left (crest and the name Rodrigo Muniz). Do not cover that corner and do not redraw the official score bug.

Shared rules:

- Put a marker on a player's feet or body. A shape in empty grass is a miss.
- One idea at a time. Two labels that overlap are a miss.
- Every word stays up at least 1.4 seconds. Explanation lines are at most 6 words.
- Only say what the scene events support. This slice is the build-up. Do not caption a goal unless the scene has a goal event.
- Colors you may use: yellow, white, cyan, red, green, magenta, orange. Yellow reads on grass. Red marks the defending side. White is for words.
- Kinds: `disc` (ellipse at the feet), `ring` (box around the body), `arrow` (from `track` to `to`), `chip` (small fact, top right, not stuck to a player), `banner` (a few big words, top center).
- `track` and `to` must be ids from the scene. `chip` and `banner` may use an empty track.
- Times are seconds inside the clip, from 0 to the clip duration.

## role-marker

Yellow disc under the ball carrier and a one-word role, like the DK Falcon reference.

Use this for entertainment that still teaches a role. One yellow `disc` on the player on the ball for most of the clip, with white text of one word: Striker, Winger, Full-back, Keeper, or the player's name if it is short. A second disc in another color is allowed on one defender, only while they are part of the idea. At most one yellow `arrow`, for a pass or a run, and only for a couple of seconds. Skip the explanation, or use at most 3 words. No chips, no banners, no paragraphs. Match the reference's graphic language, not its players or its match.

## telestrator

Pundit pen: one ring, then one arrow, each with its own short caption.

This is the Sky Sports / Match of the Day telestrator. The analyst talks through one picture at a time. Two beats, not a pile of graphics. Beat A: a white `ring` on one player and a bottom explanation of 4–6 words. Beat B: either move the ring to the next player or draw one `arrow` for the ball, and change the caption. Take the first graphic off before the second one is the focus. No discs, no chips, no banners.

## social-hook

Two or three huge words, timed to the action, for a short-form edit.

This is the TikTok / Reels / Shorts highlight. One `banner` of 1–3 words (WIDE, SWITCH, INTO SPACE) for about 2 seconds, on the moment it describes. One `disc` on the player those words are about, same window. No second sentence, no arrow, no chip. The banner is the whole explanation, so leave `explanation` empty.

## broadcast-strap

A clean name-and-role strap that stays out of the official lower-third.

Live broadcasts (Premier League, NBC, ESPN) keep a name on screen so the viewer knows who the clip is about. Ours is not a copy of that bug. A `ring` in white or cyan on the player, plus one bottom explanation such as "Muniz, striker" that stays up at least 3 seconds while that player is in the move. A later line may replace it for a second player. No discs, no arrows, no jokes, no stats.

## data-chip

One factual chip for the action a viewer can check by looking.

Opta, Prime Video, and analysis tools (pass maps, zone labels, pressure) put a single fact next to the picture. On this 8 second clip, one `chip` is enough. The words must name something visible: "Wide switch", "Into the box", "Cross". Do not invent xG, sprint speed, or pass completion. A `disc` or `ring` on the player the chip is about, during the same seconds. No banner, no joke, no second chip.
