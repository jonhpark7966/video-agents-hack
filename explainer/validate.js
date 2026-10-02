function norm(word) {
  return word.toLowerCase().replace(/[^a-z'-]/g, "");
}

function trackIds(play) {
  return new Set(play.tracks.map((track) => track.id));
}

export function validate(play) {
  const checks = [];
  const ids = trackIds(play);
  const tokens = play.narration.map((token, index) => ({
    key: norm(token.w),
    t: token.t,
    end: play.narration[index + 1]?.t ?? play.duration,
  }));

  for (const overlay of play.overlays) {
    for (const word of overlay.words) {
      const hit = tokens.find((token) => token.key === norm(word) && token.t >= overlay.start - 0.08 && token.t <= overlay.end + 0.08);
      checks.push({
        id: `${overlay.id}:${word}`,
        pass: Boolean(hit),
        detail: hit
          ? `"${word}" at ${hit.t.toFixed(2)}s is inside ${overlay.label}`
          : `"${word}" does not fall inside ${overlay.label}`,
      });
    }

    for (const ref of [overlay.anchor, overlay.from, overlay.to]) {
      if (typeof ref !== "string") continue;
      checks.push({
        id: `${overlay.id}:track:${ref}`,
        pass: ids.has(ref),
        detail: ids.has(ref) ? `${ref} is a tracked body` : `${ref} is not a tracked body`,
      });
    }
  }

  const labeled = [...play.overlays].sort((a, b) => a.start - b.start);
  for (let i = 1; i < labeled.length; i += 1) {
    const previous = labeled[i - 1];
    const current = labeled[i];
    const overlaps = previous.end > current.start + 0.05;
    checks.push({
      id: `overlap:${previous.id}:${current.id}`,
      pass: !overlaps,
      detail: overlaps
        ? `${previous.label} still up when ${current.label} starts`
        : `${previous.label} clears before ${current.label}`,
    });
  }

  return {
    pass: checks.every((check) => check.pass),
    checks,
  };
}
