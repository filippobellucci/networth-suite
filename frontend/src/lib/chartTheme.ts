export interface ChartTheme {
  accent: string;
  grid: string;
  muted: string;
  panelBg: string;
  text: string;
  /** 15-color categorical palette, accent first, for pie/bar charts with many series. */
  categorical: string[];
}

/**
 * grid/muted/panelBg/text stay fixed across every accent palette -- the
 * "Minimal Fintech" theme uses a single neutral gray/white scale regardless
 * of which accent is chosen (see index.css), unlike the old scheme where
 * the whole background hue rotated with the palette. Only `accent` (and the
 * first slot of `categorical`) varies per palette, matching the
 * --color-brass override in index.css exactly.
 */
const NEUTRAL_LIGHT = { grid: "#E5E3DD", muted: "#6B7280", panelBg: "#FFFFFF", text: "#15171B" };
const NEUTRAL_DARK = { grid: "#24262B", muted: "#8B93A0", panelBg: "#131417", text: "#ECEDEF" };

const CATEGORICAL_TAIL_LIGHT = [
  "#178A45", "#DC2626", "#B0264F", "#0D9488",
  "#8B5CF6", "#D97706", "#157F3C", "#3E5C8A",
  "#BE185D", "#0891B2", "#65A30D", "#9333EA",
  "#C2410C", "#4D7C0F", "#0369A1",
];

const CATEGORICAL_TAIL_DARK = [
  "#34D399", "#F87171", "#F0679A", "#2DD4BF",
  "#A78BFA", "#FBBF24", "#4ADE80", "#8FADDD",
  "#F472B6", "#22D3EE", "#A3E635", "#C084FC",
  "#FB923C", "#A3E635", "#38BDF8",
];

const PALETTE_ACCENT: Record<string, { light: string; dark: string }> = {
  blue: { light: "#2954FF", dark: "#6E8CFF" },
  teal: { light: "#0D9488", dark: "#2DD4BF" },
  bordeaux: { light: "#B0264F", dark: "#F0679A" },
  slate: { light: "#3E5C8A", dark: "#8FADDD" },
  forest: { light: "#157F3C", dark: "#4ADE80" },
  gray: { light: "#3F3F46", dark: "#D4D4D8" },
};

export function getChartTheme(isDark: boolean, palette: string = "blue"): ChartTheme {
  const accentEntry = PALETTE_ACCENT[palette] ?? PALETTE_ACCENT.blue;
  const accent = isDark ? accentEntry.dark : accentEntry.light;
  const neutral = isDark ? NEUTRAL_DARK : NEUTRAL_LIGHT;
  const tail = isDark ? CATEGORICAL_TAIL_DARK : CATEGORICAL_TAIL_LIGHT;
  return { accent, ...neutral, categorical: [accent, ...tail] };
}
