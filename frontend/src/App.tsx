import { useState } from "react";
import { Routes, Route, useLocation, matchPath } from "react-router-dom";
import Sidebar, { NAV_ITEMS } from "./components/Sidebar";
import { ViewModeProvider } from "./context/ViewModeContext";
import Dashboard from "./pages/Dashboard";
import Portfolios from "./pages/Portfolios";
import PortfolioDetail from "./pages/PortfolioDetail";
import Assets from "./pages/Assets";
import AssetDetail from "./pages/AssetDetail";
import Allocation from "./pages/Allocation";
import HistoricalNetWorth from "./pages/HistoricalNetWorth";
import Settings from "./pages/Settings";
import Expenses from "./pages/Expenses";

/**
 * "desktop" is the original, unchanged layout (fixed sidebar always visible).
 * "mobile" swaps the sidebar for a hamburger-triggered drawer + topbar.
 * Never auto-detected — purely a manual toggle, and never persisted, per
 * the "reorganize on phone, leave desktop untouched, one button to switch"
 * requirement: every fresh page load starts back in "desktop".
 */
export type ViewMode = "desktop" | "mobile";

function CurrentPageTitle() {
  const location = useLocation();
  const active = NAV_ITEMS.find((item) =>
    matchPath({ path: item.to, end: item.to === "/" }, location.pathname)
  );
  return <>{active?.label ?? "Ledger"}</>;
}

export default function App() {
  const [viewMode, setViewMode] = useState<ViewMode>("desktop");
  const [drawerOpen, setDrawerOpen] = useState(false);

  const isMobile = viewMode === "mobile";

  function toggleViewMode() {
    setViewMode((m) => (m === "desktop" ? "mobile" : "desktop"));
    setDrawerOpen(false);
  }

  if (!isMobile) {
    return (
      <ViewModeProvider value={viewMode}>
        <div className="flex min-h-screen bg-ink text-ink-text">
          <Sidebar viewMode={viewMode} onToggleViewMode={toggleViewMode} />
          <main className="flex-1 px-10 py-8 max-w-5xl">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/portfolios" element={<Portfolios />} />
              <Route path="/portfolios/:id" element={<PortfolioDetail />} />
              <Route path="/assets" element={<Assets />} />
              <Route path="/assets/:id" element={<AssetDetail />} />
              <Route path="/allocation" element={<Allocation />} />
              <Route path="/historical-networth" element={<HistoricalNetWorth />} />
              <Route path="/expenses" element={<Expenses />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
        </div>
      </ViewModeProvider>
    );
  }

  return (
    <ViewModeProvider value={viewMode}>
      <div className="min-h-screen bg-ink text-ink-text">
        <Sidebar
          viewMode={viewMode}
          onToggleViewMode={toggleViewMode}
          drawerOpen={drawerOpen}
          onCloseDrawer={() => setDrawerOpen(false)}
        />

        <header className="sticky top-0 z-30 flex items-center gap-3 px-4 py-3 border-b ledger-rule bg-ink/95 backdrop-blur">
          <button
            onClick={() => setDrawerOpen(true)}
            aria-label="Open menu"
            className="p-2 -ml-2 rounded hover:bg-ink-raised/60 text-ink-text"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
            </svg>
          </button>
          <span className="font-display text-lg text-brass truncate">
            <CurrentPageTitle />
          </span>
        </header>

        <main className="px-4 py-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/portfolios" element={<Portfolios />} />
            <Route path="/portfolios/:id" element={<PortfolioDetail />} />
            <Route path="/assets" element={<Assets />} />
            <Route path="/assets/:id" element={<AssetDetail />} />
            <Route path="/allocation" element={<Allocation />} />
            <Route path="/historical-networth" element={<HistoricalNetWorth />} />
            <Route path="/expenses" element={<Expenses />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </ViewModeProvider>
  );
}
