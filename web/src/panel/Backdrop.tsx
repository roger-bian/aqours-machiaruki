const BACKDROP_STYLE: React.CSSProperties = {
  position: 'fixed',
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
  zIndex: 999,
  backgroundColor: 'rgba(0, 0, 0, 0.2)',
};

// Tapping anywhere on this (map or otherwise) closes the panel. Needed
// because marker clicks bubble to Leaflet's own map click handler by
// default - without this, a marker tap would open then immediately close
// the panel on the same tap.
export function Backdrop({ onClose }: { onClose: () => void }) {
  return <div style={BACKDROP_STYLE} onClick={onClose} />;
}
