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

export function FilterPanel({ activeFilters, onToggle }: Props) {
  return (
    <div style={FILTER_PANEL_STYLE}>
      <div style={{ fontWeight: 'bold', marginBottom: 4 }}>未獲得</div>
      <label style={{ display: 'block' }}>
        <input
          type="checkbox"
          checked={activeFilters.has('stamp_missing')}
          onChange={() => onToggle('stamp_missing')}
        />
        {' '}スタンプ
      </label>
      <label style={{ display: 'block' }}>
        <input
          type="checkbox"
          checked={activeFilters.has('badge_missing')}
          onChange={() => onToggle('badge_missing')}
        />
        {' '}缶バッジ
      </label>
    </div>
  );
}
