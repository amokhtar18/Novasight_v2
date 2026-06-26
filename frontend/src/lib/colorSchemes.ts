/**
 * Named colour palettes for charts.
 *
 * Each entry is a hex colour array that maps to an ECharts `color` option.
 * These are UI display affordances — no environment or tenant specifics.
 *
 * `SharedFormatControls` builds its colour-scheme dropdown from
 * `Object.keys(COLOR_SCHEMES)` so the two places are always in sync.
 */
export const COLOR_SCHEMES: Record<string, string[]> = {
  default: [
    "#5470c6",
    "#91cc75",
    "#fac858",
    "#ee6666",
    "#73c0de",
    "#3ba272",
    "#fc8452",
    "#9a60b4",
    "#ea7ccc",
  ],
  vibrant: [
    "#e6194b",
    "#3cb44b",
    "#ffe119",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#bfef45",
    "#fabed4",
  ],
  cool: [
    "#4e79a7",
    "#59a14f",
    "#9c755f",
    "#f28e2b",
    "#edc948",
    "#bab0ac",
    "#76b7b2",
    "#e15759",
    "#499894",
    "#b07aa1",
  ],
  warm: [
    "#e15759",
    "#f28e2b",
    "#edc948",
    "#ff9da7",
    "#d37295",
    "#b5a642",
    "#9e765f",
    "#b6992d",
    "#499894",
    "#86bcb6",
  ],
  pastel: [
    "#aec6e8",
    "#ffb55a",
    "#ffee65",
    "#bde0a8",
    "#ff9699",
    "#d4a5cb",
    "#ddb27c",
    "#88ba77",
    "#fdbf6f",
    "#cab2d6",
  ],
};
