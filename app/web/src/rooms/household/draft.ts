// The household's editable fields as the room holds them while a person types, and what a save would change.
import type { Household, HouseholdRequest } from '../../api/types';
import { degrees, parsePlace } from '../../household/place.ts';

/** The request with the position as the two text boxes hold it. */
export type Draft = Omit<HouseholdRequest, 'latitude' | 'longitude'> & { latitude: string; longitude: string };

export function draftOf(h: Household): Draft {
  return {
    timezone: h.timezone, profile: h.profile, locale: h.locale, unit_system: h.unit_system, clock: h.clock,
    latitude: degrees(h.latitude), longitude: degrees(h.longitude),
  };
}

const LABELS: Record<keyof Draft, string> = {
  timezone: 'time zone', locale: 'language', clock: 'clock', unit_system: 'units', latitude: 'position', longitude: 'position',
  profile: 'notebook',
};

/** What differs between `draft` and `was`, each named once, in the order the page shows them. */
export function changedLabels(draft: Draft, was: Draft): string[] {
  const names = (Object.keys(LABELS) as (keyof Draft)[]).filter((k) => draft[k] !== was[k]).map((k) => LABELS[k]);
  return [...new Set(names)];
}

/** The request `draft` makes, or why the position is not one the API takes. */
export function requestOf(draft: Draft): HouseholdRequest | 'incomplete' | 'range' {
  const place = parsePlace(draft.latitude, draft.longitude);
  if (typeof place === 'string') return place;
  return { ...draft, ...place, timezone: draft.timezone.trim(), locale: draft.locale.trim() };
}
