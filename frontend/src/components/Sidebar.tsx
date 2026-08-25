import { NavLink } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import type { ViewMode } from "../App";

export const NAV_ITEMS = [
  { to: "/", label: "Summary", icon: "◆" },
  { to: "/portfolios", label: "Portfolios", icon: "▤" },
  { to: "/assets", label: "Asset Catalogue", icon: "◈" },
  { to: "/portfolio-allocation", label: "Portfolio Allocation", icon: "◑" },
  { to: "/currency-exposure", label: "Currency Exposure", icon: "◒" },
  { to: "/geo-allocation", label: "Geographic Allocation", icon: "◐" },
  { to: "/historical-networth", label: "Historical Net Worth", icon: "◫" },
  { to: "/transactions", label: "Transactions", icon: "✚" },
  { to: "/expense-categories", label: "Expense Categories", icon: "▥" },
  { to: "/expense-history", label: "Expense History", icon: "◧" },
  { to: "/settings", label: "Modules & Status", icon: "⚙" },
];

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
    ? `fixed inset-y-0 left-0 z-50 w-72 border-r ledger-rule bg-ink flex flex-col h-screen transition-transform duration-200 ease-out ${
        drawerOpen ? "translate-x-0" : "-translate-x-full"
      }`
    : "w-64 shrink-0 border-r ledger-rule bg-panel/40 flex flex-col h-screen sticky top-0";

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
        <div className="px-6 py-6 border-b ledger-rule">
          <div className="flex items-baseline gap-2">
            <span className="text-brass font-display text-2xl">Ledger</span>
          </div>
          <p className="text-muted text-xs mt-1 tracking-wide uppercase">Net Worth Suite</p>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={onCloseDrawer}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors ${
                  isActive
                    ? "bg-ink-raised text-brass border border-panel-hairline"
                    : "text-ink-text/80 hover:bg-ink-raised/60 hover:text-ink-text"
                }`
              }
            >
              <span className="text-brass-dim">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="px-3 pb-3 space-y-2">
          <button
            onClick={toggleTheme}
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            className="w-full flex items-center justify-between px-3 py-2 rounded border ledger-rule text-sm text-ink-text/80 hover:bg-ink-raised/60 transition-colors"
          >
            <span className="flex items-center gap-2">
              {isDark ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
                </svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
                </svg>
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
            className="w-full flex items-center justify-between px-3 py-2 rounded border ledger-rule text-sm text-ink-text/80 hover:bg-ink-raised/60 transition-colors"
          >
            <span className="flex items-center gap-2">
              {isMobile ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="4" width="18" height="12" rx="1" />
                  <path d="M8 20h8M12 16v4" />
                </svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="7" y="2" width="10" height="20" rx="2" />
                  <path d="M11 18h2" />
                </svg>
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
