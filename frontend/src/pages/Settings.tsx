import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function Settings() {
  const [health, setHealth] = useState<{ gateway: string; modules: Record<string, string> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  function check() {
    api
      .getModulesHealth()
      .then((h) => {
        setHealth(h);
        setError(null);
        setCheckedAt(new Date());
      })
      .catch((e) => setError(String(e.message || e)));
  }

  useEffect(check, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl mb-1">Modules & Status</h1>
        <p className="text-muted text-sm">
          The system is made of independent microservices behind a single gateway. Adding a new
          "module" in the future only requires registering it with the gateway — no frontend
          changes needed.
        </p>
      </div>

      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display text-lg">Service status</h2>
          <button className="btn-ghost text-sm" onClick={check}>
            Recheck
          </button>
        </div>

        {error ? (
          <p className="text-loss text-sm">{error}</p>
        ) : !health ? (
          <p className="text-muted text-sm">Checking…</p>
        ) : (
          <div className="space-y-2">
            <StatusRow name="Gateway" status={health.gateway} />
            {Object.entries(health.modules).map(([name, status]) => (
              <StatusRow key={name} name={name} status={status} />
            ))}
          </div>
        )}

        {checkedAt && <p className="text-xs text-muted mt-4">Last checked: {checkedAt.toLocaleTimeString("en-US")}</p>}
      </div>

      <div className="card p-6">
        <h2 className="font-display text-lg mb-2">Architecture</h2>
        <p className="text-sm text-muted leading-relaxed">
          core → portfolios, assets, cash, valuation. prices → live prices and FX rates (yfinance).
          geo → ETF geographic allocation (local files + parsing library). pension → pension fund
          projections. All reachable only through the gateway at{" "}
          <span className="font-mono">/api/&lt;module&gt;/...</span>.
        </p>
      </div>
    </div>
  );
}

function StatusRow({ name, status }: { name: string; status: string }) {
  const ok = status === "ok";
  return (
    <div className="flex items-center justify-between px-4 py-2 rounded bg-ink-raised border ledger-rule">
      <span className="capitalize">{name}</span>
      <span className={`text-xs font-mono ${ok ? "text-gain" : "text-loss"}`}>{ok ? "● ok" : `● ${status}`}</span>
    </div>
  );
}
