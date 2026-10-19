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
 * grid/muted/panelBg/text stay fixed across every accent palette -- the glass
 * theme uses one neutral scale regardless of which accent is chosen (see
 * index.css). Only `accent` (and the first slot of `categorical`) varies per
 * palette, matching the --color-brass override in index.css exactly.
 * panelBg is the chart tooltip's fill: nearly opaque, so a tooltip stays
 * readable over the lines it covers.
 */
const NEUTRAL_LIGHT = { grid: "rgba(20, 26, 48, 0.10)", muted: "#5F6676", panelBg: "rgba(255, 255, 255, 0.96)", text: "#11131A" };
const NEUTRAL_DARK = { grid: "rgba(255, 255, 255, 0.08)", muted: "#8C91A0", panelBg: "rgba(22, 23, 29, 0.96)", text: "#F1F2F6" };

const CATEGORICAL_TAIL_LIGHT = [
  "#12884A", "#D33A3A", "#B0264F", "#0D9488",
  "#8B5CF6", "#D97706", "#157F3C", "#3E5C8A",
  "#BE185D", "#0891B2", "#65A30D", "#9333EA",
  "#C2410C", "#4D7C0F", "#0369A1",
];

const CATEGORICAL_TAIL_DARK = [
  "#7FE0A6", "#FF8D8D", "#F58BB0", "#6EE7D5",
  "#C4B0FF", "#FBCB6A", "#86EFAC", "#A3BCE3",
  "#F9A8D4", "#7DD3FC", "#BEF264", "#D8B4FE",
  "#FDBA74", "#A3E635", "#93C5FD",
];

const PALETTE_ACCENT: Record<string, { light: string; dark: string }> = {
  blue: { light: "#4F6BEA", dark: "#A9BCFF" },
  teal: { light: "#0D9488", dark: "#6EE7D5" },
  bordeaux: { light: "#B0264F", dark: "#F58BB0" },
  slate: { light: "#3E5C8A", dark: "#A3BCE3" },
  forest: { light: "#157F3C", dark: "#86EFAC" },
  gray: { light: "#3F3F46", dark: "#E4E4E7" },
};

export function getChartTheme(isDark: boolean, palette: string = "blue"): ChartTheme {
  const accentEntry = PALETTE_ACCENT[palette] ?? PALETTE_ACCENT.blue;
  const accent = isDark ? accentEntry.dark : accentEntry.light;
  const neutral = isDark ? NEUTRAL_DARK : NEUTRAL_LIGHT;
  const tail = isDark ? CATEGORICAL_TAIL_DARK : CATEGORICAL_TAIL_LIGHT;
  return { accent, ...neutral, categorical: [accent, ...tail] };
}
