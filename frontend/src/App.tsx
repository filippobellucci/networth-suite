import { Routes, Route } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Dashboard from "./pages/Dashboard";
import Portfolios from "./pages/Portfolios";
import PortfolioDetail from "./pages/PortfolioDetail";
import Assets from "./pages/Assets";
import GeoAllocation from "./pages/GeoAllocation";
import Pension from "./pages/Pension";
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
          <Route path="/geo-allocation" element={<GeoAllocation />} />
          <Route path="/pension" element={<Pension />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
