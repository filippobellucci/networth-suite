/**
 * What, if anything, needs saying about bank sync -- worked out here, in a
 * pure function, from the status bank-sync reports (see its GET /status).
 *
 * The reason it exists: a bank's consent lasts 90 days (PSD2), and when it
 * runs out syncing simply stops. bank-sync's own status page says so, but
 * it's a page nobody opens until something has already gone missing -- so
 * the app itself has to say it, a week ahead, where it's actually looked at.
 */

export type BankLinkState = "PENDING" | "AUTHORIZING" | "ACTIVE" | "EXPIRED" | "ERROR";

export interface BankLinkStatus {
  label: string;
  aspsp_name: string;
  status: BankLinkState;
  /** ISO timestamps with an explicit offset, or null. */
  valid_until: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  authorize_url: string;
  /** The bank's balance next to Net Worth Suite's, as of the last clean sync. */
  balance?: {
    bank: number;
    bank_type: string | null;
    app: number;
    currency: string | null;
    /** bank - app; null when the two are in different currencies. */
    difference: number | null;
    checked_at: string | null;
  } | null;
}

export interface BankSyncStatus {
  status_page_url: string;
  sync_interval_hours: number;
  links: BankLinkStatus[];
}

export interface BankSyncAlert {
  level: "error" | "warning";
  label: string;
  message: string;
  /** Absent when there's nothing to click -- the message says what to check. */
  actionUrl?: string;
  actionLabel?: string;
}

/** How far ahead an expiring consent is announced. */
export const EXPIRY_WARNING_DAYS = 7;
const DAY_MS = 24 * 60 * 60 * 1000;

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

/**
 * How long without a successful sync before it's worth mentioning: three
 * missed cycles, and never less than a day -- one failed cycle (the bank
 * briefly down) recovers on its own and isn't news.
 */
function staleAfterMs(syncIntervalHours: number): number {
  return Math.max(DAY_MS, 3 * syncIntervalHours * 60 * 60 * 1000);
}

export function bankSyncAlerts(status: BankSyncStatus, now: Date = new Date()): BankSyncAlert[] {
  const alerts: BankSyncAlert[] = [];
  const reauthorize = (link: BankLinkStatus) => ({ actionUrl: link.authorize_url, actionLabel: "Re-authorize" });
  const details = { actionUrl: status.status_page_url, actionLabel: "Open bank sync" };

  for (const link of status.links) {
    const name = link.label;
    if (link.status === "EXPIRED") {
      alerts.push({
        level: "error",
        label: name,
        message: `The bank's consent ${link.valid_until ? `expired on ${shortDate(link.valid_until)}` : "has expired"} — nothing is being synced from ${name} until you re-authorize.`,
        ...reauthorize(link),
      });
      continue;
    }
    if (link.status === "ERROR") {
      alerts.push({
        level: "error",
        label: name,
        message: `Authorizing ${name} failed${link.last_error ? `: ${link.last_error}` : ""}. Nothing is being synced from it.`,
        ...reauthorize(link),
      });
      continue;
    }
    if (link.status === "PENDING" || link.status === "AUTHORIZING") {
      alerts.push({
        level: "warning",
        label: name,
        message: `${name} is configured but not authorized yet, so nothing is synced from it.`,
        actionUrl: link.authorize_url,
        actionLabel: "Authorize",
      });
      continue;
    }

    // ACTIVE
    if (link.valid_until) {
      const msLeft = new Date(link.valid_until).getTime() - now.getTime();
      if (msLeft <= 0) {
        // Not flipped to EXPIRED yet -- that happens on the next sync cycle.
        alerts.push({
          level: "error",
          label: name,
          message: `The bank's consent for ${name} expired on ${shortDate(link.valid_until)} — re-authorize to keep syncing.`,
          ...reauthorize(link),
        });
        continue;
      }
      if (msLeft <= EXPIRY_WARNING_DAYS * DAY_MS) {
        const days = Math.ceil(msLeft / DAY_MS);
        alerts.push({
          level: "warning",
          label: name,
          message: `The bank's consent for ${name} expires in ${days} day${days === 1 ? "" : "s"} (${shortDate(link.valid_until)}). Re-authorize before then, or syncing stops.`,
          ...reauthorize(link),
        });
      }
    }

    const diff = link.balance?.difference;
    if (link.balance && diff !== null && diff !== undefined && Math.abs(diff) >= 0.01) {
      const fmt = (v: number) => `${v.toFixed(2)} ${link.balance!.currency ?? ""}`.trim();
      alerts.push({
        level: "warning",
        label: name,
        message:
          `${name}'s balance doesn't match: the bank reports ${fmt(link.balance.bank)}, Net Worth Suite has ` +
          `${fmt(link.balance.app)} (${diff > 0 ? "+" : ""}${fmt(diff)}). A transaction may be missing or ` +
          "deleted, or the account's opening balance may be off.",
      });
    }

    const stale =
      link.last_synced_at !== null &&
      now.getTime() - new Date(link.last_synced_at).getTime() > staleAfterMs(status.sync_interval_hours);
    if (stale) {
      alerts.push({
        level: "warning",
        label: name,
        message: `No successful sync from ${name} since ${shortDate(link.last_synced_at!)}${link.last_error ? ` — last error: ${link.last_error}` : ""}.`,
        ...details,
      });
    } else if (link.last_error) {
      alerts.push({
        level: "warning",
        label: name,
        message: `The last sync from ${name} had a problem: ${link.last_error}`,
        ...details,
      });
    }
  }
  // Errors first: those mean syncing has already stopped.
  return alerts.sort((a, b) => (a.level === b.level ? 0 : a.level === "error" ? -1 : 1));
}
