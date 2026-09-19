import type { ReactElement } from "react";
import { NavLink } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import type { ViewMode } from "../context/ViewModeContext";

export const NAV_ITEMS = [
  { to: "/", label: "Summary", icon: "summary" },
  { to: "/portfolios", label: "Portfolios", icon: "portfolios" },
  { to: "/assets", label: "Asset Catalogue", icon: "catalogue" },
  { to: "/allocation", label: "Allocation", icon: "allocation" },
  { to: "/historical-networth", label: "Historical Net Worth", icon: "history" },
  { to: "/expenses", label: "Expenses", icon: "expenses" },
  { to: "/settings", label: "Modules & Status", icon: "settings" },
] as const;

/** A small, consistent inline stroke-icon set -- 20x20, currentColor, no fills -- one per nav item, keyed by NAV_ITEMS' `icon` field. */
const NAV_ICON_PATHS: Record<string, ReactElement> = {
  summary: <path d="M10 2 L18 10 L10 18 L2 10 Z" />,
  portfolios: (
    <>
      <path d="M10 3 L17 7 L10 11 L3 7 Z" />
      <path d="M3 11 L10 15 L17 11" />
    </>
  ),
  catalogue: (
    <>
      <rect x="3" y="3" width="6" height="6" rx="1.2" />
      <rect x="11" y="3" width="6" height="6" rx="1.2" />
      <rect x="3" y="11" width="6" height="6" rx="1.2" />
      <rect x="11" y="11" width="6" height="6" rx="1.2" />
    </>
  ),
  allocation: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 3 A7 7 0 0 1 17 10" />
    </>
  ),
  history: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6 V10 L13 12" />
    </>
  ),
  expenses: (
    <>
      <rect x="2.5" y="5" width="15" height="11" rx="2" />
      <path d="M2.5 8.5 H17.5" />
      <path d="M15 10.4 V13.4 M13.5 11.9 H16.5" />
    </>
  ),
  settings: (
    <>
      <circle cx="10" cy="10" r="3" />
      <path d="M10 2 V5 M10 15 V18 M2 10 H5 M15 10 H18 M4.6 4.6 L6.5 6.5 M13.5 13.5 L15.4 15.4 M4.6 15.4 L6.5 13.5 M13.5 6.5 L15.4 4.6" />
    </>
  ),
};

function NavIcon({ name }: { name: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {NAV_ICON_PATHS[name]}
    </svg>
  );
}

interface SidebarProps {
  /** Current layout mode. */
  viewMode: ViewMode;
  /** Flips between "desktop" and "mobile" layout. */
  onToggleViewMode: () => void;
  /**
   * Only relevant in mobile mode: whether the drawer is currently open.
   * Ignored (sidebar always visible) in desktop mode.
   */
  drawerOpen?: boolean;
  /** Called when a nav link is clicked or the overlay is dismissed, to close the drawer. */
  onCloseDrawer?: () => void;
}

export default function Sidebar({ viewMode, onToggleViewMode, drawerOpen, onCloseDrawer }: SidebarProps) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  const isMobile = viewMode === "mobile";

  const asideClasses = isMobile
    ? `fixed inset-y-0 left-0 z-50 w-72 border-r ledger-rule bg-panel flex flex-col h-screen transition-transform duration-200 ease-out ${
        drawerOpen ? "translate-x-0" : "-translate-x-full"
      }`
    : "w-64 shrink-0 border-r ledger-rule bg-panel flex flex-col h-screen sticky top-0";

  return (
    <>
      {isMobile && (
        <div
          onClick={onCloseDrawer}
          aria-hidden="true"
          className={`fixed inset-0 z-40 bg-black/50 transition-opacity duration-200 ${
            drawerOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
          }`}
        />
      )}

      <aside className={asideClasses}>
        <div className="flex items-center gap-2.5 px-6 py-6">
          <svg width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="var(--color-brass)" strokeWidth="2" aria-hidden="true">
            <path d="M10 2 L18 10 L10 18 L2 10 Z" />
          </svg>
          <span className="font-display font-extrabold text-base tracking-tight">Net Worth Suite</span>
        </div>

        <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={onCloseDrawer}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors ${
                  isActive
                    ? "bg-brass-soft text-brass font-semibold"
                    : "text-ink-text/75 font-medium hover:bg-ink-raised hover:text-ink-text"
                }`
              }
            >
              <NavIcon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="px-3 pb-3 space-y-2">
          <button
            onClick={toggleTheme}
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl border ledger-rule text-sm text-ink-text/80 hover:bg-ink-raised transition-colors"
          >
            <span className="flex items-center gap-2">
              {isDark ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
              )}
              {isDark ? "Dark mode" : "Light mode"}
            </span>
            <span className="relative w-8 h-4 rounded-full bg-ink-raised border ledger-rule shrink-0">
              <span
                className={`absolute top-0.5 w-3 h-3 rounded-full bg-brass transition-all ${
                  isDark ? "left-4" : "left-0.5"
                }`}
              />
            </span>
          </button>

          <button
            onClick={onToggleViewMode}
            aria-label={isMobile ? "Switch to desktop layout" : "Switch to mobile layout"}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl border ledger-rule text-sm text-ink-text/80 hover:bg-ink-raised transition-colors"
          >
            <span className="flex items-center gap-2">
              {isMobile ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="12" rx="1" /><path d="M8 20h8M12 16v4" /></svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="7" y="2" width="10" height="20" rx="2" /><path d="M11 18h2" /></svg>
              )}
              {isMobile ? "Desktop layout" : "Mobile layout"}
            </span>
          </button>
        </div>

        <div className="px-6 py-4 border-t ledger-rule text-xs text-muted">
          Runs locally · your data stays private
        </div>
      </aside>
    </>
  );
}
