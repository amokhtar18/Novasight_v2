/**
 * Reads the active theme's CSS custom properties so ECharts series, axes, and
 * text follow the light/dark theme and the brand chart palette. Called by
 * ChartRenderer; recomputed whenever the resolved theme changes.
 */

/** Read a raw HSL-channel token (e.g. "256 90% 68%") wrapped as an hsl() color. */
function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return raw ? `hsl(${raw})` : fallback;
}

export interface ChartTheme {
  /** Categorical series palette. */
  palette: string[];
  /** Axis / label / grid text color. */
  text: string;
  /** Subtle axis line + split-line color. */
  axisLine: string;
  /** Tooltip surface + border. */
  tooltipBg: string;
  tooltipBorder: string;
}

/** Build a ChartTheme from the current document's CSS variables. */
export function readChartTheme(): ChartTheme {
  return {
    palette: [
      token("--chart-1", "hsl(256 90% 68%)"),
      token("--chart-2", "hsl(199 89% 60%)"),
      token("--chart-3", "hsl(160 64% 52%)"),
      token("--chart-4", "hsl(38 92% 60%)"),
      token("--chart-5", "hsl(330 80% 66%)"),
      token("--chart-6", "hsl(280 76% 70%)"),
      token("--chart-7", "hsl(14 84% 62%)"),
      token("--chart-8", "hsl(188 72% 54%)"),
    ],
    text: token("--muted-foreground", "hsl(217 16% 62%)"),
    axisLine: token("--border", "hsl(220 20% 18%)"),
    tooltipBg: token("--popover", "hsl(223 36% 8%)"),
    tooltipBorder: token("--border", "hsl(220 20% 18%)"),
  };
}
