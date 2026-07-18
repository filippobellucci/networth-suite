import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Summary", icon: "◆" },
  { to: "/portfolios", label: "Portfolios", icon: "▤" },
  { to: "/assets", label: "Asset Catalogue", icon: "◈" },
  { to: "/geo-allocation", label: "Geographic Allocation", icon: "◐" },
  { to: "/pension", label: "Pension Fund", icon: "◇" },
  { to: "/settings", label: "Modules & Status", icon: "⚙" },
];

export default function Sidebar() {
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

      <div className="px-6 py-4 border-t ledger-rule text-xs text-muted">
        Runs locally · your data stays private
      </div>
    </aside>
  );
}
