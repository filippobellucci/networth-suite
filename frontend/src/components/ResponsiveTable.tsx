import type { ReactNode } from "react";
import { useIsMobile } from "../context/ViewModeContext";

export interface ResponsiveColumn<T> {
  /** Header text — used as the desktop <th> and as the mobile field label. */
  header: string;
  /** Cell content for a given row. */
  cell: (row: T) => ReactNode;
  /** Extra classes for the desktop <td> (e.g. text-right, font-mono). */
  className?: string;
  /** Extra classes for the desktop <th>. */
  headClassName?: string;
  /**
   * Purely visual/action columns (e.g. an empty header for a "Remove"
   * button) don't need their header repeated as a label on every mobile
   * card — just render the cell content on its own line instead.
   */
  noMobileLabel?: boolean;
}

interface ResponsiveTableProps<T> {
  columns: ResponsiveColumn<T>[];
  rows: T[];
  keyFor: (row: T) => string;
  /** Extra classes on the outer wrapper (card on desktop, list on mobile). */
  className?: string;
}

/**
 * Same data, two renderings: a normal dense `<table>` on desktop (byte-for-byte
 * the same markup this app always used), and a stack of label:value cards
 * (one card per row) on mobile — so nothing gets clipped or forces horizontal
 * scrolling on a phone screen, at the cost of taller rows.
 */
export default function ResponsiveTable<T>({ columns, rows, keyFor, className }: ResponsiveTableProps<T>) {
  const isMobile = useIsMobile();

  if (isMobile) {
    return (
      <div className={`space-y-3 ${className ?? ""}`}>
        {rows.map((row) => (
          <div key={keyFor(row)} className="card p-4 space-y-2 text-sm">
            {columns.map((c, i) =>
              c.noMobileLabel ? (
                <div key={i} className="pt-1 first:pt-0">
                  {c.cell(row)}
                </div>
              ) : (
                <div key={i} className="flex items-start justify-between gap-3">
                  <span className="text-muted text-xs uppercase tracking-wide shrink-0 pt-0.5">{c.header}</span>
                  <span className="text-right min-w-0">{c.cell(row)}</span>
                </div>
              )
            )}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={`card overflow-hidden ${className ?? ""}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-muted border-b ledger-rule">
            {columns.map((c, i) => (
              <th key={i} className={`px-5 py-3 font-normal ${c.headClassName ?? ""}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono">
          {rows.map((row) => (
            <tr key={keyFor(row)} className="border-b ledger-rule last:border-0">
              {columns.map((c, i) => (
                <td key={i} className={`px-5 py-3 ${c.className ?? ""}`}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
