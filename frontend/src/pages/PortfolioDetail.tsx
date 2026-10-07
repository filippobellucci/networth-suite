import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import type { Asset, PortfolioSnapshot, NetWorthHistory, GrowthStats, XirrStats } from "../types";
import NetWorthChart from "../components/NetWorthChart";
import NetWorthStat from "../components/NetWorthStat";
import XirrLine from "../components/XirrLine";
import WarningCard from "../components/WarningCard";
import PositionsSection from "../components/PositionsSection";
import BalanceSection from "../components/BalanceSection";
import { errorText } from "../lib/errors";

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

  // Guards against a slower fetch for a portfolio the user has already
  // navigated away from landing AFTER a faster fetch for the new one --
  // React Router keeps this same component mounted across
  // /portfolios/:id -> /portfolios/:id2, so without this, quickly opening
  // portfolio A then B could overwrite B's just-loaded data with A's
  // stale response while the URL/header still say B.
  const latestPortfolioId = useRef(portfolioId);
  useEffect(() => {
    latestPortfolioId.current = portfolioId;
  }, [portfolioId]);

  const reload = useCallback(
    (refresh = false) => {
      const requestedId = portfolioId;
      const isStale = () => latestPortfolioId.current !== requestedId;
      if (refresh) setRefreshing(true);
      else setLoading(true);
      Promise.all([api.getSnapshot(portfolioId, refresh), api.getHistory(portfolioId), api.listAssets()])
        .then(([snap, hist, assets]) => {
          if (isStale()) return;
          setSnapshot(snap);
          setHistory(hist);
          setAllAssets(assets);
        })
        .catch((e) => {
          if (!isStale()) setError(errorText(e));
        })
        .finally(() => {
          if (isStale()) return;
          setLoading(false);
          setRefreshing(false);
        });
      api
        .getPortfolioGrowth(portfolioId)
        .then((g) => !isStale() && setGrowth(g))
        .catch(() => !isStale() && setGrowth(null));
      api
        .getPortfolioXirr(portfolioId)
        .then((x) => !isStale() && setXirr(x))
        .catch(() => !isStale() && setXirr(null));
    },
    [portfolioId]
  );

  useEffect(() => reload(false), [reload]);

  // Memoized so its identity only changes when portfolioId does -- an
  // inline arrow passed straight as a prop gets a new identity on every
  // render, which made useIntradayData's effect (keyed on this function's
  // identity) re-fetch and flash "Loading hourly prices…" on every
  // unrelated re-render of this page (e.g. opening the "Add position"
  // form) while viewing the "Day" range.
  const fetchPortfolioIntraday = useCallback(() => api.getPortfolioIntraday(portfolioId), [portfolioId]);

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

      {snapshot.fx_unavailable && (
        <WarningCard>
          An exchange rate couldn't be fetched, so amounts in a currency other than{" "}
          {snapshot.base_currency} are counted here at 1:1 — the totals below are not converted
          correctly. Check the price-feed service in "Modules & Status", then use "↻ Refresh prices".
        </WarningCard>
      )}

      {hasUnavailablePrice && (
        <WarningCard>
          Some prices couldn't be fetched. Make sure the ticker is a valid Yahoo Finance symbol —
          non-US listings usually need an exchange suffix (e.g. <span className="font-mono">SWDA.MI</span>{" "}
          for Milan, <span className="font-mono">.DE</span> for Xetra, <span className="font-mono">.AS</span>{" "}
          for Amsterdam). If the ticker looks correct, check the price-feed service logs
          (<span className="font-mono">docker compose logs price-feed</span>) for the underlying error.
        </WarningCard>
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
            fetchIntraday={fetchPortfolioIntraday}
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
        allowPositions
        allAssets={allAssets}
        assetPositions={snapshot.positions.filter((p) => p.category === "EMERGENCY_FUND")}
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
