import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import type { ReactNode } from "react";
import type { Asset, AssetClass, AllocationCategory, CashPosition, PortfolioSnapshot, NetWorthHistory, GrowthStats, XirrStats, CashAccountKind } from "../types";
import InfoTooltip from "../components/InfoTooltip";
import { ASSET_CLASS_LABELS, ALLOCATION_CATEGORY_LABELS } from "../types";
import { formatMoney, formatMoneyPrecise, todayISO } from "../lib/format";
import NetWorthChart from "../components/NetWorthChart";
import NetWorthStat from "../components/NetWorthStat";
import XirrLine from "../components/XirrLine";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";
import SegmentedControl from "../components/SegmentedControl";

const ASSET_CLASSES: AssetClass[] = ["ETF", "STOCK", "BOND", "CRYPTO", "REAL_ESTATE", "PENSION_FUND", "OTHER"];

export default function PortfolioDetail() {
  const { id } = useParams<{ id: string }>();
  const portfolioId = id!;

  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [history, setHistory] = useState<NetWorthHistory | null>(null);
  const [growth, setGrowth] = useState<GrowthStats | null>(null);
  const [xirr, setXirr] = useState<XirrStats | null>(null);
  const [allAssets, setAllAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(
    (refresh = false) => {
      if (refresh) setRefreshing(true);
      else setLoading(true);
      Promise.all([api.getSnapshot(portfolioId, refresh), api.getHistory(portfolioId), api.listAssets()])
        .then(([snap, hist, assets]) => {
          setSnapshot(snap);
          setHistory(hist);
          setAllAssets(assets);
        })
        .catch((e) => setError(String(e.message || e)))
        .finally(() => {
          setLoading(false);
          setRefreshing(false);
        });
      api.getPortfolioGrowth(portfolioId).then(setGrowth).catch(() => setGrowth(null));
      api.getPortfolioXirr(portfolioId).then(setXirr).catch(() => setXirr(null));
    },
    [portfolioId]
  );

  useEffect(() => reload(false), [reload]);

  if (loading) return <div className="text-muted">Loading portfolio…</div>;
  if (error)
    return (
      <div className="card p-6 border-loss/40">
        <p className="text-loss text-sm">{error}</p>
      </div>
    );
  if (!snapshot) return null;

  const hasUnavailablePrice = snapshot.positions.some((p) => p.price_source === "unavailable");

  const emergencyFund = snapshot.cash_positions.filter((p) => p.category === "EMERGENCY_FUND");
  const cash = snapshot.cash_positions.filter((p) => p.category === "CASH");
  const pension = snapshot.cash_positions.filter((p) => p.category === "PENSION_FUND");

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/portfolios" className="text-muted text-xs hover:text-brass">
            ← Portfolios
          </Link>
          <h1 className="font-display text-2xl mt-1">{snapshot.portfolio_name}</h1>
        </div>
        <button className="btn-ghost text-sm" onClick={() => reload(true)} disabled={refreshing}>
          {refreshing ? "Refreshing prices…" : "↻ Refresh prices"}
        </button>
      </div>

      {hasUnavailablePrice && (
        <div className="card p-4 border-loss/40 text-sm text-loss">
          Some prices couldn't be fetched. Make sure the ticker is a valid Yahoo Finance symbol —
          non-US listings usually need an exchange suffix (e.g. <span className="font-mono">SWDA.MI</span>{" "}
          for Milan, <span className="font-mono">.DE</span> for Xetra, <span className="font-mono">.AS</span>{" "}
          for Amsterdam). If the ticker looks correct, check the price-feed service logs
          (<span className="font-mono">docker compose logs price-feed</span>) for the underlying error.
        </div>
      )}

      <div className="card p-8">
        <NetWorthStat label="Net worth" value={snapshot.net_worth_base_ccy} currency={snapshot.base_currency} />
        <div className="grid grid-cols-2 gap-8 mt-6 pt-6 border-t ledger-rule">
          <NetWorthStat label="Invested" value={snapshot.invested_total_base_ccy} currency={snapshot.base_currency} size="md" />
          <NetWorthStat label="Other" value={snapshot.cash_total_base_ccy} currency={snapshot.base_currency} size="md" />
        </div>
        <XirrLine xirr={xirr} />
        <div className="mt-8">
          <NetWorthChart
            points={history?.points ?? []}
            currency={snapshot.base_currency}
            growth={growth}
            fetchIntraday={() => api.getPortfolioIntraday(portfolioId)}
          />
        </div>
      </div>

      <PositionsSection
        snapshot={snapshot}
        allAssets={allAssets}
        portfolioId={portfolioId}
        onChanged={() => reload(false)}
      />

      <BalanceSection
        title="Emergency Fund"
        defaultCategory="EMERGENCY_FUND"
        positions={emergencyFund}
        portfolioId={portfolioId}
        baseCurrency={snapshot.base_currency}
        onChanged={() => reload(false)}
        emptyHint="A pot you'd only touch for real emergencies — kept separate from everyday cash on purpose."
        allowManualUpdate={false}
      />

      <BalanceSection
        title="Cash"
        defaultCategory="CASH"
        positions={cash}
        portfolioId={portfolioId}
        baseCurrency={snapshot.base_currency}
        onChanged={() => reload(false)}
        allowManualUpdate={false}
      />

      <BalanceSection
        title="Pension Fund"
        defaultCategory="PENSION_FUND"
        positions={pension}
        portfolioId={portfolioId}
        baseCurrency={snapshot.base_currency}
        onChanged={() => reload(false)}
        emptyHint="Tracked like a cash balance: update it by hand whenever you check the provider's site."
        tooltip={
          <p>
            Pension funds are tracked the same way as a cash balance — a name and a balance you
            update by hand whenever you check the provider's site. There's no contribution or
            projection modeling here; that was tried once as a separate feature and then
            deliberately removed in favor of this simpler model.
          </p>
        }
      />
    </div>
  );
}

// ---------------------------------------------------------------- Positions
function PositionsSection({
  snapshot,
  allAssets,
  portfolioId,
  onChanged,
}: {
  snapshot: PortfolioSnapshot;
  allAssets: Asset[];
  portfolioId: string;
  onChanged: () => void;
}) {
  const [showAdd, setShowAdd] = useState(false);

  async function removeAsset(assetId: string, assetName: string) {
    if (!confirm(`Remove "${assetName}" from this portfolio? This will delete all history for this position.`))
      return;
    const entries = await api.listHoldings(portfolioId, assetId);
    await Promise.all(entries.map((e) => api.deleteHolding(e.id)));
    onChanged();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-display text-lg">Positions</h2>
        <button className="btn-primary text-sm" onClick={() => setShowAdd((s) => !s)}>
          + Add position
        </button>
      </div>

      {showAdd && (
        <AddPositionForm
          portfolioId={portfolioId}
          allAssets={allAssets}
          onDone={() => {
            setShowAdd(false);
            onChanged();
          }}
        />
      )}

      {snapshot.positions.length === 0 ? (
        <div className="card p-6 text-muted text-sm">No holdings in this portfolio yet.</div>
      ) : (
        <ResponsiveTable
          keyFor={(pos) => pos.asset_id}
          rows={snapshot.positions}
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
                header: "Type",
                className: "font-sans text-muted text-xs",
                cell: (pos) => ASSET_CLASS_LABELS[pos.asset_class],
              },
              {
                header: "Tag",
                className: "text-xs font-sans",
                cell: (pos) =>
                  pos.category ? (
                    <span className="px-2 py-0.5 rounded-full border ledger-rule text-brass-dim">
                      {ALLOCATION_CATEGORY_LABELS[pos.category]}
                    </span>
                  ) : (
                    <span className="text-muted">—</span>
                  ),
              },
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
                cell: (pos) => (
                  <>
                    {pos.price !== null ? formatMoneyPrecise(pos.price, pos.price_currency) : "—"}
                    {pos.price_source === "historical_fallback" && (
                      <span className="inline-flex items-center gap-1 ml-1">
                        <span className="text-brass-dim text-xs font-sans">≈</span>
                        <InfoTooltip>
                          <p>
                            The real historical price for this date couldn't be fetched (usually a
                            temporary Yahoo Finance issue, or right after restarting the app when
                            its price cache is empty), so today's price is used here as an
                            approximation instead of counting this position as worth nothing.
                          </p>
                        </InfoTooltip>
                      </span>
                    )}
                    {pos.price_source === "unavailable" && (
                      <span className="inline-flex items-center gap-1 ml-1">
                        <span className="text-loss text-xs font-sans">n/a</span>
                        <InfoTooltip>
                          <p className="mb-2">
                            Yahoo Finance (this app's price source) couldn't find a quote for this
                            asset's exact ticker.
                          </p>
                          <p className="mb-2">
                            The most common cause is a missing or wrong <strong>exchange
                            suffix</strong> — non-US listings need one, e.g.{" "}
                            <span className="font-mono">.MI</span> for Milan,{" "}
                            <span className="font-mono">.DE</span> for Xetra/Frankfurt,{" "}
                            <span className="font-mono">.AS</span> for Amsterdam,{" "}
                            <span className="font-mono">.PA</span> for Paris. The same fund is
                            sometimes cross-listed on several exchanges under different suffixes —
                            search the ticker on{" "}
                            <span className="font-mono">finance.yahoo.com</span> to confirm which
                            one Yahoo actually lists it under.
                          </p>
                          <p>
                            If the ticker looks correct, check the price-feed service's own logs
                            (<span className="font-mono">docker compose logs price-feed</span>) for
                            the underlying error — it could be a temporary Yahoo Finance
                            connectivity issue rather than a wrong ticker.
                          </p>
                        </InfoTooltip>
                      </span>
                    )}
                    {pos.price_source === "manual" && (
                      <span className="text-brass-dim text-xs ml-1 font-sans">manual</span>
                    )}
                  </>
                ),
              },
              {
                header: "Value",
                className: "text-right num",
                headClassName: "text-right",
                cell: (pos) => formatMoney(pos.value_base_ccy, snapshot.base_currency),
              },
              {
                header: "",
                noMobileLabel: true,
                className: "text-right font-sans",
                cell: (pos) => (
                  <button
                    className="text-muted hover:text-loss text-xs"
                    onClick={() => removeAsset(pos.asset_id, pos.asset_name)}
                  >
                    Remove
                  </button>
                ),
              },
            ] as ResponsiveColumn<(typeof snapshot.positions)[number]>[]
          }
        />
      )}
    </div>
  );
}

function AddPositionForm({
  portfolioId,
  allAssets,
  onDone,
}: {
  portfolioId: string;
  allAssets: Asset[];
  onDone: () => void;
}) {
  const [mode, setMode] = useState<"existing" | "new">(allAssets.length ? "existing" : "new");
  const [assetId, setAssetId] = useState(allAssets[0]?.id ?? "");
  const [quantity, setQuantity] = useState("");
  const [manualPrice, setManualPrice] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // new asset fields
  const [newName, setNewName] = useState("");
  const [newTicker, setNewTicker] = useState("");
  const [newClass, setNewClass] = useState<AssetClass>("ETF");
  const [newCategory, setNewCategory] = useState<AllocationCategory | "">("");
  const [newCurrency, setNewCurrency] = useState("EUR");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      let finalAssetId = assetId;
      if (mode === "new") {
        if (!newName.trim()) throw new Error("Asset name is required");
        const created = await api.createAsset({
          name: newName.trim(),
          ticker: newTicker.trim() || undefined,
          asset_class: newClass,
          category: newCategory || null,
          currency: newCurrency,
        } as any);
        finalAssetId = created.id;
      }
      if (!finalAssetId) throw new Error("Select an asset");
      const qty = parseFloat(quantity);
      if (isNaN(qty)) throw new Error("Invalid quantity");

      await api.addHolding(portfolioId, {
        asset_id: finalAssetId,
        entry_date: todayISO(),
        quantity: qty,
        manual_price: manualPrice ? parseFloat(manualPrice) : null,
      });
      onDone();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-5 mb-4 space-y-4">
      <div className="flex gap-4 text-sm">
        <button
          type="button"
          className={mode === "existing" ? "text-brass" : "text-muted"}
          onClick={() => setMode("existing")}
        >
          Existing asset
        </button>
        <button type="button" className={mode === "new" ? "text-brass" : "text-muted"} onClick={() => setMode("new")}>
          + New asset
        </button>
      </div>

      {mode === "existing" ? (
        <select className="input w-full" value={assetId} onChange={(e) => setAssetId(e.target.value)}>
          {allAssets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} {a.ticker ? `(${a.ticker})` : ""}
            </option>
          ))}
        </select>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <input className="input" placeholder="Name (e.g. iShares Core MSCI World)" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <input className="input" placeholder="Ticker (optional, e.g. SWDA.MI)" value={newTicker} onChange={(e) => setNewTicker(e.target.value)} />
          <select className="input" value={newClass} onChange={(e) => setNewClass(e.target.value as AssetClass)}>
            {ASSET_CLASSES.map((c) => (
              <option key={c} value={c}>
                {ASSET_CLASS_LABELS[c]}
              </option>
            ))}
          </select>
          <select
            className="input"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value as AllocationCategory | "")}
          >
            <option value="">No tag</option>
            <option value="STOCK">Stock</option>
            <option value="BOND">Bond</option>
          </select>
          <select className="input" value={newCurrency} onChange={(e) => setNewCurrency(e.target.value)}>
            <option>EUR</option>
            <option>USD</option>
            <option>GBP</option>
            <option>CHF</option>
          </select>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs uppercase tracking-wide text-muted block mb-1">Quantity</label>
          <input className="input w-full" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="e.g. 12.5" />
        </div>
        <div>
          <label className="text-xs uppercase tracking-wide text-muted block mb-1">
            Manual price <span className="normal-case">(leave empty to use the live price via ticker)</span>
          </label>
          <input className="input w-full" value={manualPrice} onChange={(e) => setManualPrice(e.target.value)} placeholder="e.g. 250000" />
        </div>
      </div>

      {error && <p className="text-loss text-sm">{error}</p>}

      <div className="flex gap-3">
        <button className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : "Add"}
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- Cash / Emergency Fund / Pension Fund
// All three are the same underlying mechanism (a named balance you update by
// hand from time to time), only the `category` tag differs -- so one
// component renders all three sections.
function BalanceSection({
  title,
  defaultCategory,
  positions,
  portfolioId,
  baseCurrency,
  onChanged,
  emptyHint,
  tooltip,
  allowManualUpdate = true,
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
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState(baseCurrency);
  const [balance, setBalance] = useState("");
  const [tag, setTag] = useState<AllocationCategory>(defaultCategory);
  const [kind, setKind] = useState<CashAccountKind>("CURRENCY");
  const [unitValue, setUnitValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  // Editing the account's own details (name/currency/tag) -- separate from
  // editing its balance above, since these were previously impossible to
  // change after creation at all (the only way was delete + recreate,
  // losing the whole balance history).
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
    setTag(defaultCategory); // reset to this section's default each time the form is (re)opened
    setKind("CURRENCY");
    setUnitValue("");
    setShowAdd(true);
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const acc = await api.createCashAccount(portfolioId, {
        name: name.trim(),
        currency: kind === "VOUCHER" ? baseCurrency : currency,
        category: tag,
        kind,
        unit_value: kind === "VOUCHER" ? parseFloat(unitValue) || 0 : undefined,
      });
      if (balance) {
        await api.addCashBalance(acc.id, { entry_date: todayISO(), balance: parseFloat(balance) });
      }
      setName("");
      setBalance("");
      setUnitValue("");
      setShowAdd(false);
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  function startEdit(pos: CashPosition) {
    setEditingId(pos.account_id);
    setEditValue(String(pos.balance));
  }

  async function saveEdit(pos: CashPosition) {
    const num = parseFloat(editValue);
    if (isNaN(num)) return;
    setEditSaving(true);
    try {
      await api.addCashBalance(pos.account_id, { entry_date: todayISO(), balance: num });
      setEditingId(null);
      onChanged();
    } finally {
      setEditSaving(false);
    }
  }

  async function handleDelete(pos: CashPosition) {
    if (!confirm(`Remove "${pos.account_name}"?`)) return;
    await api.deleteCashAccount(pos.account_id);
    onChanged();
  }

  function startEditDetails(pos: CashPosition) {
    setEditingDetailsId(pos.account_id);
    setDetailsName(pos.account_name);
    setDetailsCurrency(pos.currency);
    setDetailsCategory(pos.category);
    setDetailsUnitValue(pos.unit_value != null ? String(pos.unit_value) : "");
  }

  async function saveEditDetails(pos: CashPosition) {
    if (!detailsName.trim()) return;
    setDetailsSaving(true);
    try {
      await api.updateCashAccount(pos.account_id, {
        name: detailsName.trim(),
        currency: detailsCurrency,
        category: detailsCategory,
        ...(pos.kind === "VOUCHER" ? { unit_value: parseFloat(detailsUnitValue) || 0 } : {}),
      });
      setEditingDetailsId(null);
      onChanged();
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
        <form onSubmit={handleAdd} className="card p-5 mb-4 space-y-3">
          {canOfferVoucherKind && (
            <div>
              <label className="text-xs uppercase tracking-wide text-muted block mb-1">Kind</label>
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
              <label className="text-xs uppercase tracking-wide text-muted block mb-1">Name</label>
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
              <label className="text-xs uppercase tracking-wide text-muted block mb-1">Tag</label>
              <select className="input" value={tag} onChange={(e) => setTag(e.target.value as AllocationCategory)}>
                <option value="CASH">Cash</option>
                <option value="EMERGENCY_FUND">Emergency Fund</option>
                <option value="PENSION_FUND">Pension Fund</option>
                <option value="STOCK">Stock</option>
                <option value="BOND">Bond</option>
              </select>
            </div>
            {kind === "VOUCHER" ? (
              <div>
                <label className="text-xs uppercase tracking-wide text-muted block mb-1">
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
                <label className="text-xs uppercase tracking-wide text-muted block mb-1">Currency</label>
                <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  <option>EUR</option>
                  <option>USD</option>
                  <option>GBP</option>
                  <option>CHF</option>
                </select>
              </div>
            )}
            <div>
              <label className="text-xs uppercase tracking-wide text-muted block mb-1">
                {kind === "VOUCHER" ? "Starting quantity" : "Starting balance"}
              </label>
              <input className="input" value={balance} onChange={(e) => setBalance(e.target.value)} placeholder="0" />
            </div>
            <button className="btn-primary" disabled={saving}>
              {saving ? "Saving…" : "Create"}
            </button>
          </div>
        </form>
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
                      <option value="CASH">Cash</option>
                      <option value="EMERGENCY_FUND">Emergency Fund</option>
                      <option value="PENSION_FUND">Pension Fund</option>
                      <option value="STOCK">Stock</option>
                      <option value="BOND">Bond</option>
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
                    <input
                      className="input w-32 text-right"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveEdit(pos);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                    />
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
    </div>
  );
}
