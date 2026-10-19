import { useIsMobile } from "../context/ViewModeContext";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

interface SegmentedControlProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/**
 * A pill track of toggle buttons on desktop. On mobile,
 * where several of these rows side by side would overflow the screen width,
 * it becomes a single native <select> instead — same options, no horizontal
 * overflow.
 */
export default function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className,
}: SegmentedControlProps<T>) {
  const isMobile = useIsMobile();

  if (isMobile) {
    return (
      <select
        className={`input text-xs ${className ?? ""}`}
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }

  return (
    <div className={`inline-flex w-fit gap-0.5 p-1 rounded-full bg-ink-raised border ledger-rule text-xs ${className ?? ""}`}>
      {options.map((o) => (
        <button
          type="button"
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`px-3 py-1.5 rounded-full transition-colors ${
            value === o.value ? "bg-brass text-ink font-semibold shadow-sm" : "text-muted hover:text-ink-text"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
