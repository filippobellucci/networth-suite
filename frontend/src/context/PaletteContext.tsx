import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Palette = "brass" | "teal" | "bordeaux" | "slate" | "forest" | "gray";

export const PALETTES: { id: Palette; label: string; swatchLight: string; swatchDark: string }[] = [
  { id: "brass", label: "Brass", swatchLight: "#6B4E14", swatchDark: "#E3AC4E" },
  { id: "teal", label: "Teal", swatchLight: "#0F6E56", swatchDark: "#4FBFA0" },
  { id: "bordeaux", label: "Bordeaux", swatchLight: "#7A2138", swatchDark: "#D97690" },
  { id: "slate", label: "Slate Blue", swatchLight: "#2E4F73", swatchDark: "#7FA8D4" },
  { id: "forest", label: "Forest", swatchLight: "#3D5A1F", swatchDark: "#8FC15A" },
  { id: "gray", label: "Gray", swatchLight: "#404040", swatchDark: "#989898" },
];

interface PaletteContextValue {
  palette: Palette;
  setPalette: (p: Palette) => void;
}

const PaletteContext = createContext<PaletteContextValue>({
  palette: "brass",
  setPalette: () => {},
});

function getInitialPalette(): Palette {
  const stored = localStorage.getItem("palette");
  if (stored && PALETTES.some((p) => p.id === stored)) return stored as Palette;
  return "brass";
}

export function PaletteProvider({ children }: { children: ReactNode }) {
  const [palette, setPalette] = useState<Palette>(getInitialPalette);

  useEffect(() => {
    // "brass" is the original, unstyled default -- no attribute needed,
    // since index.css's base @theme values already are brass. Only a
    // non-default choice needs the attribute that activates its override
    // block.
    if (palette === "brass") {
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
