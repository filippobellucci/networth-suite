import { useMemo } from "react";
import type { AssetPricePoint, AssetIntradayPoint, GrowthStats } from "../types";
import { formatMoneyPrecise } from "../lib/format";
import InfoTooltip from "./InfoTooltip";
import RangeAreaChart from "./RangeAreaChart";
import type { RangeKey } from "./chartHelpers";

const RANGES_WITH_DAY: RangeKey[] = ["D", "W", "M", "Y", "MAX"];
const RANGES_WITHOUT_DAY: RangeKey[] = ["W", "M", "Y", "MAX"];

export default function AssetPriceChart({
  points,
  currency = "EUR",
  height = 260,
  growth,
  fetchIntraday,
}: {
  points: AssetPricePoint[];
  currency?: string;
  height?: number;
  growth?: GrowthStats | null;
  /** Only provided for ticker-based assets -- manual-priced ones have no hourly data. */
  fetchIntraday?: () => Promise<AssetIntradayPoint[]>;
}) {
  const rows = useMemo(() => points.map((p) => ({ date: p.date, value: p.price })), [points]);

  // See NetWorthChart for why this is memoized on the incoming fetcher.
  const fetchHourly = useMemo(
    () =>
      fetchIntraday
        ? () => fetchIntraday().then((pts) => pts.map((p) => ({ time: p.time, value: p.price })))
        : undefined,
    [fetchIntraday]
  );

  return (
    <RangeAreaChart
      points={rows}
      ranges={fetchIntraday ? RANGES_WITH_DAY : RANGES_WITHOUT_DAY}
      currency={currency}
      height={height}
      growth={growth}
      formatValue={formatMoneyPrecise}
      tooltipLabel="Price"
      gradientId="assetFill"
      emptyMessage="No price history yet."
      fetchIntraday={fetchHourly}
      extraControls={
        !fetchIntraday && (
          <InfoTooltip>
            <p>
              There's no "Day" view for this asset because it has no ticker — its price only
              changes when you enter a new manual price by hand, so there's no hourly data that
              could exist to show.
            </p>
          </InfoTooltip>
        )
      }
    />
  );
}
