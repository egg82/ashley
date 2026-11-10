// The house's location as the household page's two text boxes hold it, and as the API takes it.

export type Place = { latitude: number | null; longitude: number | null };

/** The boxes as a location: both blank is none, both numbers within range is a place; anything else is why not. */
export function parsePlace(latitude: string, longitude: string): Place | 'incomplete' | 'range' {
  const lat = latitude.trim();
  const lon = longitude.trim();
  if (!lat && !lon) return { latitude: null, longitude: null };
  if (!lat || !lon) return 'incomplete';
  const parsed = { latitude: Number(lat), longitude: Number(lon) };
  const inRange = Math.abs(parsed.latitude) <= 90 && Math.abs(parsed.longitude) <= 180;
  return inRange ? parsed : 'range';
}

/** A stored coordinate as the box shows it; blank when none is set. */
export function degrees(value: number | null): string {
  return value === null ? '' : String(value);
}
