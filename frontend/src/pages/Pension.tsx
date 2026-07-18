import { useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { api } from "../api/client";
import type { PensionProjectionPoint } from "../types";
import { formatMoney, todayISO } from "../lib/format";

interface ContributionRow {
  entry_date: string;
  employee_contribution: string;
  employer_contribution: string;
  severance_contribution: string;
}

export default function Pension() {
  const [rows, setRows] = useState<ContributionRow[]>([
    { entry_date: todayISO(), employee_contribution: "100", employer_contribution: "50", severance_contribution: "80" },
  ]);
  const [annualReturn, setAnnualReturn] = useState("3");
  const [years, setYears] = useState("15");
  const [points, setPoints] = useState<PensionProjectionPoint[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateRow(i: number, field: keyof ContributionRow, value: string) {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  }

  function addRow() {
    setRows((rs) => [...rs, { entry_date: todayISO(), employee_contribution: "0", employer_contribution: "0", severance_contribution: "0" }]);
  }

  function removeRow(i: number) {
    setRows((rs) => rs.filter((_, idx) => idx !== i));
  }

  async function handleProject() {
    setLoading(true);
    setError(null);
    try {
      const result = await api.projectPension({
        contributions: rows.map((r) => ({
          entry_date: r.entry_date,
          employee_contribution: parseFloat(r.employee_contribution) || 0,
          employer_contribution: parseFloat(r.employer_contribution) || 0,
          severance_contribution: parseFloat(r.severance_contribution) || 0,
        })),
        annual_return_pct: parseFloat(annualReturn) || 0,
        projection_years: parseInt(years, 10) || 1,
      });
      setPoints(result);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl mb-1">Pension Fund</h1>
        <p className="text-muted text-sm">
          Projects the future value based on historical contributions and the fund line's expected
          return (e.g. COMETA). Independent module: extend it with your fund's exact rules whenever
          you like.
        </p>
      </div>

      <div className="card p-6 space-y-4">
        <h2 className="font-display text-lg">Contributions</h2>
        <div className="space-y-2">
          <div className="grid grid-cols-5 gap-3 text-xs uppercase tracking-wide text-muted">
            <span>Date</span>
            <span>Employee</span>
            <span>Employer</span>
            <span>Severance</span>
            <span></span>
          </div>
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-5 gap-3">
              <input type="date" className="input" value={r.entry_date} onChange={(e) => updateRow(i, "entry_date", e.target.value)} />
              <input className="input" value={r.employee_contribution} onChange={(e) => updateRow(i, "employee_contribution", e.target.value)} />
              <input className="input" value={r.employer_contribution} onChange={(e) => updateRow(i, "employer_contribution", e.target.value)} />
              <input className="input" value={r.severance_contribution} onChange={(e) => updateRow(i, "severance_contribution", e.target.value)} />
              <button className="text-muted text-xs hover:text-loss" onClick={() => removeRow(i)}>
                Remove
              </button>
            </div>
          ))}
        </div>
        <button className="btn-ghost text-sm" onClick={addRow}>
          + Add row
        </button>

        <div className="grid grid-cols-2 gap-4 pt-4 border-t ledger-rule">
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Expected annual return (%)</label>
            <input className="input w-full" value={annualReturn} onChange={(e) => setAnnualReturn(e.target.value)} />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Projection years</label>
            <input className="input w-full" value={years} onChange={(e) => setYears(e.target.value)} />
          </div>
        </div>

        {error && <p className="text-loss text-sm">{error}</p>}
        <button className="btn-primary" onClick={handleProject} disabled={loading}>
          {loading ? "Calculating…" : "Calculate projection"}
        </button>
      </div>

      {points && (
        <div className="card p-6">
          <h2 className="font-display text-lg mb-4">Projected fund value</h2>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={points} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid stroke="#2A3937" strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="year"
                tick={{ fill: "#8CA39C", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                axisLine={{ stroke: "#2A3937" }}
                tickLine={false}
                tickFormatter={(v) => `Year ${v}`}
              />
              <YAxis
                tick={{ fill: "#8CA39C", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                axisLine={false}
                tickLine={false}
                width={80}
                tickFormatter={(v) => formatMoney(v)}
              />
              <Tooltip
                contentStyle={{ background: "#1A2624", border: "1px solid #2A3937", borderRadius: 6, fontSize: 12 }}
                formatter={(v: any) => [formatMoney(Number(v)), "Estimated balance"]}
                labelFormatter={(v) => `Year ${v}`}
              />
              <Line type="monotone" dataKey="balance" stroke="#C8A661" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
