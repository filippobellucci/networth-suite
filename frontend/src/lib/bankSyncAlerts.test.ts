import { describe, it, expect } from "vitest";
import { bankSyncAlerts, EXPIRY_WARNING_DAYS, type BankLinkStatus, type BankSyncStatus } from "./bankSyncAlerts";

const NOW = new Date("2026-10-01T12:00:00+00:00");
const daysFromNow = (d: number) => new Date(NOW.getTime() + d * 86400000).toISOString();
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3600000).toISOString();

function link(over: Partial<BankLinkStatus> = {}): BankLinkStatus {
  return {
    label: "Revolut",
    aspsp_name: "Revolut",
    status: "ACTIVE",
    valid_until: daysFromNow(60),
    last_synced_at: hoursAgo(2),
    last_error: null,
    authorize_url: "http://nas:8003/authorize/Revolut",
    ...over,
  };
}

function status(...links: BankLinkStatus[]): BankSyncStatus {
  return { status_page_url: "http://nas:8003/", sync_interval_hours: 6, links };
}

describe("bankSyncAlerts", () => {
  it("says nothing while everything is fine", () => {
    expect(bankSyncAlerts(status(link()), NOW)).toEqual([]);
    expect(bankSyncAlerts(status(), NOW)).toEqual([]);
  });

  it("warns a week ahead of the consent running out, with a re-authorize link", () => {
    const [alert] = bankSyncAlerts(status(link({ valid_until: daysFromNow(5) })), NOW);
    expect(alert.level).toBe("warning");
    expect(alert.message).toContain("expires in 5 days");
    expect(alert.actionUrl).toBe("http://nas:8003/authorize/Revolut");
    expect(bankSyncAlerts(status(link({ valid_until: daysFromNow(EXPIRY_WARNING_DAYS + 1) })), NOW)).toEqual([]);
  });

  it("says 1 day, not 0, on the last day", () => {
    const [alert] = bankSyncAlerts(status(link({ valid_until: daysFromNow(0.2) })), NOW);
    expect(alert.message).toContain("expires in 1 day ");
  });

  it("treats a consent past its date as expired even before the link is flipped", () => {
    const [alert] = bankSyncAlerts(status(link({ valid_until: daysFromNow(-1) })), NOW);
    expect(alert.level).toBe("error");
    expect(alert.message).toContain("expired");
  });

  it("reports an expired or failed link as an error", () => {
    const alerts = bankSyncAlerts(
      status(link({ status: "EXPIRED", label: "A" }), link({ status: "ERROR", label: "B", last_error: "denied" })),
      NOW,
    );
    expect(alerts.map((a) => a.level)).toEqual(["error", "error"]);
    expect(alerts[1].message).toContain("denied");
  });

  it("mentions a link that was never authorized", () => {
    const [alert] = bankSyncAlerts(status(link({ status: "PENDING", valid_until: null, last_synced_at: null })), NOW);
    expect(alert.actionLabel).toBe("Authorize");
  });

  it("notices syncing has stopped, but not after one missed cycle", () => {
    expect(bankSyncAlerts(status(link({ last_synced_at: hoursAgo(13) })), NOW)).toEqual([]);
    const [alert] = bankSyncAlerts(status(link({ last_synced_at: hoursAgo(30), last_error: "timeout" })), NOW);
    expect(alert.message).toContain("No successful sync");
    expect(alert.message).toContain("timeout");
  });

  it("uses three sync intervals as the threshold when that is longer than a day", () => {
    const s = { ...status(link({ last_synced_at: hoursAgo(40) })), sync_interval_hours: 24 };
    expect(bankSyncAlerts(s, NOW)).toEqual([]);
  });

  it("passes on a problem from the last sync", () => {
    const [alert] = bankSyncAlerts(status(link({ last_error: "2 transaction(s) failed" })), NOW);
    expect(alert.level).toBe("warning");
    expect(alert.message).toContain("2 transaction(s) failed");
  });

  it("puts errors before warnings", () => {
    const alerts = bankSyncAlerts(
      status(link({ label: "A", valid_until: daysFromNow(3) }), link({ label: "B", status: "EXPIRED" })),
      NOW,
    );
    expect(alerts.map((a) => a.label)).toEqual(["B", "A"]);
  });

  it("reports a balance that doesn't match the bank's", () => {
    const balance = { bank: 243.15, bank_type: "ITAV", app: 240, currency: "EUR", difference: 3.15, checked_at: hoursAgo(1) };
    const [alert] = bankSyncAlerts(status(link({ balance })), NOW);
    expect(alert.level).toBe("warning");
    expect(alert.message).toContain("243.15 EUR");
    expect(alert.message).toContain("+3.15 EUR");
    expect(alert.actionUrl).toBeUndefined();
  });

  it("stays quiet when the balances match, or can't be compared", () => {
    const base = { bank: 240, bank_type: "ITAV", app: 240, currency: "EUR", checked_at: hoursAgo(1) };
    expect(bankSyncAlerts(status(link({ balance: { ...base, difference: 0 } })), NOW)).toEqual([]);
    expect(bankSyncAlerts(status(link({ balance: { ...base, difference: 0.004 } })), NOW)).toEqual([]);
    expect(bankSyncAlerts(status(link({ balance: { ...base, difference: null } })), NOW)).toEqual([]);
    expect(bankSyncAlerts(status(link({ balance: null })), NOW)).toEqual([]);
  });
});
