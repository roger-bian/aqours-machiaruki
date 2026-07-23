import L from 'leaflet';
import { MARKER_SIZE } from '../data/markerColors';

const cache = new Map<string, L.DivIcon>();

export function markerIcon(color: string, number: number): L.DivIcon {
  const key = `${color}-${number}`;
  let icon = cache.get(key);
  if (!icon) {
    icon = L.divIcon({
      className: 'stamp-marker',
      html: `<div style="
        width: ${MARKER_SIZE}px;
        height: ${MARKER_SIZE}px;
        border-radius: 50%;
        background: ${color};
        opacity: 0.85;
        color: white;
        font-size: 16px;
        display: flex;
        align-items: center;
        justify-content: center;
      ">${number}</div>`,
      iconSize: [MARKER_SIZE, MARKER_SIZE],
      iconAnchor: [MARKER_SIZE / 2, MARKER_SIZE / 2],
    });
    cache.set(key, icon);
  }
  return icon;
}

export const userMarkerIcon = L.divIcon({
  className: 'user-marker',
  html: `<div style="
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #4285F4;
    border: 2px solid white;
    box-shadow: 0 0 4px rgba(0,0,0,0.5);
  "></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});
