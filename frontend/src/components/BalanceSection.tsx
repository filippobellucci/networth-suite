import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ReactNode } from "react";
import type { Asset, AllocationCategory, CashPosition, HoldingPosition, CashAccountKind } from "../types";
import InfoTooltip from "./InfoTooltip";
import { ALLOCATION_CATEGORY_LABELS } from "../types";
import { formatMoney, formatMoneyPrecise, todayISO, parseLocaleFloat } from "../lib/format";
import ResponsiveTable, { type ResponsiveColumn } from "./ResponsiveTable";
import SegmentedControl from "./SegmentedControl";
import WarningCard from "./WarningCard";
import AddPositionForm from "./AddPositionForm";
import { removeAssetFromPortfolio } from "./PositionsSection";
import { errorText } from "../lib/errors";

/** Tags offerable to a cash-like balance, in the order the pickers show them. */
const BALANCE_TAGS: AllocationCategory[] = ["CASH", "EMERGENCY_FUND", "PENSION_FUND", "STOCK", "BOND"];

// Cash / Emergency Fund / Pension Fund are all the same underlying mechanism
// (a named balance you update by hand from time to time), only the
// `category` tag differs -- so one component renders all three sections.
export default function BalanceSection({
  title,
  defaultCategory,
  positions,
  portfolioId,
  baseCurrency,
  onChanged,
  emptyHint,
  tooltip,
  allowManualUpdate = true,
  allowPositions = false,
  allAssets = [],
  assetPositions = [],
}: {
  title: string;
  defaultCategory: AllocationCategory;
  positions: CashPosition[];
  portfolioId: string;
  baseCurrency: string;
  onChanged: () => void;
  emptyHint?: string;
  tooltip?: ReactNode;
  /**
   * Whether the "Update" balance flow is offered on this section. False for
   * Cash and Emergency Fund now that Transactions is the source of truth
   * for their balance -- true for Pension Fund, which deliberately stays
   * hand-updated only (see PortfolioDetail's tooltip on that section).
   */
  allowManualUpdate?: boolean;
  /**
   * Lets "+ Add" also offer "Position" alongside "Cash balance" -- so far
   * only Emergency Fund, since that's the only place a position (e.g. a
   * money-market ETF) is tracked as a sub-holding of a balance-like
   * section. Reuses AddPositionForm verbatim (same code path as the
   * Positions section above), just preselecting this section's tag on a
   * newly-created asset -- never forced, still fully editable in the form.
   */
  allowPositions?: boolean;
  allAssets?: Asset[];
  /** Positions already tagged `defaultCategory`, shown in their own table below the cash one. */
  assetPositions?: HoldingPosition[];
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [addKind, setAddKind] = useState<"balance" | "position">("balance");
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState(baseCurrency);
  const [balance, setBalance] = useState("");
  const [tag, setTag] = useState<AllocationCategory>(defaultCategory);
  const [kind, setKind] = useState<CashAccountKind>("CURRENCY");
  const [unitValue, setUnitValue] = useState("");
  const [saving, setSaving] = useState(false);
  // Every write below reports its failure here: one message, shown wherever
  // the action lives.
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [editDate, setEditDate] = useState(todayISO());
  const [editSaving, setEditSaving] = useState(false);

  // Editing the account's own details (name/currency/tag) -- separate from
  // editing its balance above.
  const [editingDetailsId, setEditingDetailsId] = useState<string | null>(null);
  const [detailsName, setDetailsName] = useState("");
  const [detailsCurrency, setDetailsCurrency] = useState("");
  const [detailsCategory, setDetailsCategory] = useState<AllocationCategory>(defaultCategory);
  const [detailsUnitValue, setDetailsUnitValue] = useState("");
  const [detailsSaving, setDetailsSaving] = useState(false);

  // Vouchers (meal vouchers, etc.) only make sense where transactions are
  // allowed to move the balance -- there's no point offering a kind that
  // can never be adjusted. Also restricted to the Cash section, since that's
  // the account type this was designed for.
  const canOfferVoucherKind = allowManualUpdate === false && defaultCategory === "CASH";

  function openAdd() {
    setAddKind("balance"); // reset to Cash balance each time the form is (re)opened
    setTag(defaultCategory); // reset to this section's default each time the form is (re)opened
    setKind("CURRENCY");
    setUnitValue("");
    setError(null);
    setShowAdd(true);
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Give this account a name.");
      return;
    }
    let parsedUnitValue: number | undefined;
    if (kind === "VOUCHER") {
      parsedUnitValue = parseLocaleFloat(unitValue);
      if (!(parsedUnitValue > 0)) {
        // A blank or mistyped unit value would make every unit worth 0.
        setError("Enter a unit value greater than 0 for a voucher account.");
        return;
      }
    }
    // Parsed before anything is created: an unreadable starting balance used
    // to reach the server as NaN (serialized to null), which it rejects --
    // leaving the account created but empty, and the error invisible.
    let parsedBalance: number | undefined;
    if (balance.trim()) {
      parsedBalance = parseLocaleFloat(balance);
      if (isNaN(parsedBalance)) {
        setError(kind === "VOUCHER" ? "That starting quantity isn't a number." : "That starting balance isn't a number.");
        return;
      }
    }
    setSaving(true);
    try {
      const acc = await api.createCashAccount(portfolioId, {
        name: name.trim(),
        currency: kind === "VOUCHER" ? baseCurrency : currency,
        category: tag,
        kind,
        unit_value: kind === "VOUCHER" ? parsedUnitValue : undefined,
      });
      if (parsedBalance !== undefined) {
        await api.addCashBalance(acc.id, { entry_date: todayISO(), balance: parsedBalance });
      }
      setName("");
      setBalance("");
      setUnitValue("");
      setShowAdd(false);
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  function startEdit(pos: CashPosition) {
    setEditingId(pos.account_id);
    setEditValue(String(pos.balance));
    setEditDate(todayISO());
    setError(null);
  }

  async function saveEdit(pos: CashPosition) {
    const num = parseLocaleFloat(editValue);
    if (isNaN(num)) {
      setError("That balance isn't a number.");
      return;
    }
    setError(null);
    setEditSaving(true);
    try {
      await api.addCashBalance(pos.account_id, { entry_date: editDate, balance: num });
      setEditingId(null);
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setEditSaving(false);
    }
  }

  async function handleDelete(pos: CashPosition) {
    if (!confirm(`Remove "${pos.account_name}"? It disappears from this list and today's totals, but its balance history is kept so past dates stay accurate.`))
      return;
    setError(null);
    try {
      await api.deleteCashAccount(pos.account_id);
      onChanged();
    } catch (e) {
      setError(errorText(e));
    }
  }

  function startEditDetails(pos: CashPosition) {
    setError(null);
    setEditingDetailsId(pos.account_id);
    setDetailsName(pos.account_name);
    setDetailsCurrency(pos.currency);
    setDetailsCategory(pos.category);
    setDetailsUnitValue(pos.unit_value != null ? String(pos.unit_value) : "");
  }

  async function saveEditDetails(pos: CashPosition) {
    if (!detailsName.trim()) {
      setError("An account needs a name.");
      return;
    }
    setError(null);
    let parsedUnitValue: number | undefined;
    if (pos.kind === "VOUCHER") {
      parsedUnitValue = parseLocaleFloat(detailsUnitValue);
      if (!(parsedUnitValue > 0)) {
        setError("Enter a unit value greater than 0 for a voucher account.");
        return;
      }
      // A voucher balance is a unit count, valued at whatever the unit is
      // worth *now* -- for every date, including past ones. Changing it
      // therefore re-values this account's entire history, while the euro
      // amounts already frozen on its transactions stay as they were.
      if (
        parsedUnitValue !== pos.unit_value &&
        !confirm(
          `Changing the unit value to ${parsedUnitValue} re-values this account's whole history, ` +
            `including past dates on the net worth chart. Amounts already logged on transactions ` +
            `keep the value they had. Continue?`
        )
      ) {
        return;
      }
    }
    setDetailsSaving(true);
    try {
      await api.updateCashAccount(pos.account_id, {
        name: detailsName.trim(),
        currency: detailsCurrency,
        category: detailsCategory,
        ...(pos.kind === "VOUCHER" ? { unit_value: parsedUnitValue } : {}),
      });
      setEditingDetailsId(null);
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setDetailsSaving(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="font-display text-lg flex items-center gap-2">
            {title}
            {tooltip && <InfoTooltip>{tooltip}</InfoTooltip>}
          </h2>
          {!allowManualUpdate && (
            <p className="text-xs text-muted mt-0.5">
              Balance is managed by Transactions now — log an income/expense there instead of
              editing it here.
            </p>
          )}
        </div>
        <button className="btn-primary text-sm" onClick={() => (showAdd ? setShowAdd(false) : openAdd())}>
          + Add
        </button>
      </div>

      {showAdd && (
        <>
          {allowPositions && (
            <div className="mb-3">
              <SegmentedControl
                options={[
                  { value: "balance", label: "Cash balance" },
                  { value: "position", label: "Position" },
                ]}
                value={addKind}
                onChange={setAddKind}
              />
            </div>
          )}

          {allowPositions && addKind === "position" ? (
            <AddPositionForm
              portfolioId={portfolioId}
              allAssets={allAssets}
              defaultCategory={defaultCategory}
              onDone={() => {
                setShowAdd(false);
                onChanged();
              }}
            />
          ) : (
        <form onSubmit={handleAdd} className="card p-5 mb-4 space-y-3">
          {canOfferVoucherKind && (
            <div>
              <label className="field-label">Kind</label>
              <SegmentedControl
                options={[
                  { value: "CURRENCY", label: "Currency balance" },
                  { value: "VOUCHER", label: "Vouchers (e.g. meal vouchers)" },
                ]}
                value={kind}
                onChange={setKind}
              />
            </div>
          )}
          <div className="flex items-end gap-3 flex-wrap">
            <div className="flex-1 min-w-[160px]">
              <label className="field-label">Name</label>
              <input
                className="input w-full"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={
                  kind === "VOUCHER"
                    ? "e.g. Meal vouchers"
                    : defaultCategory === "EMERGENCY_FUND"
                      ? "e.g. Emergency Fund"
                      : defaultCategory === "PENSION_FUND"
                        ? "e.g. COMETA"
                        : "e.g. Revolut, Trade Republic"
                }
                autoFocus
              />
            </div>
            <div>
              <label className="field-label">Tag</label>
              <select className="input" value={tag} onChange={(e) => setTag(e.target.value as AllocationCategory)}>
                {BALANCE_TAGS.map((t) => (
                  <option key={t} value={t}>
                    {ALLOCATION_CATEGORY_LABELS[t]}
                  </option>
                ))}
              </select>
            </div>
            {kind === "VOUCHER" ? (
              <div>
                <label className="field-label">
                  Unit value ({baseCurrency})
                </label>
                <input
                  className="input"
                  value={unitValue}
                  onChange={(e) => setUnitValue(e.target.value)}
                  placeholder="e.g. 7.00"
                  inputMode="decimal"
                />
              </div>
            ) : (
              <div>
                <label className="field-label">Currency</label>
                <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  <option>EUR</option>
                  <option>USD</option>
                  <option>GBP</option>
                  <option>CHF</option>
                </select>
              </div>
            )}
            <div>
              <label className="field-label">
                {kind === "VOUCHER" ? "Starting quantity" : "Starting balance"}
              </label>
              <input className="input" value={balance} onChange={(e) => setBalance(e.target.value)} placeholder="0" inputMode="decimal" />
            </div>
            <button className="btn-primary" disabled={saving}>
              {saving ? "Saving…" : "Create"}
            </button>
          </div>
        </form>
          )}
        </>
      )}

      {/* Covers every write in this section -- creating an account, updating
          a balance, editing details, removing -- since any of them can be
          the one that failed and they all share a single message. */}
      {error && (
        <div className="mb-4">
          <WarningCard>{error}</WarningCard>
        </div>
      )}

      {positions.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          {emptyHint ? `${emptyHint} None added yet.` : "None added yet."}
        </div>
      ) : (
        <ResponsiveTable
          keyFor={(pos) => pos.account_id}
          rows={positions}
          columns={
            [
              {
                header: "Name",
                className: "font-sans",
                cell: (pos) =>
                  editingDetailsId === pos.account_id ? (
                    <input
                      className="input w-full"
                      value={detailsName}
                      onChange={(e) => setDetailsName(e.target.value)}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveEditDetails(pos);
                        if (e.key === "Escape") setEditingDetailsId(null);
                      }}
                    />
                  ) : (
                    pos.account_name
                  ),
              },
              {
                header: "Tag",
                className: "text-xs font-sans",
                cell: (pos) =>
                  editingDetailsId === pos.account_id ? (
                    <select
                      className="input text-xs"
                      value={detailsCategory}
                      onChange={(e) => setDetailsCategory(e.target.value as AllocationCategory)}
                    >
                      {BALANCE_TAGS.map((t) => (
                        <option key={t} value={t}>
                          {ALLOCATION_CATEGORY_LABELS[t]}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full border ledger-rule text-brass-dim">
                      {ALLOCATION_CATEGORY_LABELS[pos.category]}
                    </span>
                  ),
              },
              {
                header: "Currency",
                className: "text-muted",
                cell: (pos) =>
                  editingDetailsId === pos.account_id ? (
                    pos.kind === "VOUCHER" ? (
                      <input
                        className="input w-24 text-xs text-right"
                        value={detailsUnitValue}
                        onChange={(e) => setDetailsUnitValue(e.target.value)}
                        placeholder="Unit value"
                        inputMode="decimal"
                      />
                    ) : (
                      <input
                        className="input w-20 text-xs"
                        value={detailsCurrency}
                        onChange={(e) => setDetailsCurrency(e.target.value.toUpperCase())}
                        maxLength={3}
                      />
                    )
                  ) : pos.kind === "VOUCHER" ? (
                    `${formatMoneyPrecise(pos.unit_value ?? 0, pos.currency)}/unit`
                  ) : (
                    pos.currency
                  ),
              },
              {
                header: "Balance",
                className: "text-right num",
                headClassName: "text-right",
                cell: (pos) =>
                  editingId === pos.account_id ? (
                    <div className="flex flex-col items-end gap-1">
                      <input
                        className="input w-32 text-right"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        autoFocus
                        inputMode="decimal"
                        onKeyDown={(e) => {
                          if (e.key === "Enter") saveEdit(pos);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                      />
                      <input
                        type="date"
                        className="input w-32 text-right text-xs"
                        value={editDate}
                        onChange={(e) => setEditDate(e.target.value)}
                        max={todayISO()}
                      />
                    </div>
                  ) : pos.kind === "VOUCHER" ? (
                    `${pos.balance.toLocaleString()} vouchers`
                  ) : (
                    formatMoneyPrecise(pos.balance, pos.currency)
                  ),
              },
              {
                header: "Value",
                className: "text-right num",
                headClassName: "text-right",
                cell: (pos) => formatMoney(pos.value_base_ccy, baseCurrency),
              },
              {
                header: "",
                noMobileLabel: true,
                className: "text-right font-sans",
                cell: (pos) => {
                  const isEditing = editingId === pos.account_id;
                  const isEditingDetails = editingDetailsId === pos.account_id;
                  return isEditingDetails ? (
                    <>
                      <button
                        className="text-brass text-xs"
                        onClick={() => saveEditDetails(pos)}
                        disabled={detailsSaving}
                      >
                        {detailsSaving ? "Saving…" : "Save"}
                      </button>
                      <button className="text-muted text-xs ml-3" onClick={() => setEditingDetailsId(null)}>
                        Cancel
                      </button>
                    </>
                  ) : isEditing ? (
                    <>
                      <button className="text-brass text-xs" onClick={() => saveEdit(pos)} disabled={editSaving}>
                        {editSaving ? "Saving…" : "Save"}
                      </button>
                      <button className="text-muted text-xs ml-3" onClick={() => setEditingId(null)}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      {allowManualUpdate && (
                        <button className="text-brass text-xs" onClick={() => startEdit(pos)}>
                          Update
                        </button>
                      )}
                      <button className="text-muted text-xs ml-3" onClick={() => startEditDetails(pos)}>
                        Edit
                      </button>
                      <button className="text-muted hover:text-loss text-xs ml-3" onClick={() => handleDelete(pos)}>
                        Remove
                      </button>
                    </>
                  );
                },
              },
            ] as ResponsiveColumn<CashPosition>[]
          }
        />
      )}

      {allowPositions && assetPositions.length > 0 && (
        <div className="mt-4">
          <p className="text-xs uppercase tracking-wide text-muted mb-2">Positions tagged {title}</p>
          <ResponsiveTable
            keyFor={(pos) => pos.asset_id}
            rows={assetPositions}
            columns={
              [
                {
                  header: "Asset",
                  className: "font-sans",
                  cell: (pos) => (
                    <Link to={`/assets/${pos.asset_id}`} className="hover:text-brass transition-colors">
                      {pos.asset_name}
                    </Link>
                  ),
                },
                { header: "Ticker", className: "text-muted text-xs", cell: (pos) => pos.ticker || "—" },
                {
                  header: "Quantity",
                  className: "text-right num",
                  headClassName: "text-right",
                  cell: (pos) => pos.quantity,
                },
                {
                  header: "Price",
                  className: "text-right num",
                  headClassName: "text-right",
                  cell: (pos) => (pos.price !== null ? formatMoneyPrecise(pos.price, pos.price_currency) : "—"),
                },
                {
                  header: "Value",
                  className: "text-right num",
                  headClassName: "text-right",
                  cell: (pos) => formatMoney(pos.value_base_ccy, baseCurrency),
                },
                {
                  header: "",
                  noMobileLabel: true,
                  className: "text-right font-sans",
                  cell: (pos) => (
                    <button
                      className="text-muted hover:text-loss text-xs"
                      onClick={() => removeAssetFromPortfolio(portfolioId, pos.asset_id, pos.asset_name, onChanged)}
                    >
                      Remove
                    </button>
                  ),
                },
              ] as ResponsiveColumn<HoldingPosition>[]
            }
          />
        </div>
      )}
    </div>
  );
}
