export interface ChartTheme {
  accent: string;
  grid: string;
  muted: string;
  panelBg: string;
  text: string;
  /** 15-color categorical palette, accent first, for pie/bar charts with many series. */
  categorical: string[];
}

const LIGHT: ChartTheme = {
  accent: "#6B4E14",
  grid: "#C7B78D",
  muted: "#75694C",
  panelBg: "#DCCDAE",
  text: "#1F1608",
  categorical: [
    "#6B4E14", "#2F6B4A", "#9C4A2E", "#3E5F73", "#6B4E82",
    "#6B6355", "#A8862E", "#3D7A6B", "#8A5A2E", "#4A6B8A",
    "#7A4A32", "#2E6B6B", "#8A5A6B", "#6B7A3D", "#6B5A7A",
  ],
};

const DARK: ChartTheme = {
  accent: "#E3AC4E",
  grid: "#2A2015",
  muted: "#9C9080",
  panelBg: "#16110A",
  text: "#F5EFE0",
  categorical: [
    "#E3AC4E", "#5FA87D", "#D97C54", "#6E93B0", "#A98BC4",
    "#A99F82", "#D4AC5C", "#6BBBA8", "#C08A54", "#7FA3C4",
    "#B37F5C", "#5CA8A0", "#C08AA0", "#A3B87A", "#A98BB0",
  ],
};

export function getChartTheme(isDark: boolean): ChartTheme {
  return isDark ? DARK : LIGHT;
}
