import { useMap } from 'react-leaflet';
import type { UserPosition } from '../hooks/useUserLocation';

const BUTTON_STYLE: React.CSSProperties = {
  position: 'fixed',
  bottom: 20,
  right: 10,
  zIndex: 900,
  width: 44,
  height: 44,
  borderRadius: '50%',
  backgroundColor: 'white',
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
  border: 'none',
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 0,
};

// close enough to see individual streets/blocks around the user
const SURROUNDINGS_ZOOM = 17;

type Props = {
  onLocate: () => Promise<UserPosition>;
  locating: boolean;
};

export function LocateButton({ onLocate, locating }: Props) {
  const map = useMap();

  async function handleClick() {
    const pos = await onLocate();
    if (pos) map.flyTo([pos.lat, pos.lon], SURROUNDINGS_ZOOM);
  }

  return (
    <button style={BUTTON_STYLE} onClick={handleClick} disabled={locating} aria-label="現在地に移動">
      {locating ? (
        <span className="spinner" />
      ) : (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4285F4" strokeWidth="2">
          <circle cx="12" cy="12" r="3" fill="#4285F4" stroke="none" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3" strokeLinecap="round" />
          <circle cx="12" cy="12" r="7" />
        </svg>
      )}
    </button>
  );
}
