export interface ChartTheme {
  accent: string;
  grid: string;
  muted: string;
  panelBg: string;
  text: string;
  /** 15-color categorical palette, accent first, for pie/bar charts with many series. */
  categorical: string[];
}

const CATEGORICAL_TAIL_LIGHT = [
  "#2F6B4A", "#9C4A2E", "#3E5F73", "#6B4E82",
  "#6B6355", "#A8862E", "#3D7A6B", "#8A5A2E", "#4A6B8A",
  "#7A4A32", "#2E6B6B", "#8A5A6B", "#6B7A3D", "#6B5A7A",
];

const CATEGORICAL_TAIL_DARK = [
  "#5FA87D", "#D97C54", "#6E93B0", "#A98BC4",
  "#A99F82", "#D4AC5C", "#6BBBA8", "#C08A54", "#7FA3C4",
  "#B37F5C", "#5CA8A0", "#C08AA0", "#A3B87A", "#A98BB0",
];

/**
 * One entry per palette (see PaletteContext), each with the exact grid/
 * muted/panelBg/text/accent values used by that palette's CSS variables in
 * index.css -- same hue-rotated colors, kept in sync by hand since Recharts
 * needs real color strings, not CSS custom properties. Only `categorical`'s
 * first slot follows the palette; the other 14 stay fixed (see
 * CATEGORICAL_TAIL_* above) rather than redesigning a full 15-color ramp
 * per palette for a marginal gain.
 */
const PALETTE_CHART_COLORS: Record<string, { light: ChartTheme; dark: ChartTheme }> = {
  brass: {
    light: { accent: "#6B4E14", grid: "#C7B78D", muted: "#75694C", panelBg: "#DCCDAE", text: "#1F1608", categorical: ["#6B4E14", ...CATEGORICAL_TAIL_LIGHT] },
    dark: { accent: "#E3AC4E", grid: "#2A2015", muted: "#9C9080", panelBg: "#16110A", text: "#F5EFE0", categorical: ["#E3AC4E", ...CATEGORICAL_TAIL_DARK] },
  },
  teal: {
    light: { accent: "#0F6E56", grid: "#8DC7B8", muted: "#4C756B", panelBg: "#AEDCD0", text: "#081F19", categorical: ["#0F6E56", ...CATEGORICAL_TAIL_LIGHT] },
    dark: { accent: "#4FBFA0", grid: "#152A24", muted: "#809C94", panelBg: "#0A1613", text: "#E0F5EF", categorical: ["#4FBFA0", ...CATEGORICAL_TAIL_DARK] },
  },
  bordeaux: {
    light: { accent: "#7A2138", grid: "#C78D9C", muted: "#754C57", panelBg: "#DCAEBA", text: "#1F080E", categorical: ["#7A2138", ...CATEGORICAL_TAIL_LIGHT] },
    dark: { accent: "#D97690", grid: "#2A151B", muted: "#9C8087", panelBg: "#160A0D", text: "#F5E0E6", categorical: ["#D97690", ...CATEGORICAL_TAIL_DARK] },
  },
  slate: {
    light: { accent: "#2E4F73", grid: "#8DA9C7", muted: "#4C6075", panelBg: "#AEC4DC", text: "#08131F", categorical: ["#2E4F73", ...CATEGORICAL_TAIL_LIGHT] },
    dark: { accent: "#7FA8D4", grid: "#151F2A", muted: "#808E9C", panelBg: "#0A1016", text: "#E0EAF5", categorical: ["#7FA8D4", ...CATEGORICAL_TAIL_DARK] },
  },
  forest: {
    light: { accent: "#3D5A1F", grid: "#AAC78D", muted: "#61754C", panelBg: "#C5DCAE", text: "#141F08", categorical: ["#3D5A1F", ...CATEGORICAL_TAIL_LIGHT] },
    dark: { accent: "#8FC15A", grid: "#202A15", muted: "#8E9C80", panelBg: "#10160A", text: "#EBF5E0", categorical: ["#8FC15A", ...CATEGORICAL_TAIL_DARK] },
  },
  gray: {
    light: { accent: "#404040", grid: "#AAAAAA", muted: "#606060", panelBg: "#C5C5C5", text: "#141414", categorical: ["#404040", ...CATEGORICAL_TAIL_LIGHT] },
    dark: { accent: "#989898", grid: "#202020", muted: "#8E8E8E", panelBg: "#101010", text: "#EBEBEB", categorical: ["#989898", ...CATEGORICAL_TAIL_DARK] },
  },
};

export function getChartTheme(isDark: boolean, palette: string = "brass"): ChartTheme {
  const entry = PALETTE_CHART_COLORS[palette] ?? PALETTE_CHART_COLORS.brass;
  return isDark ? entry.dark : entry.light;
}
