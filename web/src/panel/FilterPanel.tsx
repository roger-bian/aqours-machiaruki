import type { FilterKey } from '../data/types';

const FILTER_PANEL_STYLE: React.CSSProperties = {
  position: 'fixed',
  top: 10,
  right: 10,
  zIndex: 900,
  backgroundColor: 'white',
  padding: '8px 12px',
  borderRadius: 8,
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
  fontSize: 14,
  userSelect: 'none',
};

type Props = {
  activeFilters: Set<FilterKey>;
  onToggle: (key: FilterKey) => void;
};

// the two filters stack (AND) - see matchesFilters in data/markerColors.ts
const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'uncollected', label: '未獲得' },
  { key: 'open_now', label: '営業中のみ' },
];

export function FilterPanel({ activeFilters, onToggle }: Props) {
  return (
    <div style={FILTER_PANEL_STYLE}>
      {FILTERS.map(({ key, label }) => (
        <label key={key} style={{ display: 'block' }}>
          <input
            type="checkbox"
            checked={activeFilters.has(key)}
            onChange={() => onToggle(key)}
          />
          {' '}{label}
        </label>
      ))}
    </div>
  );
}
