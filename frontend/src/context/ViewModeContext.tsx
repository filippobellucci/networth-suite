import { createContext, useContext, type ReactNode } from "react";

export type ViewMode = "desktop" | "mobile";

const ViewModeContext = createContext<ViewMode>("desktop");

export function ViewModeProvider({ value, children }: { value: ViewMode; children: ReactNode }) {
  return <ViewModeContext.Provider value={value}>{children}</ViewModeContext.Provider>;
}

/** True on mobile layout — the single source of truth pages should check. */
export function useIsMobile() {
  return useContext(ViewModeContext) === "mobile";
}
