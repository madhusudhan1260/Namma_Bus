import * as Location from 'expo-location';

export type Coords = { latitude: number; longitude: number };

/** Bengaluru city centre (Kempegowda Bus Station) — used only as a labelled fallback. */
export const CITY_CENTRE: Coords = { latitude: 12.9767, longitude: 77.5713 };

/** Current position only if the user has already granted permission (never prompts). */
export async function positionIfGranted(): Promise<Coords | null> {
  try {
    const { status } = await Location.getForegroundPermissionsAsync();
    if (status !== 'granted') return null;
    return await readPosition();
  } catch {
    return null;
  }
}

/** Asks for permission (after a user action) and returns the position, or null. */
export async function requestPosition(): Promise<Coords | null> {
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') return null;
    return await readPosition();
  } catch {
    return null;
  }
}

async function readPosition(): Promise<Coords | null> {
  const loc = (await Location.getLastKnownPositionAsync({})) || (await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }));
  return loc ? { latitude: loc.coords.latitude, longitude: loc.coords.longitude } : null;
}

export function distanceMeters(a: Coords, b: Coords): number {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.latitude)) * Math.cos(toRad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return Math.round(2 * R * Math.asin(Math.sqrt(h)));
}
