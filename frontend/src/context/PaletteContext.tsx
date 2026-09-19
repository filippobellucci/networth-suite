import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Palette = "blue" | "teal" | "bordeaux" | "slate" | "forest" | "gray";

export const PALETTES: { id: Palette; label: string; swatchLight: string; swatchDark: string }[] = [
  { id: "blue", label: "Blue", swatchLight: "#2954FF", swatchDark: "#6E8CFF" },
  { id: "teal", label: "Teal", swatchLight: "#0D9488", swatchDark: "#2DD4BF" },
  { id: "bordeaux", label: "Bordeaux", swatchLight: "#B0264F", swatchDark: "#F0679A" },
  { id: "slate", label: "Slate", swatchLight: "#3E5C8A", swatchDark: "#8FADDD" },
  { id: "forest", label: "Forest", swatchLight: "#157F3C", swatchDark: "#4ADE80" },
  { id: "gray", label: "Gray", swatchLight: "#3F3F46", swatchDark: "#D4D4D8" },
];

interface PaletteContextValue {
  palette: Palette;
  setPalette: (p: Palette) => void;
}

const PaletteContext = createContext<PaletteContextValue>({
  palette: "blue",
  setPalette: () => {},
});

function getInitialPalette(): Palette {
  const stored = localStorage.getItem("palette");
  if (stored && PALETTES.some((p) => p.id === stored)) return stored as Palette;
  return "blue";
}

export function PaletteProvider({ children }: { children: ReactNode }) {
  const [palette, setPalette] = useState<Palette>(getInitialPalette);

  useEffect(() => {
    // "blue" is the default -- no attribute needed, since index.css's base
    // @theme values already are blue. Only a non-default choice needs the
    // attribute that activates its override block.
    if (palette === "blue") {
      document.documentElement.removeAttribute("data-palette");
    } else {
      document.documentElement.setAttribute("data-palette", palette);
    }
    localStorage.setItem("palette", palette);
  }, [palette]);

  return <PaletteContext.Provider value={{ palette, setPalette }}>{children}</PaletteContext.Provider>;
}

export function usePalette() {
  return useContext(PaletteContext);
}
