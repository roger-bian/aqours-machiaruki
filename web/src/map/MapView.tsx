import { MapContainer, TileLayer, Marker } from 'react-leaflet';
import type { Location } from '../data/types';
import type { UserPosition } from '../hooks/useUserLocation';
import { colorFor, ringColorFor } from '../data/markerColors';
import { openStatusFor } from '../data/openStatus';
import { markerIcon, userMarkerIcon } from './markerIcon';
import { LocateButton } from './LocateButton';

type Props = {
  locations: Location[];
  onSelect: (id: number) => void;
  userPosition: UserPosition;
  onLocate: () => Promise<UserPosition>;
  locating: boolean;
  now: Date;
};

export function MapView({ locations, onSelect, userPosition, onLocate, locating, now }: Props) {
  return (
    <MapContainer
      center={[35.0938, 138.8867]}
      zoom={11}
      scrollWheelZoom
      style={{ width: '100vw', height: '100vh' }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {locations.map((loc) => (
        <Marker
          key={loc.id}
          position={[loc.lat, loc.lon]}
          icon={markerIcon(
            colorFor(loc),
            loc.id,
            ringColorFor(openStatusFor(loc.hours_json, now)),
          )}
          eventHandlers={{ click: () => onSelect(loc.id) }}
        />
      ))}
      {userPosition && (
        <Marker position={[userPosition.lat, userPosition.lon]} icon={userMarkerIcon} />
      )}
      <LocateButton onLocate={onLocate} locating={locating} />
    </MapContainer>
  );
}
