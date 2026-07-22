import { useEffect, useState, useRef } from "react";
import { api } from "../api/client";
import type { BackupStats } from "../types";

type RestorePreview = { exported_at: string; core: BackupStats; geo: { assets_with_files: number } };

export default function Settings() {
  const [health, setHealth] = useState<{ gateway: string; modules: Record<string, string> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<RestorePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreDone, setRestoreDone] = useState(false);

  async function handleDownload() {
    setExporting(true);
    setExportError(null);
    try {
      await api.downloadBackup();
    } catch (e: any) {
      setExportError(e.message || String(e));
    } finally {
      setExporting(false);
    }
  }

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setPendingFile(file);
    setPreview(null);
    setPreviewError(null);
    setRestoreError(null);
    setRestoreDone(false);
    setPreviewLoading(true);
    try {
      const result = await api.previewBackup(file);
      setPreview(result);
    } catch (e: any) {
      setPreviewError(e.message || String(e));
      setPendingFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } finally {
      setPreviewLoading(false);
    }
  }

  function cancelRestore() {
    setPendingFile(null);
    setPreview(null);
    setPreviewError(null);
    setRestoreError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function confirmRestore() {
    if (!pendingFile) return;
    setRestoring(true);
    setRestoreError(null);
    try {
      await api.restoreBackup(pendingFile);
      setRestoreDone(true);
    } catch (e: any) {
      setRestoreError(e.message || String(e));
    } finally {
      setRestoring(false);
    }
  }

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
        <h2 className="font-display text-lg mb-2">Backup & Restore</h2>
        <p className="text-sm text-muted leading-relaxed mb-4">
          Everything you've entered — portfolios, holdings, cash balances, snapshots, and any
          uploaded ETF factsheets — as one downloadable file, separate from the automatic daily
          backups already kept on disk.
        </p>

        <div className="mb-6">
          <button className="btn-primary text-sm" onClick={handleDownload} disabled={exporting}>
            {exporting ? "Preparing…" : "Download full backup"}
          </button>
          {exportError && <p className="text-loss text-sm mt-2">{exportError}</p>}
        </div>

        <div className="pt-4 border-t ledger-rule">
          <h3 className="text-sm font-medium mb-2">Restore from backup</h3>
          <p className="text-xs text-muted mb-3">
            This replaces everything currently in the app with what's in the file. A safety copy
            of your current data is taken automatically first, so this can be undone if needed.
          </p>

          {!pendingFile && (
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              onChange={handleFileSelected}
              className="text-sm"
            />
          )}
          {previewLoading && <p className="text-muted text-sm mt-2">Reading backup file…</p>}
          {previewError && <p className="text-loss text-sm mt-2">{previewError}</p>}

          {preview && pendingFile && !restoreDone && (
            <div className="mt-3 p-4 rounded border ledger-rule bg-ink-raised space-y-3">
              <p className="text-sm">
                <span className="font-medium">{pendingFile.name}</span> — exported{" "}
                {new Date(preview.exported_at).toLocaleString("en-US")}
              </p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted">
                <span>Portfolios: {preview.core.portfolios ?? "?"}</span>
                <span>Assets: {preview.core.assets ?? "?"}</span>
                <span>Holdings: {preview.core.holdings ?? "?"}</span>
                <span>Cash accounts: {preview.core.cash_accounts ?? "?"}</span>
                <span>Net worth snapshots: {preview.core.snapshots ?? "?"}</span>
                <span>ETF factsheets: {preview.geo?.assets_with_files ?? "?"}</span>
              </div>
              <p className="text-loss text-xs font-medium">
                Restoring will overwrite everything currently in the app with the data above. This
                cannot be undone from the UI (though a safety copy is kept in ./backups on the
                server).
              </p>
              {restoreError && <p className="text-loss text-sm">{restoreError}</p>}
              <div className="flex gap-3">
                <button className="btn-primary text-sm bg-loss" onClick={confirmRestore} disabled={restoring}>
                  {restoring ? "Restoring…" : "Yes, restore and overwrite everything"}
                </button>
                <button className="btn-ghost text-sm" onClick={cancelRestore} disabled={restoring}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {restoreDone && (
            <div className="mt-3 p-4 rounded border ledger-rule bg-ink-raised space-y-3">
              <p className="text-sm text-gain font-medium">Restore complete.</p>
              <p className="text-xs text-muted">
                The app needs to reload to pick up the restored data everywhere.
              </p>
              <button className="btn-primary text-sm" onClick={() => window.location.reload()}>
                Reload now
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="card p-6">
        <h2 className="font-display text-lg mb-2">Architecture</h2>
        <p className="text-sm text-muted leading-relaxed">
          core → portfolios, assets, cash, valuation. prices → live prices and FX rates (yfinance).
          geo → ETF geographic allocation (local files + parsing library). All reachable only
          through the gateway at{" "}
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
