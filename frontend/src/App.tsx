import { Routes, Route } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Dashboard from "./pages/Dashboard";
import Portfolios from "./pages/Portfolios";
import PortfolioDetail from "./pages/PortfolioDetail";
import Assets from "./pages/Assets";
import PortfolioAllocation from "./pages/PortfolioAllocation";
import GeoAllocation from "./pages/GeoAllocation";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <div className="flex min-h-screen bg-ink text-ink-text">
      <Sidebar />
      <main className="flex-1 px-10 py-8 max-w-5xl">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/portfolios" element={<Portfolios />} />
          <Route path="/portfolios/:id" element={<PortfolioDetail />} />
          <Route path="/assets" element={<Assets />} />
          <Route path="/portfolio-allocation" element={<PortfolioAllocation />} />
          <Route path="/geo-allocation" element={<GeoAllocation />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
