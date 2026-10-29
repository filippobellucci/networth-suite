import { useState, type ReactElement } from "react";
import { Link, NavLink, matchPath, useLocation, useNavigate } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import { usePortfolio } from "../context/PortfolioContext";
import type { ViewMode } from "../context/ViewModeContext";

interface NavItem {
  to: string;
  label: string;
}

interface NavGroup {
  id: string;
  label: string;
  icon: string;
  items: NavItem[];
}

/**
 * The app's sections, grouped by what the user is doing: looking at the whole
 * picture (Summary), managing what they own (Wealth), analysing it over time
 * and by composition (Insights), tracking money in and out (Cash flow), and
 * the system itself. The routes themselves are unchanged; only the grouping
 * is a navigation concern.
 */
const NAV_GROUPS: NavGroup[] = [
  { id: "summary", label: "Summary", icon: "summary", items: [{ to: "/", label: "Summary" }] },
  {
    id: "wealth",
    label: "Wealth",
    icon: "wealth",
    items: [
      { to: "/portfolios", label: "Portfolios" },
      { to: "/assets", label: "Asset Catalogue" },
    ],
  },
  {
    id: "insights",
    label: "Insights",
    icon: "insights",
    items: [
      { to: "/historical-networth", label: "Historical Net Worth" },
      { to: "/allocation", label: "Allocation" },
    ],
  },
  { id: "cashflow", label: "Cash flow", icon: "cashflow", items: [{ to: "/expenses", label: "Expenses" }] },
  { id: "system", label: "System", icon: "system", items: [{ to: "/settings", label: "Modules & Status" }] },
];

/** "/" matches only itself; every other item also owns its detail pages (/portfolios/:id). */
function itemMatches(item: NavItem, pathname: string) {
  return matchPath({ path: item.to, end: item.to === "/" }, pathname) !== null;
}

/** The group the current route belongs to (Summary when nothing matches). */
function useActiveGroup(): NavGroup {
  const { pathname } = useLocation();
  return NAV_GROUPS.find((g) => g.items.some((i) => itemMatches(i, pathname))) ?? NAV_GROUPS[0];
}

/** A small, consistent inline stroke-icon set -- 24x24, currentColor, no fills. */
const ICON_PATHS: Record<string, ReactElement> = {
  summary: (
    <>
      <path d="M3.5 10.5 12 4l8.5 6.5" />
      <path d="M5.5 9v10.5h13V9" />
      <path d="M10 19.5v-5h4v5" />
    </>
  ),
  wealth: (
    <>
      <path d="M12 3.5 20 8l-8 4.5L4 8z" />
      <path d="m4 12 8 4.5 8-4.5" />
      <path d="m4 16 8 4.5 8-4.5" />
    </>
  ),
  insights: (
    <>
      <path d="M4 20h16" />
      <path d="M7 16v-4M12 16V7M17 16v-6" />
    </>
  ),
  cashflow: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="3" />
      <path d="M3 10.5h18" />
      <path d="M16 15h2" />
    </>
  ),
  system: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  desktop: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </>
  ),
  phone: (
    <>
      <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
      <path d="M11 18h2" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="10" rx="2.5" />
      <path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3" />
    </>
  ),
};

function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICON_PATHS[name]}
    </svg>
  );
}

/** The app's mark: an accent tile with a rising-line monogram. */
function Logo({ size = 44 }: { size?: number }) {
  return (
    <span
      className="grid place-items-center rounded-2xl bg-brass text-ink shadow-[0_10px_30px_-10px_var(--color-brass)]"
      style={{ width: size, height: size }}
    >
      <svg width={size * 0.55} height={size * 0.55} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 17c2.5 0 3-9 6-9s2.5 6 5 6 3-7 5-9" />
      </svg>
    </span>
  );
}

/** The theme and layout switches, as round icon buttons. */
function AppToggles({ viewMode, onToggleViewMode }: { viewMode: ViewMode; onToggleViewMode: () => void }) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  const isMobile = viewMode === "mobile";
  const button =
    "grid place-items-center w-10 h-10 rounded-full text-muted hover:text-ink-text hover:bg-ink-raised transition-colors";
  return (
    <>
      <button
        onClick={toggleTheme}
        aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        title={isDark ? "Light mode" : "Dark mode"}
        className={button}
      >
        <Icon name={isDark ? "sun" : "moon"} size={18} />
      </button>
      <button
        onClick={onToggleViewMode}
        aria-label={isMobile ? "Switch to desktop layout" : "Switch to mobile layout"}
        title={isMobile ? "Desktop layout" : "Mobile layout"}
        className={button}
      >
        <Icon name={isMobile ? "desktop" : "phone"} size={18} />
      </button>
    </>
  );
}

/** Desktop: the slim icon rail on the left edge of the app frame. */
export function Rail({ viewMode, onToggleViewMode }: { viewMode: ViewMode; onToggleViewMode: () => void }) {
  const active = useActiveGroup();
  return (
    <div className="z-30 w-[84px] shrink-0 border-r ledger-rule">
      <aside className="sticky top-3.5 h-[calc(100vh-1.75rem)] flex flex-col items-center py-6">
        <Link to="/" aria-label="Net Worth Suite — Summary">
          <Logo />
        </Link>

        <nav className="mt-10 w-full flex flex-col gap-1.5" aria-label="Sections">
          {NAV_GROUPS.map((g) => {
            const isActive = g.id === active.id;
            return (
              <Link
                key={g.id}
                to={g.items[0].to}
                aria-label={g.label}
                aria-current={isActive ? "page" : undefined}
                className={`group relative flex h-12 items-center justify-center transition-colors ${
                  isActive ? "text-ink-text" : "text-muted hover:text-ink-text"
                }`}
              >
                {isActive && (
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-0 left-0 right-0 bg-gradient-to-r from-brass-soft to-transparent"
                  >
                    <span className="absolute inset-y-1.5 left-0 w-[3px] rounded-r-full bg-brass shadow-[0_0_14px_2px_var(--color-brass)]" />
                  </span>
                )}
                <span className="relative">
                  <Icon name={g.icon} />
                </span>
                <span
                  role="tooltip"
                  className="glass pointer-events-none absolute left-full ml-2 whitespace-nowrap px-3 py-1.5 !rounded-xl text-xs font-medium text-ink-text opacity-0 -translate-x-1 transition-all group-hover:opacity-100 group-hover:translate-x-0 group-focus-visible:opacity-100 z-50"
                >
                  {g.label}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto flex flex-col items-center gap-1">
          <AppToggles viewMode={viewMode} onToggleViewMode={onToggleViewMode} />
          <span
            className="mt-3 grid place-items-center w-11 h-11 rounded-2xl border ledger-rule bg-ink-raised text-brass"
            title="Runs locally · your data stays private"
          >
            <Icon name="lock" size={18} />
          </span>
        </div>
      </aside>
    </div>
  );
}

/** The pill tabs for a group's pages; nothing for a group with a single page. */
export function SubNav({ className = "" }: { className?: string }) {
  const group = useActiveGroup();
  if (group.items.length < 2) return null;
  return (
    <nav aria-label={group.label} className={`flex gap-1 p-1 rounded-full bg-ink-raised border ledger-rule w-fit max-w-full overflow-x-auto ${className}`}>
      {group.items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            `px-4 py-1.5 rounded-full text-sm whitespace-nowrap transition-colors ${
              isActive ? "bg-brass text-ink font-semibold shadow-sm" : "text-muted hover:text-ink-text"
            }`
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

/** Mobile: the floating glass tab bar at the bottom of the screen. */
export function BottomBar() {
  const active = useActiveGroup();
  return (
    <nav
      aria-label="Sections"
      className="glass fixed bottom-3 inset-x-3 z-40 !rounded-3xl flex justify-around px-1 py-1.5"
    >
      {NAV_GROUPS.map((g) => {
        const isActive = g.id === active.id;
        return (
          <Link
            key={g.id}
            to={g.items[0].to}
            aria-current={isActive ? "page" : undefined}
            className={`flex flex-1 flex-col items-center gap-0.5 rounded-2xl py-1.5 text-[10px] font-medium transition-colors ${
              isActive ? "text-brass bg-brass-soft" : "text-muted"
            }`}
          >
            <Icon name={g.icon} size={20} />
            <span className="truncate max-w-full px-1">{g.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * The portfolio every page shows, picked once for the whole app. On a
 * portfolio's own page, picking another one opens that one's page instead.
 * Nothing to pick before the first portfolio exists.
 */
export function PortfolioSwitcher({ className = "" }: { className?: string }) {
  const { portfolios, portfolio, selectPortfolio } = usePortfolio();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  if (!portfolio) return null;

  function pick(id: string) {
    selectPortfolio(id);
    if (matchPath("/portfolios/:id", pathname)) navigate(`/portfolios/${id}`);
  }

  return (
    <label className={`flex items-center gap-2 text-xs text-muted ${className}`}>
      <span className="uppercase tracking-[0.14em] font-semibold">Portfolio</span>
      <select
        className="input !py-1.5 !rounded-full text-sm max-w-[16rem]"
        value={portfolio.id}
        onChange={(e) => pick(e.target.value)}
        aria-label="Portfolio shown"
      >
        {portfolios.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Desktop: the section name, its page tabs, the portfolio shown and today's date above the page. */
export function TopBar() {
  const group = useActiveGroup();
  const [today] = useState(() =>
    new Date().toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" })
  );
  return (
    <div className="flex items-center justify-between gap-4 flex-wrap">
      <div className="flex items-center gap-4 flex-wrap">
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{group.label}</span>
        <SubNav />
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <PortfolioSwitcher />
        <span className="text-xs text-muted px-3.5 py-2 rounded-full bg-ink-raised border ledger-rule">{today}</span>
      </div>
    </div>
  );
}

/** Mobile: the glass bar at the top, with the section name and the toggles. */
export function MobileHeader({ viewMode, onToggleViewMode }: { viewMode: ViewMode; onToggleViewMode: () => void }) {
  const group = useActiveGroup();
  return (
    <header className="glass sticky top-0 z-30 !rounded-none !border-x-0 !border-t-0 flex items-center gap-3 px-4 py-2.5">
      <Logo size={34} />
      <span className="font-display text-lg font-semibold truncate">{group.label}</span>
      <div className="ml-auto flex items-center">
        <AppToggles viewMode={viewMode} onToggleViewMode={onToggleViewMode} />
      </div>
    </header>
  );
}
