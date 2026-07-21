import { useState, useRef, useLayoutEffect, useCallback, type ReactNode } from "react";

const PANEL_WIDTH = 288; // matches w-72
const VIEWPORT_MARGIN = 8;
const GAP = 8; // space between the "?" button and the panel

type Phase = "closed" | "measuring" | "ready";
type Coords = { top: number; left: number };

/**
 * Small circled "?" that reveals an explanatory panel on hover, keyboard
 * focus, or tap. Hover-only would leave touch/keyboard users with no way to
 * open it, so it's also toggleable via click/Enter and closes on outside
 * click or Escape.
 *
 * Positioning is a two-phase "measure, then place" process:
 *   1. "measuring" -- panel is mounted off-screen/invisible so its *real*
 *      rendered height (which depends on the actual text content and can't
 *      be guessed in advance) can be read from the DOM.
 *   2. "ready" -- using that real height, picks whichever side (above or
 *      below the button) actually has room for it, then clamps the final
 *      position so every edge stays within the viewport regardless of which
 *      side was chosen. A fixed-guess height was tried first and still let
 *      long content overflow the top edge whenever the guess was too small;
 *      measuring the real height is what actually fixes that.
 */
export default function InfoTooltip({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("closed");
  const [coords, setCoords] = useState<Coords | null>(null);
  const wrapperRef = useRef<HTMLSpanElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const measuredHeightRef = useRef<number | null>(null);

  const place = useCallback((panelHeight: number) => {
    const btn = buttonRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();

    let left = rect.left + rect.width / 2 - PANEL_WIDTH / 2;
    left = Math.max(VIEWPORT_MARGIN, Math.min(left, window.innerWidth - PANEL_WIDTH - VIEWPORT_MARGIN));

    const spaceAbove = rect.top - GAP - VIEWPORT_MARGIN;
    const spaceBelow = window.innerHeight - rect.bottom - GAP - VIEWPORT_MARGIN;

    // Prefer whichever side actually fits the real measured height; if
    // neither fits fully, prefer whichever side has more room, then clamp
    // so the panel still can't cross the top/bottom edge (it'll rely on its
    // own internal scroll -- max-h-[70vh] -- only in that leftover case).
    const openAbove = panelHeight <= spaceAbove || spaceAbove >= spaceBelow;
    let top = openAbove ? rect.top - GAP - panelHeight : rect.bottom + GAP;
    top = Math.max(VIEWPORT_MARGIN, Math.min(top, window.innerHeight - VIEWPORT_MARGIN - panelHeight));

    setCoords({ top, left });
  }, []);

  const repositionWithLastHeight = useCallback(() => {
    if (measuredHeightRef.current != null) place(measuredHeightRef.current);
  }, [place]);

  // Phase 1: once the (invisible) panel has mounted, measure its real
  // height and immediately compute its final position from that.
  useLayoutEffect(() => {
    if (phase !== "measuring") return;
    const panel = panelRef.current;
    if (!panel) return;
    const height = panel.offsetHeight;
    measuredHeightRef.current = height;
    place(height);
    setPhase("ready");
  }, [phase, place]);

  useLayoutEffect(() => {
    if (phase === "closed") return;

    const onClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setPhase("closed");
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPhase("closed");
    };
    window.addEventListener("scroll", repositionWithLastHeight, true);
    window.addEventListener("resize", repositionWithLastHeight);
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("scroll", repositionWithLastHeight, true);
      window.removeEventListener("resize", repositionWithLastHeight);
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [phase, repositionWithLastHeight]);

  const openTooltip = () => setPhase((p) => (p === "closed" ? "measuring" : p));
  const closeTooltip = () => setPhase("closed");

  return (
    <span
      ref={wrapperRef}
      className="relative inline-flex items-center"
      onMouseEnter={openTooltip}
      onMouseLeave={closeTooltip}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-label="More information"
        aria-expanded={phase !== "closed"}
        onClick={() => setPhase((p) => (p === "closed" ? "measuring" : "closed"))}
        onFocus={openTooltip}
        className="w-4 h-4 rounded-full border ledger-rule text-[10px] leading-none
                   flex items-center justify-center text-muted
                   hover:text-brass hover:border-brass-dim
                   focus-visible:text-brass focus-visible:border-brass-dim
                   transition-colors cursor-help select-none"
      >
        ?
      </button>

      {phase !== "closed" && (
        <div
          ref={panelRef}
          role="tooltip"
          style={{
            position: "fixed",
            top: coords?.top ?? 0,
            left: coords?.left ?? 0,
            width: PANEL_WIDTH,
            visibility: phase === "ready" ? "visible" : "hidden",
          }}
          className="z-50 p-3 rounded-md card shadow-lg
                     text-xs leading-relaxed text-ink-text font-normal
                     normal-case tracking-normal max-h-[70vh] overflow-y-auto"
        >
          {children}
        </div>
      )}
    </span>
  );
}
