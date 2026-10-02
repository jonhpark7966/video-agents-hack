// Reconstructed Spain pick-and-roll. Coordinates are a half court:
// x 0 = left sideline, y 0 = baseline, y 1 = half-court line.
// This is the contract the models fill. Cosmos writes `beats`.
// Tracks come from detection. Opus writes `overlays` and `narration`.

export const play = {
  id: "spain-pnr",
  title: "Spain pick-and-roll",
  duration: 12.2,
  beats: [
    { start: 0, end: 2.45, text: "The guard uses a high screen. Nothing about this action is special yet." },
    { start: 2.45, end: 5.7, text: "The second big comes from the weak side and back-screens the screener’s defender." },
    { start: 5.7, end: 7.25, text: "That second screen is the Spain. It pins the defender who was guarding the first big." },
    { start: 7.25, end: 9.7, text: "The first big leaves the screen and slips to the rim while his man is stuck." },
    { start: 9.7, end: 12.2, text: "The guard throws the pocket pass into the space the slip just opened." },
  ],
  tracks: [
    { id: "pg", team: "O", label: "PG", dim: false, keys: [
      { t: 0, x: 0.46, y: 0.8 },
      { t: 1.35, x: 0.64, y: 0.58 },
      { t: 2.4, x: 0.84, y: 0.52 },
      { t: 12.2, x: 0.84, y: 0.5 },
    ]},
    { id: "c", team: "O", label: "C", dim: false, keys: [
      { t: 0, x: 0.58, y: 0.5 },
      { t: 0.55, x: 0.68, y: 0.44 },
      { t: 6.9, x: 0.68, y: 0.44 },
      { t: 8.15, x: 0.6, y: 0.28 },
      { t: 9.15, x: 0.52, y: 0.2 },
      { t: 12.2, x: 0.52, y: 0.2 },
    ]},
    { id: "pf", team: "O", label: "PF", dim: false, keys: [
      { t: 0, x: 0.24, y: 0.62 },
      { t: 2.5, x: 0.24, y: 0.62 },
      { t: 4.4, x: 0.56, y: 0.3 },
      { t: 7.25, x: 0.56, y: 0.3 },
      { t: 9.2, x: 0.32, y: 0.24 },
      { t: 12.2, x: 0.15, y: 0.18 },
    ]},
    { id: "sg", team: "O", label: "SG", dim: true, keys: [
      { t: 0, x: 0.9, y: 0.24 },
      { t: 12.2, x: 0.9, y: 0.18 },
    ]},
    { id: "sf", team: "O", label: "SF", dim: true, keys: [
      { t: 0, x: 0.12, y: 0.22 },
      { t: 12.2, x: 0.12, y: 0.18 },
    ]},
    { id: "xpg", team: "D", label: "xPG", dim: false, keys: [
      { t: 0, x: 0.46, y: 0.7 },
      { t: 1.5, x: 0.62, y: 0.54 },
      { t: 2.6, x: 0.66, y: 0.52 },
      { t: 8.5, x: 0.74, y: 0.48 },
      { t: 12.2, x: 0.78, y: 0.46 },
    ]},
    { id: "xc", team: "D", label: "xC", dim: false, keys: [
      { t: 0, x: 0.6, y: 0.36 },
      { t: 1.1, x: 0.64, y: 0.38 },
      { t: 3.6, x: 0.62, y: 0.4 },
      { t: 12.2, x: 0.62, y: 0.4 },
    ]},
    { id: "xpf", team: "D", label: "xPF", dim: true, keys: [
      { t: 0, x: 0.18, y: 0.42 },
      { t: 12.2, x: 0.2, y: 0.32 },
    ]},
    { id: "xsg", team: "D", label: "xSG", dim: true, keys: [
      { t: 0, x: 0.8, y: 0.22 },
      { t: 12.2, x: 0.8, y: 0.16 },
    ]},
    { id: "xsf", team: "D", label: "xSF", dim: true, keys: [
      { t: 0, x: 0.2, y: 0.18 },
      { t: 12.2, x: 0.2, y: 0.16 },
    ]},
  ],
  overlays: [
    { id: "screen", type: "screen", anchor: "c", start: 0.2, end: 2.4, label: "SCREEN", words: ["screen"], labelAt: [-0.15, 0.08] },
    { id: "backscreen", type: "arrow", from: "pf", to: "xc", start: 3.45, end: 5.55, label: "BACKSCREEN", words: ["back-screens"], labelAt: [-0.12, -0.03] },
    { id: "spain", type: "callout", anchor: "pf", start: 5.8, end: 7.2, label: "SPAIN", words: ["Spain"], labelAt: [-0.13, -0.01] },
    { id: "slip", type: "trail", anchor: "c", start: 7.3, end: 9.55, label: "SLIP", words: ["slips"], labelAt: [0.08, 0.02] },
    { id: "pocket", type: "pass", from: "pg", to: "c", start: 9.7, end: 11.35, label: "POCKET", words: ["Pocket"], labelAt: [0.06, 0.04] },
  ],
  narration: [
    { t: 0.25, w: "High" },
    { t: 0.7, w: "screen." },
    { t: 1.5, w: "Ordinary." },
    { t: 2.6, w: "The" },
    { t: 2.85, w: "second" },
    { t: 3.25, w: "big" },
    { t: 3.7, w: "back-screens" },
    { t: 4.45, w: "the" },
    { t: 4.65, w: "screener's" },
    { t: 5.15, w: "defender." },
    { t: 5.9, w: "That's" },
    { t: 6.2, w: "the" },
    { t: 6.45, w: "Spain." },
    { t: 7.3, w: "The" },
    { t: 7.55, w: "first" },
    { t: 7.9, w: "big" },
    { t: 8.3, w: "slips" },
    { t: 8.7, w: "to" },
    { t: 8.9, w: "the" },
    { t: 9.15, w: "rim." },
    { t: 9.9, w: "Pocket" },
    { t: 10.4, w: "pass." },
  ],
  pass: { start: 9.85, end: 10.6, from: "pg", to: "c" },
};
