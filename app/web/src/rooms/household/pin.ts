// Where the house is on the page's globe, from the two boxes: a pin, or why there is none.
import { parsePlace } from '../../household/place.ts';

export type Where = { pin: { x: number; y: number } } | { unknown: string };

/** The pin as a share of the globe's width and height, or the reason there is no pin. Never a default place. */
export function whereOf(latitude: string, longitude: string): Where {
  const place = parsePlace(latitude, longitude);
  if (place === 'incomplete') return { unknown: 'Set both latitude and longitude' };
  if (place === 'range') return { unknown: 'Latitude and longitude are degrees, ±90 and ±180' };
  if (place.latitude === null || place.longitude === null) return { unknown: 'No latitude or longitude set' };
  return { pin: { x: (place.longitude + 180) / 360, y: (90 - place.latitude) / 180 } };
}
