import { useState } from "react";
import { api } from "../api/client";
import type {
  CashAccount,
  TransactionImportMapping,
  TransactionImportRequest,
  TransactionImportResult,
  TransactionImportRow,
} from "../types";
import { formatMoneyPrecise, formatDate } from "../lib/format";
import { parseCsvHeaderRow } from "../lib/csv";
import { errorText } from "../lib/errors";
import ResponsiveTable, { type ResponsiveColumn } from "./ResponsiveTable";

type ColumnField = "date" | "amount" | "currency" | "description" | "counterparty";

const EMPTY_MAPPING: Record<ColumnField, string> = {
  date: "", amount: "", currency: "", description: "", counterparty: "",
};

// Day/month order is ambiguous in most bank exports, so the format is
// picked from a list rather than typed as a raw strptime pattern -- "Custom"
// is the escape hatch for whatever isn't on it. See DESIGN_NOTES for why
// this (and the decimal separator below) can never default to one of these.
const DATE_FORMAT_PRESETS = [
  { value: "%d/%m/%Y", label: "DD/MM/YYYY — 31/12/2026" },
  { value: "%m/%d/%Y", label: "MM/DD/YYYY — 12/31/2026" },
  { value: "%Y-%m-%d", label: "YYYY-MM-DD — 2026-12-31" },
  { value: "%d-%m-%Y", label: "DD-MM-YYYY — 31-12-2026" },
  { value: "%d.%m.%Y", label: "DD.MM.YYYY — 31.12.2026" },
  { value: "%d/%m/%y", label: "DD/MM/YY — 31/12/26" },
];
const CUSTOM_FORMAT = "__custom__";

/**
 * Imports a bank statement CSV into `account`: pick the file, map its
 * columns and date format, preview exactly what the server would write,
 * then confirm. `buildPayload` is sent unchanged to both /import/preview
 * and /import (see `_plan_csv_import` on the backend) so what's shown here
 * is exactly what gets written -- there is no path from a chosen file to a
 * write that skips the preview.
 */
export default function TransactionImport({ account, onImported }: { account: CashAccount; onImported: () => void }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [csvText, setCsvText] = useState("");
  const [readError, setReadError] = useState<string | null>(null);

  const [delimiter, setDelimiter] = useState(",");
  const [decimalSeparator, setDecimalSeparator] = useState<"" | "." | ",">("");
  const [datePreset, setDatePreset] = useState("");
  const [customDateFormat, setCustomDateFormat] = useState("");
  const [mapping, setMapping] = useState(EMPTY_MAPPING);

  const [preview, setPreview] = useState<TransactionImportResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Generated once per confirm action and reused on a retry -- a fresh
  // preview (different mapping, or a different file) starts a new action
  // and gets a new key; see the ticket's double-submit requirement.
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [confirmResult, setConfirmResult] = useState<TransactionImportResult | null>(null);

  const headerColumns = csvText ? parseCsvHeaderRow(csvText, delimiter) : [];
  const dateFormat = datePreset === CUSTOM_FORMAT ? customDateFormat.trim() : datePreset;

  function clearPreview() {
    setPreview(null);
    setPreviewError(null);
    setConfirmResult(null);
    setImportError(null);
    setIdempotencyKey(null);
  }

  function reset() {
    setFile(null);
    setCsvText("");
    setReadError(null);
    setDelimiter(",");
    setDecimalSeparator("");
    setDatePreset("");
    setCustomDateFormat("");
    setMapping(EMPTY_MAPPING);
    clearPreview();
  }

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0];
    e.target.value = "";
    if (!picked) return;
    setReadError(null);
    setMapping(EMPTY_MAPPING);
    clearPreview();
    try {
      setCsvText(await picked.text());
      setFile(picked);
    } catch (err) {
      setReadError(errorText(err));
      setFile(null);
      setCsvText("");
    }
  }

  function updateMapping(field: ColumnField, value: string) {
    setMapping((m) => ({ ...m, [field]: value }));
    clearPreview();
  }

  function updateDelimiter(value: string) {
    setDelimiter(value);
    // The file's columns are re-split on the new delimiter -- whatever was
    // picked before may no longer be one of them.
    setMapping(EMPTY_MAPPING);
    clearPreview();
  }

  function updateDatePreset(value: string) {
    setDatePreset(value);
    if (value !== CUSTOM_FORMAT) setCustomDateFormat("");
    clearPreview();
  }

  const canPreview =
    !!file && !!mapping.date && !!mapping.amount && !!dateFormat && !!decimalSeparator && delimiter.length === 1;

  function buildPayload(): TransactionImportRequest {
    const column_mapping: TransactionImportMapping = {
      date: mapping.date,
      amount: mapping.amount,
      currency: mapping.currency || undefined,
      description: mapping.description || undefined,
      counterparty: mapping.counterparty || undefined,
    };
    return {
      csv_content: csvText,
      column_mapping,
      date_format: dateFormat,
      delimiter,
      decimal_separator: decimalSeparator as "." | ",",
    };
  }

  async function handlePreview() {
    if (!canPreview || previewing) return;
    setPreviewing(true);
    setPreviewError(null);
    setConfirmResult(null);
    setIdempotencyKey(null);
    try {
      setPreview(await api.previewTransactionImport(account.id, buildPayload()));
    } catch (err) {
      setPreviewError(errorText(err));
    } finally {
      setPreviewing(false);
    }
  }

  async function handleConfirm() {
    if (!preview || importing) return;
    setImporting(true);
    setImportError(null);
    const key = idempotencyKey ?? crypto.randomUUID();
    if (!idempotencyKey) setIdempotencyKey(key);
    try {
      const result = await api.commitTransactionImport(account.id, buildPayload(), key);
      setConfirmResult(result);
      onImported();
    } catch (err) {
      setImportError(errorText(err));
    } finally {
      setImporting(false);
    }
  }

  if (!open) {
    return (
      <button className="btn-ghost text-sm" onClick={() => setOpen(true)}>
        Import CSV
      </button>
    );
  }

  const discardedRows = preview ? preview.rows.filter((r) => r.status !== "import") : [];

  return (
    <div className="card p-5 space-y-4" aria-label="Import transactions">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h3 className="font-display text-base">Import bank statement into {account.name}</h3>
        <button
          className="btn-ghost text-sm"
          onClick={() => {
            setOpen(false);
            reset();
          }}
        >
          Close
        </button>
      </div>

      {!confirmResult && !file && (
        <div>
          <input type="file" accept=".csv,.txt" onChange={handleFileSelected} className="text-sm" aria-label="CSV file" />
          {readError && <p className="text-loss text-sm mt-2">{readError}</p>}
        </div>
      )}

      {!confirmResult && file && !preview && (
        <div className="space-y-4">
          <p className="text-sm">
            <span className="font-medium">{file.name}</span>
            {headerColumns.length > 0 ? (
              <span className="text-muted"> — columns: {headerColumns.join(", ")}</span>
            ) : (
              <span className="text-loss"> — no columns found with this delimiter</span>
            )}
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="field-label">Delimiter</label>
              <select
                className="input w-full"
                aria-label="Delimiter"
                value={delimiter}
                onChange={(e) => updateDelimiter(e.target.value)}
              >
                <option value=",">Comma (,)</option>
                <option value=";">Semicolon (;)</option>
                <option value="\t">Tab</option>
                <option value="|">Pipe (|)</option>
              </select>
            </div>
            <div>
              <label className="field-label">Decimal separator</label>
              <select
                className="input w-full"
                aria-label="Decimal separator"
                value={decimalSeparator}
                onChange={(e) => {
                  setDecimalSeparator(e.target.value as "" | "." | ",");
                  clearPreview();
                }}
              >
                <option value="">Select…</option>
                <option value=".">Dot — 1234.56</option>
                <option value=",">Comma — 1234,56</option>
              </select>
            </div>

            <ColumnSelect label="Date column" value={mapping.date} onChange={(v) => updateMapping("date", v)} columns={headerColumns} />
            <div>
              <label className="field-label">Date format</label>
              <select
                className="input w-full"
                aria-label="Date format"
                value={datePreset}
                onChange={(e) => updateDatePreset(e.target.value)}
              >
                <option value="">Select…</option>
                {DATE_FORMAT_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
                <option value={CUSTOM_FORMAT}>Custom…</option>
              </select>
              {datePreset === CUSTOM_FORMAT && (
                <input
                  className="input w-full mt-2"
                  aria-label="Custom date format"
                  placeholder="e.g. %d/%m/%Y"
                  value={customDateFormat}
                  onChange={(e) => {
                    setCustomDateFormat(e.target.value);
                    clearPreview();
                  }}
                />
              )}
            </div>

            <ColumnSelect
              label="Amount column"
              value={mapping.amount}
              onChange={(v) => updateMapping("amount", v)}
              columns={headerColumns}
            />
            <ColumnSelect
              label="Currency column (optional)"
              value={mapping.currency}
              onChange={(v) => updateMapping("currency", v)}
              columns={headerColumns}
              optional
            />
            <ColumnSelect
              label="Description column (optional)"
              value={mapping.description}
              onChange={(v) => updateMapping("description", v)}
              columns={headerColumns}
              optional
            />
            <ColumnSelect
              label="Counterparty column (optional)"
              value={mapping.counterparty}
              onChange={(v) => updateMapping("counterparty", v)}
              columns={headerColumns}
              optional
            />
          </div>

          {previewError && <p className="text-loss text-sm">{previewError}</p>}
          <div className="flex gap-3">
            <button className="btn-primary text-sm" onClick={handlePreview} disabled={!canPreview || previewing}>
              {previewing ? "Checking…" : "Preview import"}
            </button>
            <button className="btn-ghost text-sm" onClick={reset}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {!confirmResult && preview && (
        <div className="space-y-4">
          <p className="text-sm">
            {preview.to_import} to import, {preview.duplicates} already here, {preview.errors} with a problem —{" "}
            {preview.total_rows} row{preview.total_rows === 1 ? "" : "s"} read.
          </p>

          {discardedRows.length > 0 && <DiscardedRowsTable rows={discardedRows} accountCurrency={account.currency} />}

          {importError && <p className="text-loss text-sm">{importError}</p>}
          <div className="flex gap-3 flex-wrap">
            <button className="btn-primary text-sm" onClick={handleConfirm} disabled={importing || preview.to_import === 0}>
              {importing ? "Importing…" : `Import ${preview.to_import} transaction${preview.to_import === 1 ? "" : "s"}`}
            </button>
            <button className="btn-ghost text-sm" onClick={() => setPreview(null)} disabled={importing}>
              Back to mapping
            </button>
            <button className="btn-ghost text-sm" onClick={reset} disabled={importing}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {confirmResult && (
        <div className="space-y-3">
          <p className="text-sm text-gain font-medium">
            {confirmResult.to_import} transaction{confirmResult.to_import === 1 ? "" : "s"} imported.
          </p>
          <button className="btn-primary text-sm" onClick={reset}>
            Import another file
          </button>
        </div>
      )}
    </div>
  );
}

function ColumnSelect({
  label,
  value,
  onChange,
  columns,
  optional,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  columns: string[];
  optional?: boolean;
}) {
  return (
    <div>
      <label className="field-label">{label}</label>
      <select className="input w-full" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{optional ? "— none —" : "Select a column…"}</option>
        {columns.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    </div>
  );
}

/** The rows the import would NOT write, each with the reason the server
 * gave -- a count alone ("3 duplicates") doesn't tell the user which of
 * their rows that was or why, which is the whole point of previewing. */
function DiscardedRowsTable({ rows, accountCurrency }: { rows: TransactionImportRow[]; accountCurrency: string }) {
  return (
    <ResponsiveTable
      keyFor={(r) => String(r.row_number)}
      rows={rows}
      columns={
        [
          { header: "Row", cell: (r) => r.row_number, className: "font-sans" },
          { header: "Date", cell: (r) => (r.entry_date ? formatDate(r.entry_date) : "—"), className: "font-sans" },
          {
            header: "Amount",
            className: "text-right num",
            headClassName: "text-right",
            cell: (r) => (r.amount != null ? formatMoneyPrecise(r.amount, accountCurrency) : "—"),
          },
          {
            header: "Why it's not imported",
            className: "text-xs",
            cell: (r) => (
              <span className={r.status === "duplicate" ? "text-muted" : "text-loss"}>
                {r.status === "duplicate" ? "Duplicate — " : "Error — "}
                {r.reason}
              </span>
            ),
          },
        ] as ResponsiveColumn<TransactionImportRow>[]
      }
    />
  );
}
