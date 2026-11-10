// The household routes: the signed-in person's household's own fields.
import { ApiError, answer } from './client';
import type { Household, HouseholdRefused, HouseholdRequest } from './types';

/** The signed-in person's household: its timezone, profile, locale, units and clock. */
export async function getHousehold(): Promise<Household> {
  return answer(await fetch('/api/household'), 200, 'GET /api/household');
}

/** Replaces every field of the signed-in person's household. A 422 answers which field she cannot use. Same-origin JSON. */
export async function putHousehold(body: HouseholdRequest): Promise<Household | HouseholdRefused> {
  const response = await fetch('/api/household', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status === 422) {
    const refused = (await response.json()) as HouseholdRefused | { detail: unknown };
    if ('invalid' in refused) return refused;
    throw new ApiError(422, 'PUT /api/household');
  }
  return answer(response, 200, 'PUT /api/household');
}
