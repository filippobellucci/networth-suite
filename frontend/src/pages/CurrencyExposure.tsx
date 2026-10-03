import SnapshotBreakdown from "../components/SnapshotBreakdown";

export default function CurrencyExposure() {
  return (
    <SnapshotBreakdown
      info={
        <>
          <p className="mb-2">
            This shows the <strong>quotation currency</strong> — the currency each position or
            cash balance is actually held/quoted in — not a true look-through into what a fund
            holds internally.
          </p>
          <p>
            Example: a EUR-listed ETF that invests in US stocks still counts entirely as EUR
            here, because that's the currency it's quoted and traded in, even though its
            underlying holdings are USD-denominated.
          </p>
        </>
      }
      emptyMessage="No positions or balances yet in this portfolio."
      groupHeader="Currency"
      positionGroup={(p) => p.price_currency}
      cashGroup={(c) => c.currency}
      colorOf={(_key, i, chart) => chart.categorical[i % chart.categorical.length]}
    />
  );
}
