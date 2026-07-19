import { NavLink } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";

const NAV_ITEMS = [
  { to: "/", label: "Summary", icon: "◆" },
  { to: "/portfolios", label: "Portfolios", icon: "▤" },
  { to: "/assets", label: "Asset Catalogue", icon: "◈" },
  { to: "/portfolio-allocation", label: "Portfolio Allocation", icon: "◑" },
  { to: "/geo-allocation", label: "Geographic Allocation", icon: "◐" },
  { to: "/historical-networth", label: "Historical Net Worth", icon: "◫" },
  { to: "/settings", label: "Modules & Status", icon: "⚙" },
];

export default function Sidebar() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <aside className="w-64 shrink-0 border-r ledger-rule bg-panel/40 flex flex-col h-screen sticky top-0">
      <div className="px-6 py-6 border-b ledger-rule">
        <div className="flex items-baseline gap-2">
          <span className="text-brass font-display text-2xl">Ledger</span>
        </div>
        <p className="text-muted text-xs mt-1 tracking-wide uppercase">Net Worth Suite</p>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
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

      <div className="px-3 pb-3">
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
      </div>

      <div className="px-6 py-4 border-t ledger-rule text-xs text-muted">
        Runs locally · your data stays private
      </div>
    </aside>
  );
}
