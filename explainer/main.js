import { play } from "./play.js";
import { validate } from "./validate.js";

const canvas = document.querySelector("#court");
const ctx = canvas.getContext("2d");
const wordsEl = document.querySelector("#words");
const beatEl = document.querySelector("#beat");
const checksEl = document.querySelector("#checks");
const playButton = document.querySelector("#play");
const scrub = document.querySelector("#scrub");
const fill = document.querySelector("#fill");
const timeEl = document.querySelector("#time");

const params = new URLSearchParams(location.search);
const report = validate(play);

let t = Number(params.get("t") ?? 0);
let playing = params.get("still") === "1" ? false : true;
let last = performance.now();

const tracks = new Map(play.tracks.map((track) => [track.id, track]));

function sample(keys, time) {
  if (time <= keys[0].t) return keys[0];
  for (let i = 1; i < keys.length; i += 1) {
    if (time <= keys[i].t) {
      const a = keys[i - 1];
      const b = keys[i];
      const u = (time - a.t) / (b.t - a.t);
      const e = u * u * (3 - 2 * u);
      return { x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e };
    }
  }
  return keys[keys.length - 1];
}

function at(id, time) {
  return sample(tracks.get(id).keys, time);
}

function layout() {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
}

function courtGeom() {
  const pad = canvas.width * 0.045;
  const width = canvas.width - pad * 2;
  const height = canvas.height - pad * 2;
  return {
    pad,
    width,
    height,
    px(x, y) {
      return { x: pad + x * width, y: pad + y * height };
    },
    feet(xf, yf) {
      return { x: pad + (xf / 50) * width, y: pad + (yf / 47) * height };
    },
  };
}

function drawCourt(g) {
  ctx.fillStyle = "#14261c";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#183226";
  const lane = [g.feet(17, 0), g.feet(33, 19)];
  ctx.fillRect(lane[0].x, lane[0].y, lane[1].x - lane[0].x, lane[1].y - lane[0].y);

  ctx.strokeStyle = "rgba(232, 236, 230, 0.78)";
  ctx.lineWidth = Math.max(2, canvas.width * 0.0022);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.setLineDash([]);

  const outerA = g.feet(0, 0);
  const outerB = g.feet(50, 47);
  ctx.strokeRect(outerA.x, outerA.y, outerB.x - outerA.x, outerB.y - outerA.y);
  ctx.strokeRect(lane[0].x, lane[0].y, lane[1].x - lane[0].x, lane[1].y - lane[0].y);

  const boardA = g.feet(22, 4);
  const boardB = g.feet(28, 4);
  ctx.beginPath();
  ctx.moveTo(boardA.x, boardA.y);
  ctx.lineTo(boardB.x, boardB.y);
  ctx.stroke();

  strokeCircleFeet(g, 25, 5.25, 0.75);
  const rim = g.feet(25, 5.25);
  ctx.beginPath();
  ctx.arc(rim.x, rim.y, Math.max(5, canvas.width * 0.011), 0, Math.PI * 2);
  ctx.fillStyle = "#f27a2a";
  ctx.fill();
  strokeArcFeet(g, 25, 5.25, 4, Math.PI * 0.15, Math.PI * 0.85);

  ctx.beginPath();
  traceArc(g, 25, 19, 6, 0, Math.PI);
  ctx.stroke();
  ctx.setLineDash([canvas.width * 0.008, canvas.width * 0.007]);
  ctx.beginPath();
  traceArc(g, 25, 19, 6, Math.PI, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);

  const breakY = 5.25 + Math.sqrt(23.75 ** 2 - 22 ** 2);
  ctx.beginPath();
  const leftTop = g.feet(3, 0);
  const leftBreak = g.feet(3, breakY);
  const rightTop = g.feet(47, 0);
  const rightBreak = g.feet(47, breakY);
  ctx.moveTo(leftTop.x, leftTop.y);
  ctx.lineTo(leftBreak.x, leftBreak.y);
  ctx.moveTo(rightTop.x, rightTop.y);
  ctx.lineTo(rightBreak.x, rightBreak.y);
  ctx.stroke();

  const leftAngle = Math.atan2(breakY - 5.25, 3 - 25);
  const rightAngle = Math.atan2(breakY - 5.25, 47 - 25);
  ctx.beginPath();
  traceArc(g, 25, 5.25, 23.75, rightAngle, leftAngle);
  ctx.stroke();

  ctx.beginPath();
  const halfA = g.feet(0, 47);
  const halfB = g.feet(50, 47);
  ctx.moveTo(halfA.x, halfA.y);
  ctx.lineTo(halfB.x, halfB.y);
  ctx.stroke();
}

function traceArc(g, cx, cy, r, a0, a1, steps = 48) {
  for (let i = 0; i <= steps; i += 1) {
    const a = a0 + ((a1 - a0) * i) / steps;
    const p = g.feet(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
}

function strokeCircleFeet(g, cx, cy, r) {
  ctx.beginPath();
  traceArc(g, cx, cy, r, 0, Math.PI * 2);
  ctx.stroke();
}

function strokeArcFeet(g, cx, cy, r, a0, a1) {
  ctx.beginPath();
  traceArc(g, cx, cy, r, a0, a1);
  ctx.stroke();
}

function drawPlayers(g, time) {
  const order = [...play.tracks].sort((a, b) => Number(a.dim) - Number(b.dim));
  for (const track of order) {
    const p = g.px(sample(track.keys, time).x, sample(track.keys, time).y);
    const radius = canvas.width * (track.dim ? 0.015 : 0.022);
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.globalAlpha = track.dim ? 0.45 : 1;
    if (track.team === "O") {
      ctx.fillStyle = "#f4f1ea";
      ctx.fill();
      ctx.fillStyle = "#17211b";
    } else {
      ctx.lineWidth = Math.max(2, radius * 0.18);
      ctx.strokeStyle = "#ff5a45";
      ctx.stroke();
      ctx.fillStyle = "#ffb0a6";
    }
    ctx.font = `700 ${Math.round(radius * 0.78)}px "Avenir Next Condensed", "Arial Narrow", sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(track.label, p.x, p.y + radius * 0.04);
    ctx.globalAlpha = 1;
  }
}

function drawBall(g, time) {
  const pass = play.pass;
  const from = at(pass.from, pass.start);
  const to = at(pass.to, pass.end);
  let point;
  if (time < pass.start) point = { x: at("pg", time).x + 0.02, y: at("pg", time).y };
  else if (time > pass.end) point = { x: at("c", time).x + 0.02, y: at("c", time).y };
  else {
    const u = (time - pass.start) / (pass.end - pass.start);
    const e = u * u * (3 - 2 * u);
    point = {
      x: from.x + (to.x - from.x) * e,
      y: from.y + (to.y - from.y) * e - Math.sin(Math.PI * u) * 0.035,
    };
  }
  const p = g.px(point.x, point.y);
  const radius = canvas.width * 0.008;
  ctx.beginPath();
  ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
  ctx.fillStyle = "#ff8a2a";
  ctx.fill();
  ctx.strokeStyle = "#7a3a10";
  ctx.lineWidth = Math.max(1, radius * 0.25);
  ctx.stroke();
}

function activeOverlays(time) {
  return play.overlays.filter((overlay) => time >= overlay.start && time <= overlay.end);
}

function drawOverlays(g, time) {
  for (const overlay of activeOverlays(time)) {
    const age = time - overlay.start;
    const draw = Math.min(1, age / 0.35);
    ctx.strokeStyle = "#ffd84a";
    ctx.fillStyle = "#ffd84a";
    ctx.lineWidth = Math.max(3, canvas.width * 0.0035);
    if (overlay.type === "screen") drawScreen(g, overlay, time);
    if (overlay.type === "arrow") drawArrow(g, overlay, at(overlay.from, time), at(overlay.to, time), draw);
    if (overlay.type === "trail") drawTrail(g, overlay, time, draw);
    if (overlay.type === "pass") drawPass(g, overlay, time, draw);
    if (overlay.type === "callout") {
      ring(g, overlay.anchor, time);
      const body = at(overlay.anchor, time);
      const p = labelPoint(g, body.x, body.y, overlay);
      pill(p.x, p.y, overlay.label);
    }
  }
}

function labelPoint(g, x, y, overlay) {
  const [dx, dy] = overlay.labelAt ?? [0, -0.06];
  return g.px(x + dx, y + dy);
}

function ring(g, id, time) {
  const p = g.px(at(id, time).x, at(id, time).y);
  ctx.beginPath();
  ctx.arc(p.x, p.y, canvas.width * 0.03, 0, Math.PI * 2);
  ctx.stroke();
}

function segment(g, from, to) {
  const a = g.px(from.x, from.y);
  const b = g.px(to.x, to.y);
  const ang = Math.atan2(b.y - a.y, b.x - a.x);
  const dist = Math.hypot(b.x - a.x, b.y - a.y);
  const pad = Math.min(canvas.width * 0.024, dist * 0.28);
  return {
    a: { x: a.x + Math.cos(ang) * pad, y: a.y + Math.sin(ang) * pad },
    b: { x: b.x - Math.cos(ang) * pad, y: b.y - Math.sin(ang) * pad },
    ang,
  };
}

function drawScreen(g, overlay, time) {
  const c = at(overlay.anchor, time);
  const pg = at("pg", time);
  const ang = Math.atan2(pg.y - c.y, pg.x - c.x);
  const wall = { x: c.x + Math.cos(ang) * 0.028, y: c.y + Math.sin(ang) * 0.028 };
  ring(g, overlay.anchor, time);
  const angle = ang + Math.PI / 2;
  const center = g.px(wall.x, wall.y);
  const length = canvas.width * 0.032;
  ctx.save();
  ctx.translate(center.x, center.y);
  ctx.rotate(angle);
  ctx.lineWidth = Math.max(7, canvas.width * 0.008);
  ctx.beginPath();
  ctx.moveTo(-length, 0);
  ctx.lineTo(length, 0);
  ctx.stroke();
  ctx.restore();
  const p = labelPoint(g, c.x, c.y, overlay);
  pill(p.x, p.y, overlay.label);
}

function drawArrow(g, overlay, from, to, draw) {
  const line = segment(g, from, to);
  const mx = line.a.x + (line.b.x - line.a.x) * draw;
  const my = line.a.y + (line.b.y - line.a.y) * draw;
  ctx.beginPath();
  ctx.moveTo(line.a.x, line.a.y);
  ctx.lineTo(mx, my);
  ctx.stroke();
  if (draw > 0.85) head(mx, my, line.ang);
  if (draw > 0.4) {
    const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
    const p = labelPoint(g, mid.x, mid.y, overlay);
    pill(p.x, p.y, overlay.label);
  }
}

function drawTrail(g, overlay, time, draw) {
  const start = at(overlay.anchor, overlay.start);
  const now = at(overlay.anchor, overlay.start + (time - overlay.start));
  const line = segment(g, start, now);
  const mx = line.a.x + (line.b.x - line.a.x) * draw;
  const my = line.a.y + (line.b.y - line.a.y) * draw;
  ctx.beginPath();
  ctx.moveTo(line.a.x, line.a.y);
  ctx.lineTo(mx, my);
  ctx.stroke();
  if (draw > 0.85) head(mx, my, line.ang);
  const p = labelPoint(g, now.x, now.y, overlay);
  pill(p.x, p.y, overlay.label);
}

function drawPass(g, overlay, time, draw) {
  const from = at(overlay.from, play.pass.start);
  const to = at(overlay.to, Math.min(time, play.pass.end));
  const line = segment(g, from, to);
  const mx = line.a.x + (line.b.x - line.a.x) * draw;
  const my = line.a.y + (line.b.y - line.a.y) * draw;
  ctx.setLineDash([canvas.width * 0.012, canvas.width * 0.008]);
  ctx.beginPath();
  ctx.moveTo(line.a.x, line.a.y);
  ctx.lineTo(mx, my);
  ctx.stroke();
  ctx.setLineDash([]);
  if (draw > 0.85) head(mx, my, line.ang);
  const mid = {
    x: from.x + (to.x - from.x) * 0.45,
    y: from.y + (to.y - from.y) * 0.45,
  };
  const p = labelPoint(g, mid.x, mid.y, overlay);
  pill(p.x, p.y, overlay.label);
}

function head(x, y, angle) {
  const size = canvas.width * 0.014;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(-size, size * 0.55);
  ctx.lineTo(-size, -size * 0.55);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function pill(x, y, text) {
  ctx.font = `700 ${Math.round(canvas.width * 0.016)}px "Avenir Next Condensed", "Arial Narrow", sans-serif`;
  const padX = canvas.width * 0.008;
  const height = canvas.width * 0.026;
  const width = ctx.measureText(text).width + padX * 2;
  ctx.fillStyle = "#ffd84a";
  ctx.fillRect(x - width / 2, y - height / 2, width, height);
  ctx.fillStyle = "#1c1604";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 1);
}

function renderWords(time) {
  const current = play.narration.findIndex((token, index) => {
    const end = play.narration[index + 1]?.t ?? play.duration;
    return time >= token.t && time < end;
  });
  wordsEl.replaceChildren();
  play.narration.forEach((token, index) => {
    const span = document.createElement("span");
    span.className = "word";
    if (current === index) span.classList.add("now");
    else if (current > index) span.classList.add("said");
    span.textContent = `${token.w} `;
    wordsEl.appendChild(span);
    if (/[.]$/.test(token.w)) {
      const br = document.createElement("span");
      br.className = "break";
      wordsEl.appendChild(br);
    }
  });
}

function renderBeat(time) {
  const beat = play.beats.find((item) => time >= item.start && time < item.end) ?? play.beats.at(-1);
  beatEl.textContent = beat.text;
}

function renderChecks() {
  checksEl.replaceChildren();
  for (const check of report.checks.filter((item) => item.id.includes(":") && !item.id.startsWith("overlap") && !item.id.includes(":track:"))) {
    const li = document.createElement("li");
    if (!check.pass) li.classList.add("miss");
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = check.pass ? "OK" : "MISS";
    li.append(mark, document.createTextNode(check.detail));
    checksEl.appendChild(li);
  }
}

function renderScrub() {
  const pct = (t / play.duration) * 100;
  fill.style.width = `${pct}%`;
  timeEl.textContent = `${t.toFixed(2)} / ${play.duration.toFixed(1)}`;
  scrub.setAttribute("aria-valuenow", t.toFixed(2));
  playButton.textContent = playing ? "Pause" : "Play";
}

function frame(now) {
  if (playing) {
    const dt = Math.min(0.05, (now - last) / 1000);
    t += dt;
    if (t >= play.duration) t = 0;
  }
  last = now;
  const g = courtGeom();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawCourt(g);
  drawPlayers(g, t);
  drawOverlays(g, t);
  drawBall(g, t);
  renderWords(t);
  renderBeat(t);
  renderScrub();
  if (playing) requestAnimationFrame(frame);
}

playButton.addEventListener("click", () => {
  playing = !playing;
  last = performance.now();
  if (playing) requestAnimationFrame(frame);
  else playButton.textContent = "Play";
});

scrub.addEventListener("pointerdown", (event) => {
  const seek = (clientX) => {
    const rect = scrub.getBoundingClientRect();
    t = Math.min(play.duration, Math.max(0, ((clientX - rect.left) / rect.width) * play.duration));
    if (!playing) {
      last = performance.now();
      window.__drewStill = false;
      frame(last);
    }
  };
  seek(event.clientX);
  const move = (ev) => seek(ev.clientX);
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
});

window.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || event.target instanceof HTMLInputElement) return;
  event.preventDefault();
  playButton.click();
});

window.addEventListener("resize", () => {
  layout();
  if (!playing) frame(performance.now());
});

for (const overlay of play.overlays) {
  const tick = document.createElement("div");
  tick.className = "tick";
  tick.style.left = `${(overlay.start / play.duration) * 100}%`;
  tick.title = overlay.label;
  scrub.appendChild(tick);
}

renderChecks();
layout();
requestAnimationFrame(frame);
