import { useEffect, useState } from 'react';

export type UserPosition = { lat: number; lon: number } | null;

export function useUserLocation(): UserPosition {
  const [position, setPosition] = useState<UserPosition>(null);

  useEffect(() => {
    if (!navigator.geolocation) return;

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setPosition({ lat: pos.coords.latitude, lon: pos.coords.longitude });
      },
      () => {
        // denied/unavailable - just omit the current-location marker
        setPosition(null);
      },
      { enableHighAccuracy: false },
    );
  }, []);

  return position;
}
