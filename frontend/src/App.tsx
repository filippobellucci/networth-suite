import { useEffect, useState } from "react";
import { Routes, Route, useLocation } from "react-router-dom";
import { BottomBar, MobileHeader, PortfolioSwitcher, Rail, SubNav, TopBar } from "./components/Navigation";
import ErrorBoundary from "./components/ErrorBoundary";
import { ViewModeProvider, type ViewMode } from "./context/ViewModeContext";
import { RequirePortfolio } from "./context/PortfolioContext";
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
 * "desktop" is the framed layout with the icon rail on the left; "mobile"
 * swaps the rail for a top bar and a floating bottom tab bar. Never
 * auto-detected -- purely a manual toggle -- and persisted (like
 * theme/palette), so picking "mobile" once sticks across reloads. The type
 * itself lives in ViewModeContext, next to the provider/hook the rest of the
 * app reads it through.
 */
function getInitialViewMode(): ViewMode {
  return localStorage.getItem("viewMode") === "mobile" ? "mobile" : "desktop";
}

/**
 * The same route table for both layouts -- only the chrome around it differs.
 * Every page that shows data is about the portfolio picked in the top bar
 * (RequirePortfolio); the Portfolios list and Modules & Status are not.
 * Wrapped in an error boundary so a render error takes down the page's
 * content, not the whole app (the navigation stays usable).
 *
 * The boundary is reset on the path so navigating away clears the error: it
 * holds its failed state until something resets it, which would otherwise
 * leave the message in place while the navigation happily changed the URL.
 */
function AppRoutes() {
  const location = useLocation();
  return (
    <ErrorBoundary resetKey={location.pathname}>
      <Routes>
        <Route path="/" element={<RequirePortfolio><Dashboard /></RequirePortfolio>} />
        <Route path="/portfolios" element={<Portfolios />} />
        <Route path="/portfolios/:id" element={<PortfolioDetail />} />
        <Route path="/assets" element={<RequirePortfolio><Assets /></RequirePortfolio>} />
        <Route path="/assets/:id" element={<AssetDetail />} />
        <Route path="/allocation" element={<RequirePortfolio><Allocation /></RequirePortfolio>} />
        <Route path="/historical-networth" element={<RequirePortfolio><HistoricalNetWorth /></RequirePortfolio>} />
        <Route path="/expenses" element={<RequirePortfolio><Expenses /></RequirePortfolio>} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </ErrorBoundary>
  );
}

export default function App() {
  const [viewMode, setViewMode] = useState<ViewMode>(getInitialViewMode);
  const isMobile = viewMode === "mobile";

  useEffect(() => {
    localStorage.setItem("viewMode", viewMode);
  }, [viewMode]);

  function toggleViewMode() {
    setViewMode((m) => (m === "desktop" ? "mobile" : "desktop"));
  }

  if (!isMobile) {
    return (
      <ViewModeProvider value={viewMode}>
        <div className="min-h-screen p-3.5 text-ink-text">
          <div className="app-frame rounded-[28px] flex min-h-[calc(100vh-1.75rem)]">
            <Rail viewMode={viewMode} onToggleViewMode={toggleViewMode} />
            <div className="flex-1 min-w-0 px-8 py-7">
              <TopBar />
              <main className="mt-7 max-w-[1320px]">
                <AppRoutes />
              </main>
            </div>
          </div>
        </div>
      </ViewModeProvider>
    );
  }

  return (
    <ViewModeProvider value={viewMode}>
      <div className="min-h-screen text-ink-text">
        <MobileHeader viewMode={viewMode} onToggleViewMode={toggleViewMode} />
        <main className="px-4 pt-4 pb-28">
          <PortfolioSwitcher className="mb-4" />
          <SubNav className="mb-5" />
          <AppRoutes />
        </main>
        <BottomBar />
      </div>
    </ViewModeProvider>
  );
}
