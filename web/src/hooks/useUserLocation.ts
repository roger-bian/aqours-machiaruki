import { useCallback, useEffect, useState } from 'react';

export type UserPosition = { lat: number; lon: number } | null;

function getCurrentPosition(options: PositionOptions): Promise<UserPosition> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => resolve(null), // denied/unavailable - just omit the current-location marker
      options,
    );
  });
}

export function useUserLocation() {
  const [position, setPosition] = useState<UserPosition>(null);
  const [locating, setLocating] = useState(false);

  useEffect(() => {
    getCurrentPosition({ enableHighAccuracy: false }).then(setPosition);
  }, []);

  // re-fetches at high accuracy (vs. the coarse initial mount fetch) since
  // this is a deliberate user action, not a passive background lookup
  const locate = useCallback(async () => {
    setLocating(true);
    const pos = await getCurrentPosition({ enableHighAccuracy: true });
    setPosition(pos);
    setLocating(false);
    return pos;
  }, []);

  return { position, locate, locating };
}
