import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Palette = "blue" | "teal" | "bordeaux" | "slate" | "forest" | "gray";

export const PALETTES: { id: Palette; label: string; swatchLight: string; swatchDark: string }[] = [
  { id: "blue", label: "Periwinkle", swatchLight: "#4F6BEA", swatchDark: "#A9BCFF" },
  { id: "teal", label: "Teal", swatchLight: "#0D9488", swatchDark: "#6EE7D5" },
  { id: "bordeaux", label: "Rose", swatchLight: "#B0264F", swatchDark: "#F58BB0" },
  { id: "slate", label: "Slate", swatchLight: "#3E5C8A", swatchDark: "#A3BCE3" },
  { id: "forest", label: "Mint", swatchLight: "#157F3C", swatchDark: "#86EFAC" },
  { id: "gray", label: "Mono", swatchLight: "#3F3F46", swatchDark: "#E4E4E7" },
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
