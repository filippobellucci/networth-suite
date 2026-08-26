import { useMemo, useRef, useState } from "react";
import { geoNaturalEarth1, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import worldTopology from "world-atlas/countries-110m.json";
import type { AllocationRegion } from "../types";
import { ISO2_TO_NUMERIC } from "../lib/isoNumericCodes";
import { useTheme } from "../context/ThemeContext";
import { usePalette } from "../context/PaletteContext";
import { getChartTheme } from "../lib/chartTheme";

const WIDTH = 760;
const HEIGHT = 400;

const worldFeatures = (feature(worldTopology as any, (worldTopology as any).objects.countries) as any)
  .features as Array<{ id: string; properties: { name: string }; geometry: any }>;

export default function WorldMapChart({ regions }: { regions: AllocationRegion[] }) {
  const { theme } = useTheme();
  const { palette } = usePalette();
  const chart = getChartTheme(theme === "dark", palette);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; label: string } | null>(null);

  const { pathFor, weightByNumericId, maxWeight } = useMemo(() => {
    const projection = geoNaturalEarth1().fitSize([WIDTH, HEIGHT], { type: "Sphere" } as any);
    const path = geoPath(projection);

    const byNumeric: Record<string, { name: string; pct: number }> = {};
    let max = 0;
    for (const r of regions) {
      const numericId = ISO2_TO_NUMERIC[r.country];
      if (!numericId) continue;
      byNumeric[numericId] = { name: r.country_name, pct: r.weight_pct };
      if (r.weight_pct > max) max = r.weight_pct;
    }

    return { pathFor: path, weightByNumericId: byNumeric, maxWeight: max || 1 };
  }, [regions]);

  function colorFor(numericId: string): string {
    const entry = weightByNumericId[numericId];
    if (!entry) return chart.grid; // no allocation data for this country
    // Interpolate opacity of the accent color by weight, relative to the
    // largest single-country weight in this dataset -- keeps small
    // exposures visible instead of washing everything out next to one
    // dominant country.
    const intensity = 0.18 + 0.75 * Math.sqrt(entry.pct / maxWeight);
    return withOpacity(chart.accent, Math.min(intensity, 0.93));
  }

  return (
    <div ref={containerRef} className="relative">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto">
        {worldFeatures.map((f) => (
          <path
            key={f.id}
            d={pathFor(f as any) || undefined}
            fill={colorFor(f.id)}
            stroke={chart.panelBg}
            strokeWidth={0.5}
            onMouseMove={(e) => {
              const entry = weightByNumericId[f.id];
              const rect = containerRef.current?.getBoundingClientRect();
              if (!rect) return;
              setHover({
                x: e.clientX - rect.left,
                y: e.clientY - rect.top,
                label: entry ? `${entry.name} — ${entry.pct.toFixed(2)}%` : f.properties?.name || "",
              });
            }}
            onMouseLeave={() => setHover(null)}
            className="cursor-default"
          />
        ))}
      </svg>
      {hover && (
        <div
          className="absolute pointer-events-none px-2 py-1 rounded text-xs font-mono border ledger-rule"
          style={{
            left: hover.x + 12,
            top: hover.y + 12,
            background: chart.panelBg,
            borderColor: chart.grid,
            color: chart.text,
          }}
        >
          {hover.label}
        </div>
      )}
    </div>
  );
}

function withOpacity(hex: string, opacity: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}
